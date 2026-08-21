"""SessionTranscriptParser — Claude Code JSONL session transcript parser (T110a).

Reads Claude Code's default JSONL session transcript files to extract per-tick
token usage in Agent-driven Tick mode. Claude Code writes each API response's
``usage`` block to ``~/.claude/projects/<encoded-cwd>/<uuid>.jsonl``.

Design ref: v5.6-Design-Loop.md, IMPLEMENTATION-TRACKER.md T110.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Claude Code session transcript directory
_CC_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def _encode_cwd(cwd: str) -> str:
    """Encode a project directory path the same way Claude Code does.

    Claude Code replaces every path character outside ``[A-Za-z0-9-]`` with
    ``-`` when naming the project transcript directory.
    """
    return re.sub(r"[^A-Za-z0-9-]", "-", cwd)


class SessionTranscriptParser:
    """Incremental parser for Claude Code JSONL session transcripts.

    Reads ``type=="assistant"`` lines from the session JSONL, extracts
    ``message.usage``, and records positive cumulative deltas per transcript
    file and ``message.id`` so streamed updates are not lost or double-counted.

    Usage::

        parser = SessionTranscriptParser(project_root)
        usage = parser.collect()  # returns {input_tokens, output_tokens, model}
        # Next tick: parser.collect() reads only new lines
    """

    def __init__(self, project_root: str | Path) -> None:
        self._project_root = Path(project_root).resolve()
        self._encoded_cwd = _encode_cwd(str(self._project_root))
        self._session_dir = _CC_PROJECTS_DIR / self._encoded_cwd
        self._offset: int = 0  # byte offset in the main session file
        self._message_usage: dict[tuple[str, str], tuple[int, int, int, int]] = {}
        self._current_session_file: Path | None = None
        self._subagent_offset: dict[str, int] = {}

    # ---- public API ----------------------------------------------------

    def collect(self) -> dict[str, Any]:
        """Collect token usage from new JSONL lines since last call.

        Returns:
            dict with keys: input_tokens, output_tokens, model, message_count,
            source. All values are zero if no new data.
        """
        if not self._session_dir.exists():
            return self._empty_result()

        session_file = self._find_latest_session()
        if session_file is None:
            return self._empty_result()

        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0
        models: set[str] = set()
        message_count = 0

        # Main session file — incremental read
        try:
            new_offset, input_t, output_t, cache_read, cache_write, models_set, msg_count = (
                self._read_incremental(session_file, self._offset))
            self._offset = new_offset
            total_input += input_t
            total_output += output_t
            total_cache_read += cache_read
            total_cache_write += cache_write
            models.update(models_set)
            message_count += msg_count
        except (json.JSONDecodeError, OSError):
            _logger.debug("Failed to read main session file", exc_info=True)

        # Current Claude stores workers under <session-id>/subagents. Keep the
        # former flat location as a read-only compatibility fallback.
        subagent_dirs = (
            session_file.parent / session_file.stem / "subagents",
            session_file.parent / "subagents",
        )
        for subagent_dir in subagent_dirs:
            if not subagent_dir.exists():
                continue
            try:
                for agent_file in sorted(subagent_dir.glob("agent-*.jsonl")):
                    fkey = str(agent_file)
                    sub_off = self._subagent_offset.get(fkey, 0)
                    try:
                        (
                            new_off, input_t, output_t, cache_read,
                            cache_write, models_set, msg_count,
                        ) = (
                            self._read_incremental(agent_file, sub_off))
                        self._subagent_offset[fkey] = new_off
                        total_input += input_t
                        total_output += output_t
                        total_cache_read += cache_read
                        total_cache_write += cache_write
                        models.update(models_set)
                        message_count += msg_count
                    except (OSError, UnicodeDecodeError, ValueError):
                        _logger.debug(
                            "Failed to read subagent file %s", agent_file,
                            exc_info=True)
            except (OSError, ValueError):
                _logger.debug("Failed to scan subagent dir", exc_info=True)

        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cache_read_tokens": total_cache_read,
            "cache_write_tokens": total_cache_write,
            "model": ", ".join(sorted(models)) if models else "unknown",
            "message_count": message_count,
            "source": "transcript",
            "usage_source": "claude-transcript",
            "provider": "anthropic",
        }

    def reset(self) -> None:
        """Reset parser state (offset + message usage) for a new session."""
        self._offset = 0
        self._message_usage.clear()
        self._subagent_offset.clear()
        self._current_session_file = None

    # ---- internal ------------------------------------------------------

    def _find_latest_session(self) -> Path | None:
        """Find the most recently modified .jsonl session file."""
        try:
            candidates = sorted(
                self._session_dir.glob("*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            return candidates[0] if candidates else None
        except OSError:
            return None

    def _read_incremental(
        self, filepath: Path, offset: int,
    ) -> tuple[int, int, int, int, int, set[str], int]:
        """Read new lines from *filepath* starting at *offset*.

        Returns (new_offset, input_tokens, output_tokens, models_set, msg_count).
        """
        try:
            stat = filepath.stat()
        except OSError:
            return offset, 0, 0, 0, 0, set(), 0

        file_size = stat.st_size
        if offset >= file_size:
            return offset, 0, 0, 0, 0, set(), 0

        with open(filepath, encoding="utf-8") as fh:
            fh.seek(offset)
            raw = fh.read()

        new_offset = offset + len(raw.encode("utf-8"))
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0
        models: set[str] = set()
        msg_count = 0

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message", {})
            msg_id = msg.get("id", "")
            usage = msg.get("usage", {})
            if usage:
                usage_values = tuple(
                    int(usage.get(name, 0) or 0)
                    for name in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                current = (
                    usage_values[0], usage_values[1],
                    usage_values[2], usage_values[3],
                )
                key = (str(filepath), msg_id) if msg_id else None
                previous = self._message_usage.get(key, (0, 0, 0, 0)) if key else (
                    0, 0, 0, 0
                )
                deltas = tuple(
                    max(value - previous[index], 0)
                    for index, value in enumerate(current)
                )
                total_input += deltas[0]
                total_output += deltas[1]
                total_cache_read += deltas[2]
                total_cache_write += deltas[3]
                if key is None or key not in self._message_usage:
                    msg_count += 1
                if key is not None:
                    self._message_usage[key] = (
                        max(current[0], previous[0]),
                        max(current[1], previous[1]),
                        max(current[2], previous[2]),
                        max(current[3], previous[3]),
                    )
            model = msg.get("model", "")
            if model:
                models.add(model)

        return (
            new_offset,
            total_input,
            total_output,
            total_cache_read,
            total_cache_write,
            models,
            msg_count,
        )

    def _empty_result(self) -> dict[str, Any]:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "model": "unknown",
            "message_count": 0,
            "source": "transcript",
            "usage_source": "claude-transcript",
            "provider": "anthropic",
        }


class CodexSessionTranscriptParser:
    """Incrementally project Codex rollout usage for one parent thread."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        thread_id: str,
        sessions_root: Path = _CODEX_SESSIONS_DIR,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._thread_id = thread_id
        self._sessions_root = sessions_root.expanduser().resolve()
        self._main_file: Path | None = None
        self._file_totals: dict[str, tuple[int, int, int, int]] = {}

    def collect(self) -> dict[str, Any]:
        main = self._main_file or self._find_main_file()
        if main is None:
            return self._empty_result()
        self._main_file = main
        files = [main]
        try:
            candidates = sorted(main.parent.glob("*.jsonl"))
        except OSError:
            candidates = []
        for candidate in candidates:
            if candidate != main and self._is_child(candidate):
                files.append(candidate)

        totals = [0, 0, 0, 0]
        models: set[str] = set()
        changed_files = 0
        for path in files:
            current, model, found = self._read_cumulative(path)
            if not found:
                continue
            key = str(path)
            previous = self._file_totals.get(key, (0, 0, 0, 0))
            deltas = tuple(
                max(current[index] - previous[index], 0)
                for index in range(4)
            )
            for index, value in enumerate(deltas):
                totals[index] += value
            if any(deltas):
                changed_files += 1
            self._file_totals[key] = tuple(
                max(current[index], previous[index]) for index in range(4)
            )  # type: ignore[assignment]
            if model:
                models.add(model)
        return {
            "input_tokens": totals[0],
            "output_tokens": totals[3],
            "cache_read_tokens": totals[1],
            "cache_write_tokens": totals[2],
            "model": ", ".join(sorted(models)) if models else "unknown",
            "message_count": changed_files,
            "source": "transcript",
            "usage_source": "codex-rollout",
            "provider": "openai",
        }

    def reset(self) -> None:
        self._main_file = None
        self._file_totals.clear()

    def _find_main_file(self) -> Path | None:
        try:
            candidates = sorted(
                self._sessions_root.rglob(f"*{self._thread_id}.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None
        for candidate in candidates:
            meta = self._read_meta(candidate)
            if (
                meta.get("thread_source") != "subagent"
                and meta.get("session_id") == self._thread_id
                and self._same_project(meta.get("cwd"))
            ):
                return candidate
        return None

    def _is_child(self, path: Path) -> bool:
        meta = self._read_meta(path)
        return (
            meta.get("thread_source") == "subagent"
            and meta.get("parent_thread_id") == self._thread_id
            and self._same_project(meta.get("cwd"))
        )

    def _same_project(self, raw: object) -> bool:
        if not isinstance(raw, str) or not raw:
            return False
        try:
            return Path(raw).resolve() == self._project_root
        except OSError:
            return False

    @staticmethod
    def _read_meta(path: Path) -> dict[str, Any]:
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    entry = json.loads(line)
                    if entry.get("type") == "session_meta":
                        payload = entry.get("payload")
                        return dict(payload) if isinstance(payload, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {}

    @staticmethod
    def _read_cumulative(
        path: Path,
    ) -> tuple[tuple[int, int, int, int], str, bool]:
        latest: tuple[int, int, int, int] | None = None
        model = ""
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = entry.get("payload", {})
                    if entry.get("type") == "turn_context":
                        value = payload.get("model")
                        if isinstance(value, str):
                            model = value
                    if not (
                        entry.get("type") == "event_msg"
                        and payload.get("type") == "token_count"
                    ):
                        continue
                    usage = payload.get("info", {}).get("total_token_usage")
                    if not isinstance(usage, dict):
                        continue
                    raw_input = int(usage.get("input_tokens", 0) or 0)
                    cached = int(usage.get("cached_input_tokens", 0) or 0)
                    cache_write = int(
                        usage.get("cache_write_input_tokens", 0) or 0
                    )
                    output = int(usage.get("output_tokens", 0) or 0)
                    latest = (
                        max(raw_input - cached - cache_write, 0),
                        cached,
                        cache_write,
                        output,
                    )
        except (OSError, UnicodeDecodeError):
            return (0, 0, 0, 0), model, False
        return latest or (0, 0, 0, 0), model, latest is not None

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "model": "unknown",
            "message_count": 0,
            "source": "transcript",
            "usage_source": "codex-rollout",
            "provider": "openai",
        }


def create_parser(
    project_root: str | Path,
) -> SessionTranscriptParser | CodexSessionTranscriptParser | None:
    """Factory: create a parser if AE_TOKEN_TRACKING is enabled.

    Returns None if token tracking is disabled (default), so callers can
    skip the JSONL I/O entirely.
    """
    from auto_engineering.config.runtime_config import get_default_config
    _cfg = get_default_config()
    if not _cfg.metrics_enabled:
        return None
    if not _cfg.token_tracking_enabled:
        return None
    from auto_engineering.host import HostPlatform, detect_host, usage_source_for
    platform = detect_host().platform
    if usage_source_for(platform) is None:
        return None
    if platform is HostPlatform.CLAUDE_CODE:
        return SessionTranscriptParser(project_root)
    if platform is HostPlatform.CODEX:
        thread_id = os.environ.get("CODEX_THREAD_ID")
        if thread_id:
            return CodexSessionTranscriptParser(
                project_root,
                thread_id=thread_id,
            )
    return None
