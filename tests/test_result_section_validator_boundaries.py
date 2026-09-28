"""Gap Scan 章节结果在 Core 边界的规范化测试。"""

from __future__ import annotations

from types import SimpleNamespace

from auto_engineering.loop.result_section_validator import (
    normalize_result_section_findings,
)


def _target(stage: str = "gap_scan", context: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        _state=SimpleNamespace(
            current_stage=stage,
            to_dict=lambda: {"stage": stage},
        ),
        _active_action={"context": context} if context is not None else {},
    )


def _context() -> dict[str, object]:
    return {
        "design_doc_digest": "sha256:design",
        "design_sections": [
            {"section_id": "s1", "design_section": "§1"},
            {"section_id": "s2", "design_section": "§2"},
        ],
    }


def _findings() -> list[dict[str, object]]:
    return [
        {"section_ref": "§1", "verdict": "clear", "evidence": ["已核对"]},
        {"section_ref": "§2", "verdict": "clear", "evidence": ["已核对"]},
    ]


def test_result_section_validator_is_noop_outside_gap_scan_or_without_field() -> None:
    assert normalize_result_section_findings(_target("architect"), {}) is None
    assert normalize_result_section_findings(_target(), {"gaps": []}) is None


def test_result_section_validator_reports_missing_context() -> None:
    error = normalize_result_section_findings(
        _target(), {"section_findings": []}
    )
    assert error is not None and error.error_code == "SECTION_FINDINGS_CONTEXT_MISSING"

    error = normalize_result_section_findings(
        _target(context={}), {"section_findings": []}
    )
    assert error is not None and error.error_code == "SECTION_FINDINGS_CONTEXT_MISSING"


def test_result_section_validator_normalizes_valid_findings_and_rejects_invalid() -> None:
    result: dict[str, object] = {
        "section_findings": _findings(),
        "gaps": [],
    }
    assert normalize_result_section_findings(_target(context=_context()), result) is None
    assert "section_findings" not in result
    assert result["scanned_sections"] == 2

    invalid = {"section_findings": [{"section_ref": "unknown"}]}
    error = normalize_result_section_findings(
        _target(context=_context()), invalid
    )
    assert error is not None and error.error_code == "SECTION_FINDINGS_INVALID"
