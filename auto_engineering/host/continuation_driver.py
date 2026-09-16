"""宿主进程返回后的自动续驱动纯决策。

该模块只判断是否应再次交给同一宿主命令，不创建 Worker、不调用 Tick，
也不改变 Core 状态。实际启动仍由宿主边界脚本负责。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def should_resume_host(
    status: Mapping[str, Any] | None,
    lease: Mapping[str, Any] | None,
    outcome_journal_dir: Path | None = None,
) -> bool:
    """仅在 Core 明确要求继续且仍有 active Action 时允许续跑。

    OutcomeJournal 是宿主交接的事实证据，不是 Loop 状态源。若当前 Action
    的 Result 修复预算已耗尽，继续 resume 只会重复同一个坏路径，必须停下让
    人工修复宿主合同后显式恢复。
    """

    if not isinstance(status, Mapping) or not isinstance(lease, Mapping):
        return False
    active_action = status.get("active_action")
    next_operation = status.get("next_operation")
    if not isinstance(active_action, Mapping) or not active_action:
        return False
    if not isinstance(next_operation, Mapping):
        return False
    if next_operation.get("operation") != "resume_active_action":
        return False
    # CONTINUE 只是执行意图，不是 Action 身份。续驱动前必须确认 status、
    # next_operation 与 lease 指向同一个 thread/action，避免旧宿主租约把新
    # active Action 错误地重新交给宿主。
    status_thread_id = status.get("thread_id")
    active_message_id = active_action.get("message_id")
    operation_thread_id = next_operation.get("thread_id")
    lease_thread_id = lease.get("thread_id")
    lease_message_id = lease.get("action_message_id")
    if not all(
        isinstance(value, str) and value
        for value in (
            status_thread_id,
            active_message_id,
            operation_thread_id,
            lease_thread_id,
            lease_message_id,
        )
    ):
        return False
    if (
        status_thread_id != lease_thread_id
        or operation_thread_id != lease_thread_id
        or active_message_id != lease_message_id
    ):
        return False
    if not isinstance(active_message_id, str):
        return False
    if isinstance(outcome_journal_dir, Path) and _repair_is_exhausted(
        outcome_journal_dir, active_message_id
    ):
        return False
    return (
        lease.get("disposition") == "CONTINUE"
        and lease.get("continuation_required") is True
        and lease.get("yield_allowed") is False
    )


def _repair_is_exhausted(journal_dir: Path, action_message_id: str) -> bool:
    """检查当前 Action 的宿主交接记录是否已进入不可修复终态。"""

    if Path(action_message_id).name != action_message_id or "\\" in action_message_id:
        return True
    journal_path = journal_dir / f"{action_message_id}.json"
    if not journal_path.is_file():
        return False
    record = _read_mapping(journal_path)
    if record is None or record.get("action_message_id") != action_message_id:
        return True
    return (
        record.get("status") in {"rejected", "assembly_rejected"}
        and record.get("repairable") is False
    )


def _read_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--lease-file", type=Path, required=True)
    parser.add_argument("--outcome-journal-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print("resume" if should_resume_host(
        _read_mapping(args.status_file),
        _read_mapping(args.lease_file),
        args.outcome_journal_dir,
    ) else "stop")
    return 0


__all__ = ["main", "should_resume_host"]


if __name__ == "__main__":
    raise SystemExit(main())
