"""Tick Result 校验 canonical service。

TickOrchestrator 只负责生命周期与委托；本模块集中保存跨 stage 的 Result
边界校验，避免在编排器中形成第二套校验逻辑。
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ErrorResponse
from auto_engineering.loop.engineering_model import EngineeringModel
from auto_engineering.loop.result_section_validator import (
    normalize_result_section_findings,
)
from auto_engineering.loop.section_findings import section_has_explicit_design_contract

__all__ = [
    "normalize_result_section_findings",
    "validate_component_verifier_scope",
    "validate_gap_analysis",
    "validate_gap_review_decisions",
]


class ResultValidationTarget(Protocol):
    """Result 校验需要的最小 Orchestrator 视图。"""

    _state: EngineState
    _design_doc: DesignDoc | None
    _active_action: dict[str, Any] | None


def validate_gap_analysis(target: ResultValidationTarget, result: dict) -> ErrorResponse | None:
    """Gap Scan 必须提供足以让用户判断的完整分析，不接受空洞摘要。"""
    if target._state.current_stage != "gap_scan":
        return None
    if (
        target._design_doc is not None
        and not target._design_doc.plates
        and not result.get("gaps")
    ):
        return ErrorResponse(
            "GAP_SCAN_DESIGN_STRUCTURE_INVALID",
            "设计文档没有可执行的 H2/H3 或 ae 层次，不能以 synthetic document 章节直接进入 Architect",
            target._state.to_dict(),
            suggestion=(
                "请在同一 Gap Scan Action 中提交 architectural gap，或补齐设计文档的 H2/H3 层次后重新初始化。"
            ),
        )
    coverage = result.get("scan_coverage")
    if not isinstance(coverage, list) or not coverage:
        return ErrorResponse(
            "GAP_SCAN_EVIDENCE_INCOMPLETE",
            "Gap Scan 必须逐项提供 Core 解析章节的覆盖结论与非空证据",
            target._state.to_dict(),
        )
    if result.get("design_doc_digest") != target._state.design_doc_digest:
        return ErrorResponse(
            "GAP_SCAN_DESIGN_MISMATCH",
            "Gap Scan 结果未绑定当前 active design digest",
            target._state.to_dict(),
        )
    engineering_model = (
        EngineeringModel.from_design_doc(
            target._design_doc,
            design_digest=target._state.design_doc_digest,
        )
        if target._design_doc is not None
        else None
    )
    expected_by_id = {
        section.section_id: section.design_section
        for section in engineering_model.sections
    } if engineering_model is not None else {}
    expected_id_by_ref = {
        reference: section_id
        for section_id, reference in expected_by_id.items()
    }
    expected_id_by_alias = dict(expected_id_by_ref)
    if engineering_model is not None:
        for section in engineering_model.sections:
            if section.title and section.title != section.design_section:
                expected_id_by_alias.setdefault(
                    f"{section.design_section} {section.title}",
                    section.section_id,
                )
    actual_section_ids: list[str] = []
    for index, item in enumerate(coverage):
        section_id = item.get("section_id") if isinstance(item, dict) else None
        design_section_ref = (
            item.get("design_section_ref") if isinstance(item, dict) else None
        )
        valid = (
            isinstance(item, dict)
            and isinstance(design_section_ref, str)
            and item.get("verdict") in {"clear", "gap"}
            and isinstance(item.get("evidence"), list)
            and bool(item.get("evidence"))
            and all(
                isinstance(evidence, str) and evidence.strip()
                for evidence in item.get("evidence", [])
            )
        )
        if not valid:
            return ErrorResponse(
                "GAP_SCAN_EVIDENCE_INCOMPLETE",
                f"scan_coverage[{index}] 缺少章节、结论或非空证据",
                target._state.to_dict(),
            )
        resolved_id = (
            section_id
            if isinstance(section_id, str)
            else expected_id_by_alias.get(str(design_section_ref))
        )
        reference_id = expected_id_by_alias.get(str(design_section_ref))
        if (
            not isinstance(resolved_id, str)
            or resolved_id not in expected_by_id
            or (
                isinstance(section_id, str)
                and reference_id != resolved_id
            )
        ):
            return ErrorResponse(
                "GAP_SCAN_COVERAGE_MISMATCH",
                f"scan_coverage[{index}] 未绑定当前设计的稳定章节身份",
                target._state.to_dict(),
            )
        actual_section_ids.append(resolved_id)
    if (
        len(actual_section_ids) != len(set(actual_section_ids))
        or set(actual_section_ids) != set(expected_by_id)
        or result.get("scanned_sections") != len(actual_section_ids)
    ):
        return ErrorResponse(
            "GAP_SCAN_COVERAGE_MISMATCH",
            "Gap Scan 覆盖必须与 Core 解析章节一一对应且计数一致",
            target._state.to_dict(),
        )
    required = {
        "evidence", "problem_statement", "impact", "dependencies",
        "recommendation", "options", "blocking_rule",
    }
    gaps = result.get("gaps", [])
    advisory_refs = {
        re.sub(r"\s+", "", reference).casefold()
        for reference in target._design_doc.advisory_section_refs()
    } if target._design_doc is not None else set()
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            return ErrorResponse(
                "GAP_ANALYSIS_INCOMPLETE",
                f"gaps[{index}] 必须是 object",
                target._state.to_dict(),
            )
        missing = sorted(required - set(gap))
        recommendation = gap.get("recommendation")
        options = gap.get("options")
        invalid = (
            missing
            or not isinstance(gap.get("evidence"), list)
            or not gap.get("evidence")
            or not isinstance(gap.get("impact"), list)
            or not gap.get("impact")
            or not isinstance(recommendation, dict)
            or not {"resolution", "reason", "confidence"}.issubset(
                recommendation or {}
            )
            or not isinstance(options, list)
            or not options
        )
        if invalid:
            gap_id = gap.get("id", f"index-{index}")
            return ErrorResponse(
                "GAP_ANALYSIS_INCOMPLETE",
                f"gap {gap_id!r} 缺少可审计的证据、影响、推荐或选项",
                target._state.to_dict(),
            )
        assert isinstance(options, list)
        gap_source_text = " ".join([
            str(gap.get("design_section_ref", "")),
            *(str(item) for item in gap.get("evidence", [])),
        ])
        gap_refs = {
            f"§{reference.lstrip('§')}".casefold()
            for reference in re.findall(
                r"§?[A-Za-z]*\d+(?:\.\d+)*",
                gap_source_text,
            )
        }
        misclassified_advisory_refs = sorted(gap_refs & advisory_refs)
        if misclassified_advisory_refs:
            gap_id = gap.get("id", f"index-{index}")
            return ErrorResponse(
                "GAP_ANALYSIS_FUTURE_SCOPE_MISCLASSIFIED",
                f"gap {gap_id!r} 引用了未来/咨询章节 "
                f"{', '.join(misclassified_advisory_refs)}，不得升级为当前版本 Gap",
                target._state.to_dict(),
                suggestion=(
                    "将未来改进从 gaps 移除；若当前版本存在真实契约矛盾，"
                    "只引用当前章节作为 design_section_ref 和 evidence。"
                ),
            )
        if (
            gap.get("clarity") == "missing"
            and isinstance(gap.get("design_section_ref"), str)
            and target._design_doc is not None
            and section_has_explicit_design_contract(
                target._design_doc,
                gap["design_section_ref"],
            )
        ):
            return ErrorResponse(
                "GAP_ANALYSIS_IMPLEMENTATION_MISCLASSIFIED",
                f"gap {gap.get('id', f'index-{index}')!r} 将已有明确设计条目误判为 missing；"
                "实现文件、测试或配置缺失必须留给 Architect/Developer",
                target._state.to_dict(),
                suggestion=(
                    "保留 section_findings 的章节覆盖证据；将该项从 gaps 移除，"
                    "或仅在设计本身缺少必要契约时使用 vague/partial。"
                ),
            )
        if gap.get("grade") == "architectural" and any(
            isinstance(option, dict)
            and str(option.get("resolution", "")).lower() == "defer"
            and option.get("enabled", True)
            for option in options
        ):
            return ErrorResponse(
                "GAP_ANALYSIS_BLOCKING_RULE_INVALID",
                f"architectural gap {gap.get('id')!r} 不得启用纯 Defer",
                target._state.to_dict(),
            )
    expected_blocking = any(
        isinstance(gap, dict) and gap.get("grade") == "architectural"
        for gap in gaps
    )
    if bool(result.get("has_blocking")) != expected_blocking:
        return ErrorResponse(
            "GAP_ANALYSIS_BLOCKING_FLAG_MISMATCH",
            "has_blocking 必须由 architectural gap 集合确定",
            target._state.to_dict(),
        )
    return None

def validate_component_verifier_scope(target: ResultValidationTarget, result: dict) -> ErrorResponse | None:
    """Verifier 只能提交当前 Action 声明的批次设计条目。"""
    if target._state.current_stage != "component_verifier":
        return None
    action = target._active_action or {}
    scope = action.get("verification_scope")
    if not isinstance(scope, dict):
        return None
    if scope.get("mode") != "batch_design_items":
        return None
    component = scope.get("component")
    if result.get("component") != component:
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "component_verifier 结果的 component 未绑定当前批次",
            target._state.to_dict(),
        )
    expected = scope.get("design_item_ids")
    if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "当前 Action 的 design_item_ids 非法，无法安全接收覆盖结果",
            target._state.to_dict(),
        )
    coverage = result.get("coverage_map")
    if not isinstance(coverage, list):
        return None
    actual: list[str] = []
    for item in coverage:
        if not isinstance(item, dict) or not isinstance(item.get("design_item"), str):
            return ErrorResponse(
                "COMPONENT_VERIFICATION_SCOPE_INVALID",
                "coverage_map 每项必须绑定非空 design_item",
                target._state.to_dict(),
            )
        actual.append(item["design_item"])
    if len(actual) != len(set(actual)):
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "coverage_map 不得重复提交同一 design_item",
            target._state.to_dict(),
        )
    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("缺少=" + ",".join(missing))
        if unexpected:
            detail.append("越界=" + ",".join(unexpected))
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "coverage_map 未完整且仅覆盖当前批次白名单（" + "; ".join(detail) + "）",
            target._state.to_dict(),
        )
    return None

def validate_gap_review_decisions(target: ResultValidationTarget, result: dict) -> ErrorResponse | None:
    """新 Action 接受当前单项决定；旧 active Action 兼容完整 decisions。"""
    if target._state.current_stage != "gap_review":
        return None
    report = json.loads(target._state.gap_report_json or '{"gaps": []}')
    unresolved = [
        str(gap.get("id"))
        for gap in report.get("gaps", [])
        if gap.get("id") is not None
        and gap.get("resolution") not in {"fill", "defer"}
    ]
    decision = result.get("decision")
    if isinstance(decision, dict):
        current_id = unresolved[0] if unresolved else None
        if decision.get("gap_id") != current_id:
            return ErrorResponse(
                error_code="GAP_REVIEW_DECISION_OUT_OF_ORDER",
                message=(
                    f"当前只能处理 gap {current_id!r}，不得跳项或重复提交"
                ),
                current_state=target._state.to_dict(),
            )
        decision_source = decision.get("decision_source")
        if decision_source == "thread_policy":
            current_gap: dict[str, Any] = next(
                (
                    gap for gap in report.get("gaps", [])
                    if str(gap.get("id")) == current_id
                ),
                {},
            )
            recommended = (current_gap.get("recommendation") or {}).get(
                "resolution"
            )
            recommendation = current_gap.get("recommendation")
            if not isinstance(recommendation, dict) or recommendation.get(
                "requires_user_approval"
            ) is not False:
                return ErrorResponse(
                    error_code="GAP_REVIEW_POLICY_REQUIRES_APPROVAL",
                    message=(
                        "当前 Gap 推荐可能改变绑定设计，不能由线程策略自动采用；"
                        "必须单独提交用户 Gate 决策。"
                    ),
                    current_state=target._state.to_dict(),
                )
            if (
                target._state.gap_decision_policy
                != "remaining_recommendations"
                or decision.get("policy") != "remaining_recommendations"
                or str(decision.get("resolution", "")).lower()
                != str(recommended or "").lower()
            ):
                return ErrorResponse(
                    error_code="GAP_REVIEW_POLICY_DECISION_INVALID",
                    message="自动 Gap 决策必须匹配当前线程的结构化授权与 Core 推荐",
                    current_state=target._state.to_dict(),
                )
            return None
        if decision_source != "user":
            return ErrorResponse(
                error_code="GAP_REVIEW_USER_DECISION_REQUIRED",
                message="Gap Review 决策必须来自用户，禁止宿主代选",
                current_state=target._state.to_dict(),
            )
        return None
    expected = set(unresolved)
    decisions = result.get("decisions", [])
    actual = [str(item.get("gap_id")) for item in decisions if isinstance(item, dict)]
    actual_set = set(actual)
    if len(actual) != len(actual_set) or not actual_set.issubset(expected):
        return ErrorResponse(
            error_code="GAP_REVIEW_DECISIONS_INVALID_SET",
            message="decisions 含重复或未知 gap_id，必须严格对应当前 action.gaps",
            current_state=target._state.to_dict(),
        )
    if actual_set != expected:
        missing = sorted(expected - actual_set)
        return ErrorResponse(
            error_code="GAP_REVIEW_DECISIONS_INCOMPLETE",
            message=f"decisions 未完整覆盖当前 gap: {', '.join(missing)}",
            current_state=target._state.to_dict(),
        )
    return None
