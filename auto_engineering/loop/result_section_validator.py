"""Gap Scan 章节发现规范化的 canonical boundary。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ErrorResponse
from auto_engineering.loop.section_findings import (
    SectionFindingValidationError,
    normalize_section_findings,
)


class SectionValidationTarget(Protocol):
    _state: EngineState
    _active_action: dict[str, Any] | None


def normalize_result_section_findings(
    target: SectionValidationTarget, result: dict,
) -> ErrorResponse | None:
    """在任何状态推进前统一校验并规范化原始章节发现。"""
    if target._state.current_stage != "gap_scan":
        return None
    if "section_findings" not in result:
        return None
    active = target._active_action if isinstance(target._active_action, dict) else {}
    context = active.get("context")
    if not isinstance(context, Mapping):
        return ErrorResponse(
            "SECTION_FINDINGS_CONTEXT_MISSING",
            "当前 Gap Scan Action 缺少稳定设计章节上下文",
            target._state.to_dict(),
        )
    sections = context.get("design_sections")
    if not isinstance(sections, list) or not sections:
        return ErrorResponse(
            "SECTION_FINDINGS_CONTEXT_MISSING",
            "当前 Gap Scan Action 缺少可校验的设计章节集合",
            target._state.to_dict(),
        )
    try:
        projection = normalize_section_findings(
            sections=sections,
            findings=result.get("section_findings"),
            gaps=result.get("gaps", []),
            design_doc_digest=str(context.get("design_doc_digest", "")),
        )
    except SectionFindingValidationError as exc:
        return ErrorResponse(
            "SECTION_FINDINGS_INVALID",
            "；".join(exc.violations),
            target._state.to_dict(),
            suggestion=(
                "只使用当前 Action context.design_sections 中的 canonical "
                "design_section，并一次性补齐全部章节。"
            ),
        )
    result.pop("section_findings", None)
    result.update(projection)
    return None
