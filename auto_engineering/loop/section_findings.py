"""Gap Scan 章节证据的纯身份校验与规范化。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.engine.design_doc import DesignDoc


class SectionFindingValidationError(ValueError):
    """章节证据无法绑定到当前设计章节。"""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(dict.fromkeys(violations))
        super().__init__("SECTION_FINDINGS_INVALID: " + ",".join(self.violations))


def section_has_explicit_design_contract(
    design_doc: DesignDoc,
    design_section: str,
) -> bool:
    """判断章节是否已经给出可直接实现的 API、行为或验证契约。"""

    explicit_markers = {
        "heading", "list_item", "table_row", "fence", "explicit_marker",
    }
    contract_signal = re.compile(
        r"(?:`[^`]+`|->|\b(?:must|shall|returns?|stores?|reject|"
        r"implement|test(?:s|ing)?)\b|必须|应当|返回|保存|拒绝|实现|测试)",
        re.IGNORECASE,
    )
    for plate in design_doc.plates:
        for component in plate.components:
            if component.design_section != design_section:
                continue
            for item in component.design_items:
                if item.source_marker in explicit_markers:
                    return True
                text = " ".join((item.title, *item.key_claims))
                if contract_signal.search(text):
                    return True
    return False


def normalize_section_findings(
    *,
    sections: Sequence[object],
    findings: object,
    gaps: object,
    design_doc_digest: str,
) -> dict[str, Any]:
    """把 Worker 的章节发现绑定为 Core 可消费的稳定覆盖投影。

    该函数不读文件、不写状态、不依赖宿主。Core 预校验与 Host Assembler
    必须共用它，避免一处接受、另一处拒绝。
    """

    violations: list[str] = []
    expected: dict[str, Mapping[str, Any]] = {}
    expected_by_ref: dict[str, str] = {}
    for section in sections:
        if not isinstance(section, Mapping):
            violations.append("CORE_DESIGN_SECTION_INVALID")
            continue
        section_id = section.get("section_id")
        if not isinstance(section_id, str) or not section_id:
            violations.append("CORE_DESIGN_SECTION_ID_MISSING")
            continue
        if section_id in expected:
            violations.append(f"CORE_DESIGN_SECTION_DUPLICATE:{section_id}")
        expected[section_id] = section
        section_ref = section.get("design_section")
        if not isinstance(section_ref, str) or not section_ref:
            violations.append("CORE_DESIGN_SECTION_REF_MISSING")
        elif section_ref in expected_by_ref:
            violations.append(f"CORE_DESIGN_SECTION_REF_DUPLICATE:{section_ref}")
        else:
            expected_by_ref[section_ref] = section_id

    if not isinstance(findings, list):
        raise SectionFindingValidationError(
            [*violations, "SECTION_FINDINGS_REQUIRED"]
        )

    received: dict[str, Mapping[str, Any]] = {}
    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping):
            violations.append(f"SECTION_FINDING_INVALID:{index}")
            continue
        raw_section_ref = finding.get("section_ref")
        raw_section_id = finding.get("section_id")
        section_id = (
            expected_by_ref.get(raw_section_ref)
            if isinstance(raw_section_ref, str)
            else raw_section_id
        )
        evidence = finding.get("evidence")
        identifier_valid = (
            isinstance(raw_section_ref, str) and bool(raw_section_ref)
        ) or (
            isinstance(raw_section_id, str) and bool(raw_section_id)
        )
        if (
            not identifier_valid
            or finding.get("verdict") not in {"clear", "gap"}
            or not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item.strip() for item in evidence)
        ):
            violations.append(f"SECTION_FINDING_INVALID:{index}")
            continue
        if section_id not in expected:
            unknown = raw_section_ref if raw_section_ref is not None else raw_section_id
            violations.append(f"SECTION_FINDING_UNKNOWN:{unknown}")
            continue
        if section_id in received:
            violations.append(f"SECTION_FINDING_DUPLICATE:{section_id}")
            continue
        received[section_id] = finding

    for section_id in sorted(set(expected) - set(received)):
        violations.append(f"SECTION_FINDING_MISSING:{section_id}")
    if violations:
        raise SectionFindingValidationError(violations)

    coverage = [
        {
            "section_id": section_id,
            "design_section_ref": str(expected[section_id]["design_section"]),
            "verdict": str(received[section_id]["verdict"]),
            "evidence": list(received[section_id]["evidence"]),
        }
        for section_id in expected
    ]
    gap_items = gaps if isinstance(gaps, list) else []
    return {
        "scanned_sections": len(coverage),
        "has_blocking": any(
            isinstance(gap, Mapping) and gap.get("grade") == "architectural"
            for gap in gap_items
        ),
        "design_doc_digest": design_doc_digest,
        "scan_coverage": coverage,
    }


__all__ = [
    "SectionFindingValidationError",
    "normalize_section_findings",
    "section_has_explicit_design_contract",
]
