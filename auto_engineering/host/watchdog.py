"""宿主边界 watchdog。

该模块只观察宿主输出和已提交的 Core/Host 事实，并在有界条件触发时
终止宿主进程。它不创建 Action、不推进 Tick，也不启动 Worker。启动入口
必须由 ``scripts/ae-run --run-module`` 提供，以保证 watchdog 与产品使用同一
个锁定运行时；禁止退回系统 ``python3``。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from sqlite3 import Error as SQLiteError

from auto_engineering.loop.event_store import SQLiteEventStore

NATIVE_OBSERVATION_MAX_AGE_SECONDS = 300.0
# 项目运行时首次 bootstrap、宿主启动和第一条 native observation 可能跨越一个
# watchdog 调度周期；该宽限只对已存在且身份完整的 Claude CONTINUE lease 生效，
# 无 lease 的首个 init 仍由 max_idle 直接封口。宽限必须短于宿主 idle 上限的
# 常见测试窗口，避免把“有效 lease”误当成“宿主仍有 native 进展”。
NATIVE_OBSERVATION_STARTUP_GRACE_SECONDS = 2.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument("host_pid", type=int)
    parser.add_argument("attempt_output", type=Path)
    parser.add_argument("max_idle", type=float)
    parser.add_argument("max_runtime", nargs="?")
    parser.add_argument("max_protocol_refusals", type=int)
    parser.add_argument("max_coordinator_polls", type=int)
    parser.add_argument("protocol_pattern")
    parser.add_argument("idle_marker", type=Path)
    parser.add_argument("timeout_marker", type=Path)
    parser.add_argument("protocol_marker", type=Path)
    parser.add_argument("coordinator_marker", type=Path)
    parser.add_argument("state_root", type=Path)
    parser.add_argument("attempt_started_epoch", type=float)
    return parser


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        state = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return True
    return bool(state) and not state.startswith("Z")


def _terminate(pid: int, marker: Path) -> None:
    marker.touch()
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _alive(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _event_store_semantic_signature(path: Path) -> object | None:
    """通过 canonical EventStore API 读取已提交事实，不信任数据库 mtime。"""

    try:
        with SQLiteEventStore(path, read_only=True) as event_store:
            return event_store.semantic_signature()
    except (OSError, SQLiteError, TypeError, ValueError, RuntimeError):
        return None


def _state_signature(state_root: Path) -> tuple[tuple[str, str, int], ...]:
    """只观察当前 Action 的 Core/Host 已提交事实目录。"""

    event_store_path = state_root / "events.db"
    watched_paths = (
        event_store_path,
        state_root / "host-runtime" / "worker-outcomes",
        state_root / "host-runtime" / "outcomes",
    )
    content_watched = {
        state_root / "host-runtime" / "worker-outcomes",
        state_root / "host-runtime" / "outcomes",
    }
    entries: list[tuple[str, str, int]] = []
    for watched in watched_paths:
        try:
            is_directory = watched.is_dir()
        except OSError:
            continue
        if is_directory:
            for root, directories, files in os.walk(watched, followlinks=False):
                directories[:] = [name for name in directories if name != ".ae-runtime"]
                for name in files:
                    path = Path(root) / name
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    marker = _content_marker(path) if watched in content_watched else str(
                        stat.st_mtime_ns
                    )
                    if marker is None:
                        continue
                    entries.append((str(path), marker, stat.st_size))
            continue
        try:
            stat = watched.stat()
        except OSError:
            continue
        if watched == event_store_path:
            semantic = _event_store_semantic_signature(watched)
            if semantic is None:
                continue
            entries.append((str(watched), "event-store:" + repr(semantic), 0))
        # 当前 watched_paths 的非目录项只有 events.db；所有宿主 outcome 文件
        # 都按目录内容处理，避免引入无法到达的第二套文件签名规则。
    return tuple(sorted(entries))


def _content_marker(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
        try:
            normalized = json.dumps(
                json.loads(raw),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            normalized = raw
        return hashlib.sha256(normalized).hexdigest()
    except OSError:
        return None


def _native_sync_wait_active(
    *,
    state_root: Path,
    attempt_started_epoch: float,
    max_idle: float,
) -> bool:
    """只接受当前 lease 绑定且处于有效窗口的 native running 观察。"""

    lease_path = state_root / "host-runtime" / "active-lease.json"
    try:
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        not isinstance(lease, dict)
        or lease.get("platform") != "claude-code"
        or lease.get("disposition") != "CONTINUE"
    ):
        return False
    action_message_id = lease.get("action_message_id")
    generation = lease.get("execution_generation", 1)
    fencing_token = lease.get("fencing_token")
    if (
        not isinstance(action_message_id, str)
        or not isinstance(generation, int)
        or not isinstance(fencing_token, str)
        or not re.fullmatch(r"[0-9a-f]{64}", fencing_token)
    ):
        return False
    now_epoch = time.time()
    # 首次 observation 到达前，必须同时满足“当前 watchdog 确实由 Claude
    # 宿主边界启动”和“lease 身份完整”。仅凭持久化 lease 不能把任意沉默
    # 宿主误判为 native wait，否则普通宿主会绕过 max_idle。
    if (
        os.environ.get("AE_HOST_PLATFORM") == "claude-code"
        and now_epoch - attempt_started_epoch
        <= max_idle + NATIVE_OBSERVATION_STARTUP_GRACE_SECONDS
    ):
        return True
    observations_root = state_root / "host-runtime" / "worker-observations"
    if not observations_root.is_dir():
        return False
    max_observation_age = max(NATIVE_OBSERVATION_MAX_AGE_SECONDS, max_idle)
    for directory, _, files in os.walk(observations_root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            try:
                observation = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            observed_at = observation.get("observed_at") if isinstance(observation, dict) else None
            if not isinstance(observed_at, str) or not observed_at:
                continue
            try:
                normalized = re.sub(r"\.(\d{6})\d+(?=(?:Z|[+-]\d{2}:?\d{2})$)", r".\1", observed_at)
                normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
                observed_epoch = datetime.fromisoformat(normalized).timestamp()
            except ValueError:
                continue
            if (
                isinstance(observation, dict)
                and observation.get("action_message_id") == action_message_id
                and observation.get("execution_generation") == generation
                and observation.get("fencing_token") == fencing_token
                and observation.get("native_status") == "running"
                and observed_epoch + 2.0 >= attempt_started_epoch
                and observed_epoch <= now_epoch + 2.0
                and now_epoch - observed_epoch <= max_observation_age
            ):
                return True
    return False


def _meaningful_stream_activity(lines: list[str], *, terminal_seen: bool) -> tuple[bool, bool]:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        event_type = value.get("type")
        if event_type in {"result", "turn.completed", "response.completed"}:
            if terminal_seen:
                continue
            return True, True
        if event_type == "message" and value.get("is_api_error_message"):
            if terminal_seen:
                continue
            return True, True
        if event_type == "item.completed":
            item = value.get("item")
            if isinstance(item, dict) and item.get("type") in {
                "agent_message", "assistant_message"
            }:
                return True, terminal_seen
    return False, terminal_seen


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    max_runtime = float(args.max_runtime) if args.max_runtime else None
    protocol_pattern = re.compile(args.protocol_pattern)
    resume_pattern = re.compile(r"dev-loop\s+--resume\s+[0-9a-fA-F-]{36}")
    state_root = args.state_root
    started = time.monotonic()
    last_activity = started
    offset = 0
    pending = ""
    protocol_refusals = 0
    coordinator_polls = 0
    terminal_seen = False
    previous_state = _state_signature(state_root)

    while _alive(args.host_pid):
        time.sleep(1)
        now = time.monotonic()
        try:
            size = args.attempt_output.stat().st_size
        except OSError:
            size = 0
        if size != offset:
            if size < offset:
                offset = 0
                pending = ""
            try:
                with args.attempt_output.open("rb") as stream:
                    stream.seek(offset)
                    chunk = stream.read()
            except OSError:
                chunk = b""
            offset += len(chunk)
            text = pending + chunk.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            pending = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                pending = lines.pop()
            protocol_refusals += sum(len(protocol_pattern.findall(line)) for line in lines)
            coordinator_polls += sum(len(resume_pattern.findall(line)) for line in lines)
            meaningful, terminal_seen = _meaningful_stream_activity(
                lines, terminal_seen=terminal_seen
            )
            if meaningful:
                last_activity = now
        current_state = _state_signature(state_root)
        if current_state != previous_state:
            last_activity = now
            previous_state = current_state
        if protocol_refusals >= args.max_protocol_refusals:
            if _alive(args.host_pid):
                _terminate(args.host_pid, args.protocol_marker)
            break
        if coordinator_polls >= args.max_coordinator_polls:
            if _alive(args.host_pid):
                _terminate(args.host_pid, args.coordinator_marker)
            break
        native_active = _native_sync_wait_active(
            state_root=state_root,
            attempt_started_epoch=args.attempt_started_epoch,
            max_idle=args.max_idle,
        )
        # 首个 init 前尚未有 lease，但宿主已经由外层适配器启动；没有 lease
        # 不能成为无限等待的豁免。此阶段没有 Action-scoped 事实可观察时，
        # max_idle 仍是唯一有界启动窗口；一旦进入 native Worker 等待，
        # _native_sync_wait_active 才能按当前 Action 合同保留观察时间。
        if now - last_activity >= args.max_idle and not native_active:
            if _alive(args.host_pid):
                _terminate(args.host_pid, args.idle_marker)
            break
        if max_runtime is not None and now - started >= max_runtime:
            if _alive(args.host_pid):
                _terminate(args.host_pid, args.timeout_marker)
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
