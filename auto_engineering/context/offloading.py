"""Stage context offloading — persist stage conversations to disk.

Design ref: v5.6-Design-Loop.md appendix E §E.2.2 (T53).

ContextOffloader is a pure storage/retrieval layer — it does NOT call an LLM.
Summary generation happens upstream (TickOrchestrator) before offload() is called.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class StageContextOffload:
    """Single stage's context offload artifact.

    After each stage completes, the full conversation history is persisted
    to disk.  Downstream stages load only the structured summary — not the
    raw messages — unless they explicitly need to backtrack.
    """

    stage: str
    round_number: int
    timestamp: str
    summary: str
    key_decisions: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    gate_results: dict[str, str] = field(default_factory=dict)
    raw_context_path: str = ""


class ContextOffloader:
    """Manages stage context offloading and retrieval.

    Usage::

        offloader = ContextOffloader(Path(".ae-state/offload"))
        offload = offloader.offload(
            stage="architect", messages=[...],
            summary="Designed payment module.",
            key_decisions=["Use clean architecture"],
            files_changed=[], gate_results={},
        )
        # Later — load just the summary (cheap):
        summary = offloader.load_summary("architect")
        # Or load the full conversation (expensive, only when backtracking):
        full = offloader.load_full_context("architect")
    """

    def __init__(self, offload_dir: Path) -> None:
        self._dir = offload_dir
        self._round_counter: int = 0

    # ---- public API ----------------------------------------------------

    def offload(
        self,
        stage: str,
        messages: list[dict],
        summary: str,
        key_decisions: list[str],
        files_changed: list[str],
        gate_results: dict,
    ) -> StageContextOffload:
        """Persist the stage's full conversation and return a summary artifact."""
        self._round_counter += 1
        self._dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).isoformat()
        filename = f"{stage}-r{self._round_counter}.json"
        filepath = self._dir / filename

        payload = {
            "stage": stage,
            "round_number": self._round_counter,
            "timestamp": timestamp,
            "summary": summary,
            "key_decisions": key_decisions,
            "files_changed": files_changed,
            "gate_results": gate_results,
            "messages": messages,
        }
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        return StageContextOffload(
            stage=stage,
            round_number=self._round_counter,
            timestamp=timestamp,
            summary=summary,
            key_decisions=list(key_decisions),
            files_changed=list(files_changed),
            gate_results=dict(gate_results),
            raw_context_path=str(filepath),
        )

    def load_summary(self, stage: str) -> StageContextOffload | None:
        """Load just the metadata for *stage* (cheap — no messages)."""
        path = self._find_latest(stage)
        if path is None:
            return None
        data = json.loads(path.read_text())
        return StageContextOffload(
            stage=data["stage"],
            round_number=data["round_number"],
            timestamp=data["timestamp"],
            summary=data["summary"],
            key_decisions=data.get("key_decisions", []),
            files_changed=data.get("files_changed", []),
            gate_results=data.get("gate_results", {}),
            raw_context_path=str(path),
        )

    def load_full_context(self, stage: str) -> list[dict] | None:
        """Load full conversation history for *stage* (expensive)."""
        path = self._find_latest(stage)
        if path is None:
            return None
        data = json.loads(path.read_text())
        return data.get("messages", [])

    # ---- internal ------------------------------------------------------

    def _find_latest(self, stage: str) -> Path | None:
        """Return the newest offload file for *stage*, or None."""
        if not self._dir.exists():
            return None
        candidates = sorted(
            self._dir.glob(f"{stage}-r*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None
