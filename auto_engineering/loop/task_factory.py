"""v5.0 M3 — Task Factory: batch_plan → Plan 转换 + outcome → state 分发.

设计参考: v5.6-Design-Loop.md §B7.3 (_tasks_from_batch_plan)
                   + §B7.2 (_apply_outcome_to_state)

模块职责:
    - _tasks_from_batch_plan: ArchitectAgent 产出的 batch_plan (list[dict])
      → Plan 实例, 所有 batch 硬编码 role="developer", 末尾追加 critic-review task.
    - _apply_outcome_to_state: TaskOutcome.output 按 task_role 分发写入
      EngineState 对应 channel (architect/developer/critic 各 3-4 字段).
      缺字段时静默跳过 (if "field" in values: 守卫), 不抛 KeyError.

依赖 (避免循环 import):
    - plan.Plan / Task (Stage 字段过滤)
    - round.TaskOutcome (orchestrator 产出的执行结果)
    - engine.state.EngineState (Channel 写入目标)
"""

from __future__ import annotations

import logging
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.loop.plan import Plan, Task
from auto_engineering.loop.round import TaskOutcome


def tasks_from_batch_plan(
    batch_plan: list[dict],
    requirement: str,
) -> Plan:
    """从 ArchitectAgent 产出的 batch_plan 构建 Plan (v5.6 B6.1a 嵌套 schema).

    batch_plan 层级: list[Batch] → Batch.tasks[] → Task{id, description, file_targets}.
    所有 task 展平为 developer Task; 末尾追加 1 个 critic-review Task.

    Args:
        batch_plan: list[dict], 每个 dict 含 keys:
            - batch_id: str (必填, 唯一)
            - component: str (必填)
            - design_section: str (必填)
            - tasks: list[dict] (必填, ≥1), 每元素含:
                - id: str (必填, 单次 run 内唯一)
                - description: str (必填)
                - file_targets: list[str] (必填, ≥1)
                - module_ref: str | list[str] (丢弃, 仅供 ProgressTree 使用)
            - depends_on: list[str] (可选, batch 级依赖, 不下放到 task)
        requirement: 原始需求描述.

    Returns:
        Plan 实例: 含所有展平的 developer Task + 1 个 critic-review Task.
    """
    tasks: list[Task] = []
    for batch in batch_plan:
        for task_dict in batch.get("tasks", []):
            task_id = task_dict.get("id")
            if not task_id:
                # 契约违规: task id 必填 (空/缺失破坏 depends_on + critic 引用)
                raise AEError(
                    ErrorCode.INVALID_AGENT_OUTPUT,
                    f"batch_plan task 缺少必填字段 'id' "
                    f"(batch_id={batch.get('batch_id', '?')})",
                    suggestion="architect 需为每个 task 提供唯一非空 id (见 §B6.1a schema)",
                )
            tasks.append(Task(
                id=task_id,
                title=task_dict.get("description", task_id)[:60],
                description=task_dict.get("description", ""),
                expected_output=f"实现并测试通过 {task_dict.get('description', '')}",
                role="developer",
                target_files=frozenset(task_dict.get("file_targets", [])),
                depends_on=[],  # task 级为空; batch 内顺序 = 隐式依赖
                kind=task_dict.get("kind", ""),  # v5.6 T30: regression_fix → RegressionGate(G9)
                regression_test_id=task_dict.get("regression_test_id", ""),
            ))
    # 追加 critic task (审查所有 developer 产出)
    tasks.append(Task(
        id="critic-review",
        title="审查所有 developer 产出",
        description=f"审查所有 developer 产出. 需求: {requirement}",
        expected_output='{"verdict": "APPROVE|MAJOR", "findings": [...], "feedback": "..."}',
        role="critic",
        depends_on=[t.id for t in tasks],
    ))
    return Plan(tasks=tasks, requirement=requirement)


# role→fields 映射表 (v5.4 审计 P0-2): 替代 12 个重复 if "field" in values 守卫.
# 新增 role/field 只需在此表追加, 无需修改 apply_outcome_to_state 主体.
ROLE_FIELD_MAP: dict[str, list[str]] = {
    # v5.5 Phase 2: architect 扩展 audit_findings (DeepAudit pass/PLAN-REFINE 后清除)
    # v5.6 B6.10: refine_request_json — architect PLAN-REFINE 消费后清除 (避免 stale 泄漏)
    "architect": ["plan", "file_list", "batch_plan", "contracts", "audit_findings",
                  "refine_request_json"],
    "developer": ["files_changed", "commit_hash", "test_results"],
    "critic": ["critic_verdict", "findings", "critic_feedback", "suggested_fix",
               "strengths", "assessment"],
}

# 每个 field 的清空默认值 (v5.4 审计 r2 P1-3: clear_stage_fields 引用此表 + ROLE_FIELD_DEFAULTS,
# 消除 stage_router.py 的重复硬编码).
ROLE_FIELD_DEFAULTS: dict[str, object] = {
    "plan": "",
    "file_list": [],
    "batch_plan": [],
    "contracts": {},
    "audit_findings": None,  # v5.5 Phase 2: DeepAudit pass/PLAN-REFINE 后清除
    "refine_request_json": None,  # v5.6 B6.10: architect PLAN-REFINE 消费后清除
    "files_changed": [],
    "commit_hash": "",
    "test_results": {},
    "critic_verdict": "",
    "findings": [],
    "critic_feedback": "",
    "suggested_fix": "",
    "strengths": None,
    "assessment": None,
}


# EngineState字段名 → LLM输出key 映射 (字段名与LLM输出key不一致时使用)
_STATE_TO_LLM_KEY: dict[str, str] = {
    "critic_verdict": "verdict",
}

# v5.5 Phase 2: LLM severity 标签 → P0/P1/P2 映射表
_SEVERITY_MAP: dict[str, str] = {
    "Critical": "P0",
    "Important": "P1",
    "Minor": "P2",
}


def apply_outcome_to_state(state: EngineState, outcome: TaskOutcome) -> None:
    """按 task_role 分发 outcome.output 写入 EngineState 字段 (v5.0 §B7.2).

    v5.5 Phase 2: critic findings 的 severity 字段映射 LLM 标签 →
    P0/P1/P2 (Critical→P0, Important→P1, Minor→P2).

    Args:
        state: EngineState 实例 (会被 mutate).
        outcome: TaskOutcome, 必读字段:
            - task_role: "architect" | "developer" | "critic" (否则 no-op 防御性)
            - output:    dict 形式承载 stage-specific 字段 (None 时 no-op)

    行为契约:
        - 缺字段 → 静默跳过, 不抛 KeyError
        - 未注册的 task_role → no-op (防御性).
        - output 为 None 或非 dict → 视为空 dict, 不写入任何字段.
    """
    role = outcome.task_role
    if role is None:
        return

    values: dict[str, Any] = outcome.output if isinstance(outcome.output, dict) else {}

    # v5.5 Phase 2: critic findings severity 映射
    if role == "critic" and "findings" in values:
        findings = values["findings"]
        if isinstance(findings, list):
            for finding in findings:
                if isinstance(finding, dict) and "severity" in finding:
                    raw = finding["severity"]
                    finding["severity"] = _SEVERITY_MAP.get(raw, raw)

    if values:
        validated = validate_role_output(role, values)
        for k in list(values.keys()):
            if k in validated:
                values[k] = validated[k]

    field_names = ROLE_FIELD_MAP.get(role, [])
    for field_name in field_names:
        # 通过映射表查找 LLM 输出中的对应 key (默认同名字段)
        llm_key = _STATE_TO_LLM_KEY.get(field_name, field_name)
        if llm_key in values:
            setattr(state, field_name, values[llm_key])


def validate_role_output(role: str, values: dict) -> dict:
    """Pydantic 校验 agent 输出, 返回 model_dump 或降级原始 dict.

    Pydantic ValidationError → 降级原始 values (非致命, agent 输出可能缺少可选字段).
    其他异常 → 传播 (非预期错误).
    """
    from pydantic import ValidationError

    try:
        if role == "architect":
            from auto_engineering.agents.output_models import ArchitectOutput
            validated = ArchitectOutput.model_validate(values)
            return validated.model_dump()
        elif role == "developer":
            from auto_engineering.agents.output_models import DeveloperOutput
            validated = DeveloperOutput.model_validate(values)
            return validated.model_dump()
        elif role == "critic":
            from auto_engineering.agents.output_models import CriticOutput
            validated = CriticOutput.model_validate(values)
            return validated.model_dump()
    except ValidationError:
        logging.getLogger("ae.loop.task_factory").warning(
            "Pydantic 校验失败 (role=%s), 降级使用原始 values", role, exc_info=True
        )
    return values


__all__ = [
    "ROLE_FIELD_DEFAULTS",
    "ROLE_FIELD_MAP",
    "apply_outcome_to_state",
    "tasks_from_batch_plan",
    "validate_role_output",
]
