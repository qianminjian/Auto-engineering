"""ActionBuilder 上下文摘要的 canonical 纯投影。"""

from __future__ import annotations

import json
from typing import Protocol

from auto_engineering.engine.state import EngineState


class ActionContextTarget(Protocol):
    @property
    def _state(self) -> EngineState: ...


def gap_scan_summary(target: ActionContextTarget) -> dict[str, object] | None:
    """把已接受的 Gap Scan 结论投影为有界前台摘要。"""
    if target._state.current_stage not in {"gap_review", "research", "architect"}:
        return None
    raw = target._state.gap_report_json
    if not raw:
        return None
    report = json.loads(raw)
    if not report.get("design_doc_digest"):
        return None
    gaps = report.get("gaps", [])
    if target._state.current_stage == "gap_review":
        outcome = "user_decision_required"
    elif target._state.current_stage == "research":
        outcome = "research_in_progress"
    elif gaps:
        outcome = "gaps_resolved"
    else:
        outcome = "no_gaps_auto_continue"
    return {
        "design_doc_digest": report.get("design_doc_digest", ""),
        "scanned_sections": report.get("scanned_sections", 0),
        "gap_count": len(gaps),
        "has_blocking": bool(report.get("has_blocking", False)),
        "outcome": outcome,
    }
