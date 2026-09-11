"""方案 A A002：Gap Scan 章节证据必须由同一纯校验器规范化。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.section_findings import (
    SectionFindingValidationError,
    normalize_section_findings,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _sections() -> list[dict[str, str]]:
    return [
        {"section_id": "s1", "design_section": "§1"},
        {"section_id": "s2", "design_section": "§2"},
    ]


def _finding(section_ref: str) -> dict[str, object]:
    return {
        "section_ref": section_ref,
        "verdict": "clear",
        "evidence": [f"已核对 {section_ref}"],
    }


def test_normalize_section_findings_returns_canonical_coverage() -> None:
    projected = normalize_section_findings(
        sections=_sections(),
        findings=[_finding("§1"), _finding("§2")],
        gaps=[],
        design_doc_digest="sha256:design",
    )

    assert projected["scanned_sections"] == 2
    assert projected["design_doc_digest"] == "sha256:design"
    assert [item["section_id"] for item in projected["scan_coverage"]] == [
        "s1", "s2"
    ]


@pytest.mark.parametrize(
    ("findings", "violation"),
    [
        ([_finding("§404"), _finding("§2")], "SECTION_FINDING_UNKNOWN:§404"),
        ([_finding("§1")], "SECTION_FINDING_MISSING:s2"),
        ([_finding("§1"), _finding("§1")], "SECTION_FINDING_DUPLICATE:s1"),
    ],
)
def test_normalize_section_findings_reports_all_identity_violations(
    findings: list[dict[str, object]], violation: str,
) -> None:
    with pytest.raises(SectionFindingValidationError) as raised:
        normalize_section_findings(
            sections=_sections(),
            findings=findings,
            gaps=[],
            design_doc_digest="sha256:design",
        )

    assert violation in raised.value.violations


def test_core_rejects_raw_section_findings_before_progression(tmp_path) -> None:
    orchestrator = TickOrchestrator(
        project_root=tmp_path,
    )
    orchestrator._state = EngineState(
        thread_id="thread-1",
        current_stage="gap_scan",
        design_doc_digest="sha256:design",
    )
    orchestrator._active_action = {
        "message_id": "action-1",
        "context": {
            "design_doc_digest": "sha256:design",
            "design_sections": _sections(),
        },
    }
    result = {
        "stage": "gap_scan",
        "section_findings": [_finding("§404"), _finding("§2")],
    }

    error = orchestrator._normalize_result_section_findings(result)

    assert error is not None
    assert error.error_code == "SECTION_FINDINGS_INVALID"
    assert "SECTION_FINDING_UNKNOWN:§404" in error.message
    assert "SECTION_FINDING_MISSING:s1" in error.message
