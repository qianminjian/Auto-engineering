"""SessionTranscriptParser — Claude Code JSONL session transcript parser (T110a).

Reads Claude Code's default JSONL session transcript files to extract per-tick
token usage in Agent-driven Tick mode. Claude Code writes each API response's
``usage`` block to ``~/.claude/projects/<encoded-cwd>/<uuid>.jsonl``.

Design ref: v5.6-Design-Loop.md, IMPLEMENTATION-TRACKER.md T110.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Claude Code session transcript directory
_CC_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _encode_cwd(cwd: str) -> str:
    """Encode a project directory path the same way Claude Code does.

    Claude Code replaces '/' with '-' in the absolute path.
    """
    return cwd.lstrip("/").replace("/", "-")


class SessionTranscriptParser:
    """Incremental parser for Claude Code JSONL session transcripts.

    Reads ``type=="assistant"`` lines from the session JSONL, extracts
    ``message.usage``, and deduplicates by ``message.id``.

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
        self._seen_message_ids: set[str] = set()
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
        models: set[str] = set()
        message_count = 0

        # Main session file — incremental read
        try:
            new_offset, input_t, output_t, models_set, msg_count = (
                self._read_incremental(session_file, self._offset))
            self._offset = new_offset
            total_input += input_t
            total_output += output_t
            models.update(models_set)
            message_count += msg_count
        except (json.JSONDecodeError, OSError):
            _logger.debug("Failed to read main session file", exc_info=True)

        # Subagent files — scan subagents/ directory
        subagent_dir = session_file.parent / "subagents"
        if subagent_dir.exists():
            try:
                for agent_file in sorted(subagent_dir.glob("agent-*.jsonl")):
                    fkey = str(agent_file)
                    sub_off = self._subagent_offset.get(fkey, 0)
                    try:
                        new_off, input_t, output_t, models_set, msg_count = (
                            self._read_incremental(agent_file, sub_off))
                        self._subagent_offset[fkey] = new_off
                        total_input += input_t
                        total_output += output_t
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
            "model": ", ".join(sorted(models)) if models else "unknown",
            "message_count": message_count,
            "source": "transcript",
            "usage_source": "claude-transcript",
            "provider": "anthropic",
        }

    def reset(self) -> None:
        """Reset parser state (offset + seen IDs) for a new session."""
        self._offset = 0
        self._seen_message_ids.clear()
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
    ) -> tuple[int, int, int, set[str], int]:
        """Read new lines from *filepath* starting at *offset*.

        Returns (new_offset, input_tokens, output_tokens, models_set, msg_count).
        """
        try:
            stat = filepath.stat()
        except OSError:
            return offset, 0, 0, set(), 0

        file_size = stat.st_size
        if offset >= file_size:
            return offset, 0, 0, set(), 0

        with open(filepath, encoding="utf-8") as fh:
            fh.seek(offset)
            raw = fh.read()

        new_offset = offset + len(raw.encode("utf-8"))
        total_input = 0
        total_output = 0
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
            if msg_id and msg_id in self._seen_message_ids:
                continue
            if msg_id:
                self._seen_message_ids.add(msg_id)
            usage = msg.get("usage", {})
            if usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
                msg_count += 1
            model = msg.get("model", "")
            if model:
                models.add(model)

        return new_offset, total_input, total_output, models, msg_count

    def _empty_result(self) -> dict[str, Any]:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "model": "unknown",
            "message_count": 0,
            "source": "transcript",
            "usage_source": "claude-transcript",
            "provider": "anthropic",
        }


def create_parser(project_root: str | Path) -> SessionTranscriptParser | None:
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
    from auto_engineering.host import detect_host, usage_source_for
    if usage_source_for(detect_host().platform) is None:
        return None
    return SessionTranscriptParser(project_root)
