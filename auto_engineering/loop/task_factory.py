"""v5.0 M3 — Task Factory: batch_plan → Plan 转换 + outcome → state 分发.

设计参考: v5.0-Design-Loop.md §B7.3 (_tasks_from_batch_plan)
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

from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.plan import Plan, Task
from auto_engineering.loop.round import TaskOutcome


def tasks_from_batch_plan(
    batch_plan: list[dict],
    requirement: str,
) -> Plan:
    """从 ArchitectAgent 产出的 batch_plan 构建 Plan (v5.0 §B7.3).

    设计假设 (v5.0 §B7.3):
        batch_plan 由 ArchitectAgent 生成, 仅含 developer 可执行的任务.
        architect 的分析工作和 critic 的审查工作不由 batch_plan 描述.
        因此所有 batch 的 role 硬编码为 "developer".
        若未来需要支持非 developer batch, 扩展 batch_plan 的 role 字段.

    Args:
        batch_plan: list[dict], 每个 dict 含 keys:
            - id: Task ID (必填)
            - description: 任务描述 (必填, 用于 Agent prompt)
            - files: list[str], 目标文件 (可选, 默认 [])
            - depends_on: list[str], 依赖 Task ID 列表 (可选, 默认 [])
        requirement: 原始需求描述 (写入 Plan.requirement, critic 任务 prompt 中引用).

    Returns:
        Plan 实例:
            - 包含所有 batch 转化的 developer Task
            - 末尾追加 1 个 critic-review Task (depends_on = 所有 developer task id)

    Note:
        - 即使 batch_plan 为空, 仍返回含 critic-review task 的 Plan (空开发 + 单审查)
        - 字段裁剪: Task 只承载 batch dict 的契约字段 (id/description/file_targets/depends_on),
          其他 batch 字段 (priority/estimated_minutes 等) 暂不映射 (YAGNI).
    """
    tasks: list[Task] = []
    for batch in batch_plan:
        tasks.append(Task(
            id=batch["id"],
            title=batch.get("description", batch["id"])[:60],  # title 截断 ≤60 char (避免过长)
            description=batch.get("description", ""),
            expected_output=batch.get("description", ""),  # batch 阶段 description 即期望产出
            role="developer",  # 硬编码: batch_plan 仅描述 developer 任务 (v5.0 §B7.3)
            target_files=frozenset(batch.get("files", [])),
            depends_on=list(batch.get("depends_on", [])),
        ))
    # 追加 critic task (审查所有 developer 产出)
    tasks.append(Task(
        id="critic-review",
        title="审查所有 developer 产出",
        description=f"审查所有 developer 产出. 需求: {requirement}",
        expected_output='{"verdict": "APPROVE|MAJOR", "findings": [...], "feedback": "..."}',
        role="critic",
        depends_on=[t.id for t in tasks],  # 依赖所有 developer task
    ))
    return Plan(tasks=tasks, requirement=requirement)


# role→fields 映射表 (v5.4 审计 P0-2): 替代 12 个重复 if "field" in values 守卫.
# 新增 role/field 只需在此表追加, 无需修改 apply_outcome_to_state 主体.
ROLE_FIELD_MAP: dict[str, list[str]] = {
    # v5.5 Phase 2: architect 扩展 audit_findings (DeepAudit pass/PLAN-REFINE 后清除)
    "architect": ["plan", "file_list", "batch_plan", "contracts", "audit_findings"],
    "developer": ["files_changed", "commit_hash", "test_results"],
    "critic": ["verdict", "findings", "critic_feedback", "suggested_fix"],
}

# 每个 field 的清空默认值 (v5.4 审计 r2 P1-3: clear_stage_fields 引用此表 + ROLE_FIELD_DEFAULTS,
# 消除 stage_router.py 的重复硬编码).
ROLE_FIELD_DEFAULTS: dict[str, object] = {
    "plan": "",
    "file_list": [],
    "batch_plan": [],
    "contracts": {},
    "audit_findings": None,  # v5.5 Phase 2: DeepAudit pass/PLAN-REFINE 后清除
    "files_changed": [],
    "commit_hash": "",
    "test_results": {},
    "verdict": "",
    "findings": [],
    "critic_feedback": "",
    "suggested_fix": "",
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
        if validated is not None:
            for k in list(values.keys()):
                if k in validated:
                    values[k] = validated[k]

    field_names = ROLE_FIELD_MAP.get(role, [])
    for field_name in field_names:
        if field_name in values:
            setattr(state, field_name, values[field_name])


def validate_role_output(role: str, values: dict) -> dict | None:
    """Pydantic 校验 agent 输出, 返回 model_dump 或降级原始 dict."""
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
    except Exception:
        import logging
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
