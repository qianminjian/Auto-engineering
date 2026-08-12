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

from dataclasses import dataclass

__all__ = [
    "RESULT_SCHEMA",
    "ActionDone",
    "ActionError",
    "ErrorResponse",
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

    def to_dict(self) -> dict:
        d: dict = {
            "action": "done",
            "tick": self.tick,
            "verdict": self.verdict,
            "verdict_level": self.verdict_level,
            "verdict_reason": self.reason,
        }
        # 可选富字段: 仅在提供时出现
        for key in ("thread_id", "rounds", "gate_summary", "checkpoint_id"):
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        # tick 恒定输出 (done JSON 含 tick), 但 None 时移除避免误导
        if self.tick is None:
            del d["tick"]
        return d


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
    "project_setup": {
        "required": ["stage", "result_type", "artifacts"],
    },
    "architect": {
        "required": ["stage", "plan", "file_list"],
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

# Phase 0 stage: 结构自由, 由各 _after_* handler 自行取值 (无强制 schema)
_PHASE0_STAGES = frozenset({"gap_scan", "gap_review", "research"})

_RESULT_FIELD_TYPES: dict[str, dict[str, tuple[type, ...]]] = {
    "project_setup": {
        "stage": (str,), "result_type": (str,), "artifacts": (list,),
    },
    "architect": {
        "stage": (str,), "plan": (str,), "file_list": (list,),
    },
    "developer": {
        "stage": (str,), "batch_id": (str, type(None)),
        "files_changed": (list,), "test_results": (dict,),
    },
    "critic": {
        "stage": (str,), "verdict": (str,), "findings": (list,),
    },
    "component_verifier": {
        "stage": (str,), "component": (str, type(None)),
        "coverage_map": (list,), "missing_count": (int,),
        "diverged_count": (int,),
    },
    "plate_deep_audit": {
        "stage": (str,), "plate": (str,), "findings": (list,),
        "p0_count": (int,), "p1_count": (int,), "p2_count": (int,),
        "cross_component_issues": (list,),
    },
    "system_verifier": {
        "stage": (str,), "full_coverage_map": (list,),
        "total_design_items": (int,), "covered_count": (int,),
        "missing_count": (int,), "diverged_count": (int,),
    },
    "system_deep_audit": {
        "stage": (str,), "findings": (list,), "p0_count": (int,),
        "p1_count": (int,), "p2_count": (int,),
        "total_audited_files": (int,),
    },
    "session_claimed": {
        "stage": (str,), "claim_token": (str,), "session_id": (str,),
        "host": (str,),
    },
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
    if stage in _PHASE0_STAGES:
        return []

    schema = RESULT_SCHEMA.get(stage)
    if schema is None:
        return [f"未知 stage: '{stage}' (无 RESULT_SCHEMA)"]

    errors: list[str] = []

    # 必填字段存在性
    for req in schema["required"]:
        if req not in result or result[req] is None:
            errors.append(f"缺少必填字段 '{req}'")

    # JSON Schema 的字段类型约束必须在运行时同样生效。尤其排除 bool：
    # Python 中 bool 是 int 子类，但 JSON Schema 不把 boolean 视为 integer。
    for field, allowed_types in _RESULT_FIELD_TYPES[stage].items():
        if field not in result or result[field] is None:
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

    if stage == "project_setup":
        if result.get("result_type") != "project_setup_completed":
            errors.append("result_type 必须为 'project_setup_completed'")
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append("artifacts 必须为数组")

    # architect: plan 长度 + batch_plan 非空
    if stage == "architect":
        plan = result.get("plan")
        if isinstance(plan, str) and len(plan) < schema["plan_min_length"]:
            errors.append(
                f"plan 过短 ({len(plan)} < {schema['plan_min_length']})")
        batch_plan = result.get("batch_plan")
        plan_patch = result.get("plan_patch")
        if batch_plan is None and plan_patch is None:
            errors.append("batch_plan 或 plan_patch 至少提供一个")
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
