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


def _tasks_from_batch_plan(
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


def _apply_outcome_to_state(state: EngineState, outcome: TaskOutcome) -> None:
    """按 task_role 分发 outcome.output 写入 EngineState 字段 (v5.0 §B7.2).

    字段映射 (v5.0 §B7.2):
        architect:
            - plan            → state.plan
            - file_list       → state.file_list
            - batch_plan      → state.batch_plan
            - contracts       → state.contracts
        developer:
            - files_changed   → state.files_changed
            - commit_hash     → state.commit_hash
            - test_results    → state.test_results
        critic:
            - verdict         → state.verdict
            - findings        → state.findings
            - critic_feedback → state.critic_feedback

    Args:
        state: EngineState 实例 (会被 mutate).
        outcome: TaskOutcome, 必读字段:
            - task_role: "architect" | "developer" | "critic" (否则 no-op 防御性)
            - output:    dict 形式承载 stage-specific 字段 (None 时 no-op)

    行为契约:
        - 缺字段 (`"field" not in values`) → 静默跳过, 不抛 KeyError
          (避免 Agent 输出 schema 漂移导致 Orchestrator 僵死).
        - 未注册的 task_role → no-op (防御性, 未来扩展不破坏现有逻辑).
        - output 为 None 或非 dict → 视为空 dict, 不写入任何字段.

    Note:
        state 写入走 getattr + setattr, 不直接 dict.update, 保持 type-checker 友好
        (EngineState 字段静态可见). 未来加新字段 → 此处单点扩展.

    v5.1 候选: packet apply_writes (LangGraph 借鉴)
        - 当前: 串行 apply,每个 outcome 立即写入 state
        - v5.1 候选: 收集所有 outcomes 后批量 apply,减少 state lock 冲突
        - 借鉴: LangGraph pregel/_algo.py apply_writes (pregel/_algo.py:87-110)
        - 触发条件: 多 Agent 并发场景 N task 并行时
        - 收益: state lock 冲突降低,apply 耗时从 O(N) 降至 O(1)
        - 不实施原因: 当前并发度低 (1-3 task), 性能不是瓶颈
    """
    role = outcome.task_role
    if role is None:
        # 旧调用方未传 task_role → 不分发, 避免误写
        return

    # 容错: output 非 dict (None / str / 其他) → 视为空, 不写任何字段
    values: dict[str, Any] = outcome.output if isinstance(outcome.output, dict) else {}

    if role == "architect":
        if "plan" in values:
            state.plan = values["plan"]
        if "file_list" in values:
            state.file_list = values["file_list"]
        if "batch_plan" in values:
            state.batch_plan = values["batch_plan"]
        if "contracts" in values:
            state.contracts = values["contracts"]
    elif role == "developer":
        if "files_changed" in values:
            state.files_changed = values["files_changed"]
        if "commit_hash" in values:
            state.commit_hash = values["commit_hash"]
        if "test_results" in values:
            state.test_results = values["test_results"]
    elif role == "critic":
        if "verdict" in values:
            state.verdict = values["verdict"]
        if "findings" in values:
            state.findings = values["findings"]
        if "critic_feedback" in values:
            state.critic_feedback = values["critic_feedback"]
    # 未知 role → no-op (防御性, 不抛避免僵死)


__all__ = [
    "_tasks_from_batch_plan",
    "_apply_outcome_to_state",
]
