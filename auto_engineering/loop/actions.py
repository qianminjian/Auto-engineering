"""Action / ErrorResponse 响应层 + RESULT_SCHEMA 校验 (v5.6 §C.3).

TickOrchestrator 离散调用模型的 I/O 契约:
  - 每 tick Python 输出一个 action dict (stdout JSON) 告诉 Agent 下一步做什么
  - Agent 执行后写 stage-result.json, Python 读回校验

本模块提供 Python → Agent 侧的**终态/错误** action 与 result 校验:
  - ActionDone:    循环终止 ({"action":"done", verdict, verdict_reason, ...})
  - ActionError:   路由/内部错误 ({"action":"error", error_code, message})
  - ErrorResponse: result 校验失败 (带 current_state, tick() 用 isinstance 分流)
  - RESULT_SCHEMA + validate_result_format: 各 stage result 必填字段/值域校验

中间 action (architect/developer/critic/verifier/audit) 由 TickOrchestrator._build_action
直接构造 dict (含 context/expected_format), 不走本模块 —— 本模块只承载终态+错误+校验.

设计参考: §C.3.1 (done action) / §C.3.3 (error 响应) / §C.3.4 (RESULT_SCHEMA).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "RESULT_SCHEMA",
    "ActionDone",
    "ActionError",
    "ErrorResponse",
    "build_terminal_acceptance_summary",
    "business_result_contract",
    "result_contract_warnings",
    "validate_result_format",
]


@dataclass
class ActionDone:
    """循环终止 action (§C.3.1 done).

    verdict 为 level 名 (GOAL_ACHIEVED/STAGNANT/QUALITY/HARD_LIMIT/REFINE_LIMIT),
    reason 序列化为 "verdict_reason" 键 (与 done JSON 对齐). 其余字段可选,
    未提供 (None) 则不出现在 to_dict 输出中 (保持 JSON 精简).
    """

    verdict: str
    reason: str | None = None
    verdict_level: int | None = None
    tick: int | None = None
    thread_id: str | None = None
    rounds: int | None = None
    gate_summary: dict | None = None
    checkpoint_id: str | None = None
    acceptance_summary: dict | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": "done",
            "tick": self.tick,
            "verdict": self.verdict,
            "verdict_level": self.verdict_level,
            "verdict_reason": self.reason,
        }
        # 可选富字段: 仅在提供时出现
        if self.acceptance_summary is not None:
            d["acceptance_summary"] = self.acceptance_summary
        else:
            d["acceptance_summary"] = build_terminal_acceptance_summary(
                None, verdict=self.verdict,
            )
        for key in ("thread_id", "rounds", "gate_summary", "checkpoint_id"):
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        # tick 恒定输出 (done JSON 含 tick), 但 None 时移除避免误导
        if self.tick is None:
            del d["tick"]
        return d


def build_terminal_acceptance_summary(
    state: object | Mapping[str, object] | None,
    *,
    verdict: str,
    design_coverage_ok: bool = False,
    system_deep_audit_ok: bool = False,
) -> dict[str, object]:
    """区分 Core 收敛与真实产品验收，避免 ``done`` 被误读为发布完成。

    Core 只能声明自己实际掌握的确定性证据；真实 API、浏览器、设备权限等
    外部业务链路属于产品验收层，必须由独立的产品证据门禁确认。
    """

    def value(name: str, default: object = None) -> object:
        if isinstance(state, Mapping):
            return state.get(name, default)
        return getattr(state, name, default) if state is not None else default

    verified: list[str] = []
    if design_coverage_ok:
        verified.append("design_coverage")
    if system_deep_audit_ok:
        verified.append("system_deep_audit")
    gate_results = value("gate_results", {})
    if isinstance(gate_results, Mapping) and gate_results and all(
        isinstance(item, Mapping)
        and (item.get("not_applicable") is True or item.get("passed") is True)
        for item in gate_results.values()
    ):
        verified.append("project_gates")
    task_evidence = value("task_verification_evidence", {})
    if isinstance(task_evidence, Mapping) and task_evidence:
        verified.append("task_verification")

    unverified = ["product_business_acceptance"]
    if verdict != "GOAL_ACHIEVED":
        unverified.insert(0, "core_completion")
    total = len(verified) + len(unverified)
    return {
        "scope": "core",
        "status": (
            "core_verified_product_unverified"
            if verdict == "GOAL_ACHIEVED"
            else "core_incomplete"
        ),
        "verified_checks": verified,
        "unverified_items": unverified,
        "coverage": {"verified": len(verified), "total": total},
        "release_eligible": False,
    }


@dataclass
class ActionError:
    """路由/内部错误 action (§C.3.3, 无 current_state)."""

    error_code: str
    message: str
    suggestion: str | None = None  # P1-9: 告诉 Agent 如何恢复

    def to_dict(self) -> dict:
        d: dict = {
            "action": "error",
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


@dataclass
class ErrorResponse:
    """result 校验失败响应 (§C.3.3, 带 current_state).

    _read_and_validate 校验 stage 不匹配 / 格式非法时返回本类型;
    tick() 用 isinstance(result, ErrorResponse) 分流后 to_dict 输出.
    """

    error_code: str
    message: str
    current_state: dict | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": "error",
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.current_state is not None:
            d["current_state"] = self.current_state
        if self.suggestion is not None:
            d["suggestion"] = self.suggestion
        return d


# ── §C.3.4 各 Stage Result 验证规则 ──
RESULT_SCHEMA: dict[str, dict] = {
    "gap_scan": {"required": ["stage", "gaps", "section_findings"]},
    "gap_review": {"required": ["stage"]},
    "research": {"required": ["stage"]},
    "project_setup": {
        "required": ["stage", "result_type", "artifacts"],
    },
    "architect": {
        # Architect 有两种互斥结果：可执行计划，或设计变更请求。
        # 共同必填项只有 stage，分支必填项由 validate_result_format
        # 与 JSON Schema 的 oneOf 同步强制。
        "required": ["stage"],
        "batch_plan_min_batches": 1,
        "plan_min_length": 50,
    },
    "developer": {
        "required": ["stage", "batch_id", "files_changed", "test_results"],
        "test_results_min_passed": 1,
        "test_results_required_failed": 0,
        "files_changed_min": 1,
    },
    "critic": {
        "required": ["stage", "verdict", "findings"],
        "verdict_values": ["APPROVE", "MAJOR"],
    },
    "component_verifier": {
        "required": ["stage", "component", "coverage_map", "missing_count", "diverged_count"],
        "coverage_item_status": ["IMPLEMENTED", "MISSING", "DIVERGED"],
    },
    "plate_deep_audit": {
        "required": ["stage", "plate", "findings", "p0_count", "p1_count", "p2_count",
                     "cross_component_issues"],
        "severity_values": ["P0", "P1", "P2"],
    },
    "system_verifier": {
        "required": ["stage", "full_coverage_map", "total_design_items", "covered_count",
                     "missing_count", "diverged_count"],
        "coverage_item_status": ["IMPLEMENTED", "MISSING", "DIVERGED"],
    },
    "system_deep_audit": {
        "required": ["stage", "findings", "p0_count", "p1_count", "p2_count",
                     "total_audited_files"],
        "severity_values": ["P0", "P1", "P2"],
    },
    "session_claimed": {
        "required": ["stage", "claim_token", "session_id", "host"],
    },
}

# Phase 0 仍允许按版本兼容扩展字段，但不能再接受只有 stage 的空结果。
# 具体的章节覆盖/决策顺序由 TickOrchestrator 的领域校验继续负责。
_PHASE0_STAGES = frozenset({"gap_scan", "gap_review", "research"})

_RESULT_FIELD_TYPES: dict[str, dict[str, tuple[type, ...]]] = {
    "gap_scan": {
        "gaps": (list,), "section_findings": (list,),
        "scanned_sections": (int,), "has_blocking": (bool,),
        "design_doc_digest": (str,), "scan_coverage": (list,),
    },
    "gap_review": {"decision": (dict,)},
    "research": {
        "findings": (str,), "sources": (list,), "source_tier": (str,),
        "confidence": (str,), "recommended_design": (str,),
        "search_status": (str,), "search_error": (str,),
    },
    "project_setup": {
        "stage": (str,), "result_type": (str,), "artifacts": (list,),
    },
    "architect": {
        "stage": (str,), "plan": (str,), "file_list": (list,),
        "batch_plan": (list,), "plan_patch": (dict,),
        "result_type": (str,), "source_revision": (int,),
        "classifications": (list,), "new_batch_plan": (list,),
        "contracts": (dict,), "obligations": (list,),
        "design_change_requests": (list,), "decision_impacts": (list,),
    },
    "developer": {
        "stage": (str,), "batch_id": (str, type(None)),
        "files_changed": (list,), "test_results": (dict,),
        "commit_hash": (str,), "red_evidence": (list,),
    },
    "critic": {
        "stage": (str,), "verdict": (str,), "findings": (list,),
        "strengths": (list,), "critic_feedback": (str,),
        "assessment": (str,), "assurance_bundle": (dict,),
    },
    "component_verifier": {
        "stage": (str,), "component": (str, type(None)),
        "coverage_map": (list,), "missing_count": (int,),
        "diverged_count": (int,), "recheck_log": (list,),
    },
    "plate_deep_audit": {
        "stage": (str,), "plate": (str,), "findings": (list,),
        "p0_count": (int,), "p1_count": (int,), "p2_count": (int,),
        "cross_component_issues": (list,), "total_audited_files": (int,),
    },
    "system_verifier": {
        "stage": (str,), "full_coverage_map": (list,),
        "total_design_items": (int,), "covered_count": (int,),
        "missing_count": (int,), "diverged_count": (int,),
        "recheck_log": (list,),
    },
    "system_deep_audit": {
        "stage": (str,), "findings": (list,), "p0_count": (int,),
        "p1_count": (int,), "p2_count": (int,),
        "total_audited_files": (int,),
        "design_docs_stale": (bool,), "design_doc_suggestions": (str, list),
        "missing_count": (int,), "diverged_count": (int,),
    },
    "session_claimed": {
        "stage": (str,), "claim_token": (str,), "session_id": (str,),
        "host": (str,),
    },
}


def business_result_contract(
    stage: str,
    expected_fields: object,
) -> dict[str, object] | None:
    """把 Stage 类型事实投影为宿主可执行的业务 payload 合同。

    `expected_format` 继续只负责人类/模型说明；这里不解析其描述文本，只用
    RESULT_SCHEMA 与运行时字段类型表，因此宿主不会从示例字符串猜测类型。
    """

    field_types = _RESULT_FIELD_TYPES.get(stage)
    schema = RESULT_SCHEMA.get(stage)
    if (
        field_types is None
        or not isinstance(expected_fields, dict)
    ):
        return None
    undeclared = sorted(
        str(field) for field in expected_fields if field not in field_types
    )
    if undeclared:
        raise ValueError(
            f"RESULT_FIELD_TYPE_UNDECLARED:{stage}:{','.join(undeclared)}"
        )
    properties: dict[str, dict[str, object]] = {}
    for field in expected_fields:
        allowed = field_types.get(field)
        if allowed is None:
            continue
        names = [
            {
                str: "string",
                list: "array",
                dict: "object",
                int: "integer",
                bool: "boolean",
                type(None): "null",
            }[item]
            for item in allowed
        ]
        properties[field] = {
            "type": names[0] if len(names) == 1 else names,
        }
    required = (
        [
            field
            for field in schema.get("required", [])
            if field != "stage" and field in properties
        ]
        if schema is not None
        else list(properties)
    )
    return {
        "schema_version": "1.0",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }

_CONSUMED_OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "architect": ("contracts",),
    "developer": ("commit_hash", "red_evidence"),
    "critic": ("critic_feedback",),
    "component_verifier": ("recheck_log",),
    "system_verifier": ("recheck_log",),
    "system_deep_audit": (
        "design_docs_stale",
        "design_doc_suggestions",
        "missing_count",
        "diverged_count",
    ),
}


def result_contract_warnings(result: dict, stage: str) -> list[dict[str, str]]:
    """报告 Handler 会消费、但兼容期尚未提升为必填的缺失字段。"""

    return [
        {
            "code": "RESULT_OPTIONAL_FIELD_MISSING",
            "stage": stage,
            "field": field,
        }
        for field in _CONSUMED_OPTIONAL_FIELDS.get(stage, ())
        if field not in result
    ]


def validate_result_format(result: dict, stage: str) -> list[str]:
    """按 RESULT_SCHEMA 校验 result, 返回违规消息列表 (空列表 = 通过).

    Args:
        result: Agent 写回的 stage-result dict.
        stage: 期望 stage (由 orchestrator 传入, 权威).

    Returns:
        list[str]: 每条违规一行人类可读消息. 空 = 校验通过.
    """
    schema = RESULT_SCHEMA.get(stage)
    if schema is None:
        return [f"未知 stage: '{stage}' (无 RESULT_SCHEMA)"]

    errors: list[str] = []

    design_change_only = (
        stage == "architect"
        and isinstance(result.get("design_change_requests"), list)
        and bool(result["design_change_requests"])
    )
    plan_reconciliation = (
        stage == "architect"
        and result.get("result_type") == "plan_reconciliation"
    )
    required_fields = (
        ["stage", "design_change_requests"]
        if design_change_only
        else (
            [
                "stage", "plan", "file_list", "result_type",
                "source_revision", "classifications", "new_batch_plan",
            ]
            if plan_reconciliation
            else (
                ["stage"]
                if stage == "gap_scan"
                else (
                    ["stage", "plan", "file_list"]
                    if stage == "architect"
                    else (
                    ["stage", "decisions"]
                    if stage == "gap_review"
                    and "decision" not in result
                    and "decisions" in result
                    else schema["required"]
                    )
                )
            )
        )
    )

    # 必填字段存在性
    for req in required_fields:
        if req not in result or result[req] is None:
            errors.append(f"缺少必填字段 '{req}'")

    # JSON Schema 的字段类型约束必须在运行时同样生效。尤其排除 bool：
    # Python 中 bool 是 int 子类，但 JSON Schema 不把 boolean 视为 integer。
    for field, allowed_types in _RESULT_FIELD_TYPES[stage].items():
        if field not in result:
            continue
        value = result[field]
        valid_type = (
            False
            if int in allowed_types and isinstance(value, bool)
            else isinstance(value, allowed_types)
        )
        if not valid_type:
            expected = " 或 ".join(t.__name__ for t in allowed_types)
            errors.append(
                f"字段 '{field}' 类型错误，应为 {expected}，"
                f"当前为 {type(value).__name__}"
            )

    if result.get("stage") != stage:
        errors.append(f"stage 必须为 '{stage}'")

    # Phase 0 的领域校验需要保留更详细的错误码，因此这里只拦截“空壳”结果，
    # 不把 gaps/coverage 的完整性重复搬到本层。
    if stage == "gap_scan" and not any(
        field in result for field in ("gaps", "section_findings", "scan_coverage")
    ):
        errors.append("gap_scan 至少需要 gaps、section_findings 或 scan_coverage 之一")
    elif stage == "gap_review" and not any(
        field in result for field in ("decision", "decisions")
    ):
        errors.append("gap_review 至少需要 decision 或 decisions")
    elif stage == "research" and not any(
        field in result for field in (
            "findings", "recommended_design", "search_status", "search_error",
        )
    ):
        errors.append("research 至少需要 findings、recommended_design 或搜索状态")

    if stage == "project_setup":
        if result.get("result_type") != "project_setup_completed":
            errors.append("result_type 必须为 'project_setup_completed'")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append("artifacts 必须为数组")

    if stage == "architect" and design_change_only:
        requests = result.get("design_change_requests")
        if isinstance(requests, list):
            for index, request in enumerate(requests):
                if not isinstance(request, dict):
                    errors.append(
                        f"design_change_requests[{index}] 必须为 object"
                    )
                    continue
                required_request_fields = {
                    "source", "source_ref", "requested_authority",
                    "change_summary", "affected_design_refs",
                }
                missing = sorted(required_request_fields - set(request))
                if missing:
                    errors.append(
                        f"design_change_requests[{index}] 缺少: {', '.join(missing)}"
                    )
                if request.get("source") not in {"research", "agent_assumption"}:
                    errors.append(
                        f"design_change_requests[{index}].source 非法"
                    )
                if request.get("requested_authority") != "binding":
                    errors.append(
                        f"design_change_requests[{index}].requested_authority 必须为 binding"
                    )
                if not isinstance(request.get("source_ref"), str) or not request.get("source_ref", "").strip():
                    errors.append(
                        f"design_change_requests[{index}].source_ref 必须为非空字符串"
                    )
                if not isinstance(request.get("change_summary"), str) or not request.get("change_summary", "").strip():
                    errors.append(
                        f"design_change_requests[{index}].change_summary 必须为非空字符串"
                    )
                refs = request.get("affected_design_refs")
                if not isinstance(refs, list) or not refs or not all(
                    isinstance(ref, str) and ref.strip() for ref in refs
                ):
                    errors.append(
                        f"design_change_requests[{index}].affected_design_refs 必须为非空字符串数组"
                    )

    # architect: plan 长度 + batch_plan 非空
    if stage == "architect" and not design_change_only:
        plan = result.get("plan")
        if isinstance(plan, str) and len(plan) < schema["plan_min_length"]:
            errors.append(
                f"plan 过短 ({len(plan)} < {schema['plan_min_length']})")
        batch_plan = result.get("batch_plan")
        plan_patch = result.get("plan_patch")
        if (
            batch_plan is None
            and plan_patch is None
            and not plan_reconciliation
        ):
            errors.append("batch_plan 或 plan_patch 至少提供一个")
        if plan_reconciliation:
            source_revision = result.get("source_revision")
            if (
                isinstance(source_revision, int)
                and not isinstance(source_revision, bool)
                and source_revision < 1
            ):
                errors.append("source_revision 必须大于等于 1")
        if isinstance(batch_plan, list) and len(batch_plan) < schema["batch_plan_min_batches"]:
            errors.append("batch_plan 至少需 1 个 batch")
        if plan_patch is not None:
            if not isinstance(plan_patch, dict):
                errors.append("plan_patch 必须为 object")
            else:
                base_revision = plan_patch.get("base_revision")
                if base_revision is not None and not isinstance(base_revision, int):
                    errors.append("plan_patch.base_revision 必须为 integer")
                additions = plan_patch.get("add_batches")
                if not isinstance(additions, list) or not additions:
                    errors.append("plan_patch.add_batches 至少需 1 个 batch")
                if plan_patch.get("reopen_completed"):
                    errors.append("普通 plan_patch 不得重新打开已完成工作")

    # developer: test_results.failed==0 + files_changed 非空
    elif stage == "developer":
        tr = result.get("test_results") or {}
        if isinstance(tr, dict):
            failed = tr.get("failed", 0)
            passed = tr.get("passed", 0)
            if not isinstance(failed, int) or isinstance(failed, bool):
                errors.append("test_results.failed 类型错误，应为 integer")
            elif failed != schema["test_results_required_failed"]:
                errors.append(f"test_results.failed 必须为 0, 当前 {tr.get('failed')}")
            if not isinstance(passed, int) or isinstance(passed, bool):
                errors.append("test_results.passed 类型错误，应为 integer")
            elif passed < schema["test_results_min_passed"]:
                errors.append(
                    "test_results.passed 至少为 1 —— "
                    "纯配置/脚手架 batch 也需验证产出"
                    "（如文件是否存在、JSON 是否合法、配置项是否有效）"
                )
        fc = result.get("files_changed")
        if isinstance(fc, list) and len(fc) < schema["files_changed_min"]:
            errors.append("files_changed 至少 1 个文件")

    # critic: verdict 值域
    elif stage == "critic":
        verdict = result.get("verdict")
        if verdict not in schema["verdict_values"]:
            errors.append(
                f"verdict 非法 '{verdict}', 合法: {schema['verdict_values']}")

    # verifier: coverage_map item.status 值域
    elif stage in ("component_verifier", "system_verifier"):
        map_key = "coverage_map" if stage == "component_verifier" else "full_coverage_map"
        allowed = schema["coverage_item_status"]
        for item in result.get(map_key) or []:
            if isinstance(item, dict) and item.get("status") not in allowed:
                errors.append(
                    f"coverage item status 非法 '{item.get('status')}', 合法: {allowed}")
                break

    # deep_audit: findings severity 值域
    elif stage in ("plate_deep_audit", "system_deep_audit"):
        allowed = schema["severity_values"]
        for f in result.get("findings") or []:
            if isinstance(f, dict) and f.get("severity") not in allowed:
                errors.append(
                    f"finding severity 非法 '{f.get('severity')}', 合法: {allowed}")
                break

    return errors
