"""M1 Stage 状态机 — StageRouter + StageDecision + 5 helper functions.

设计参考: v5.6-Design-Loop.md §B2.2 (StageRouter 接口契约)
                   + §B3.1 (Stage 转换表 T1-T8)
                   + §B3.2 (MAJOR 计数更新)
                   + §B3.3 (clear_stage_fields)

T1-T6 转换表 (§B2.2):
    T1: stage="" → next="architect"
    T2: architect → next="developer"
    T3: developer → next="critic"
    T4: critic + APPROVE → next=None, should_stop=False (Judge 触发 GOAL_ACHIEVED)
    T5: critic + MAJOR + 未超限 → next="developer"
    T6: critic + MAJOR + 超限 → next=None, should_stop=True
        reason="MAJOR 超限: 连续{majors}/累计{total}"

T7/T8 由 Orchestrator / ConvergenceJudge 处理, 不在本模块范围.

2026-07-04 修复 (Bug 3 prismscan 集成): critic verdict 异常分支不再默认
should_stop=True + level=3 (静默归一化为 PASS, 反向语义), 改为
raise CriticVerdictInvalid 让 orchestrator 显式处理 (重试或抛异常).

业界对标:
    - LangGraph conditional edge router (pregel/main.py:1790)
    - LangGraph recursion_limit 单层保护 (pregel/_algo.py:87-110)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

from auto_engineering.loop.task_factory import ROLE_FIELD_DEFAULTS, ROLE_FIELD_MAP

__all__ = [
    "CriticVerdictInvalid",
    "StageDecision",
    "StageRouter",
    "update_majors_count",
    "clear_stage_fields",
]


class CriticVerdictInvalid(Exception):
    """Critic 返回非法 verdict 时抛出 (空字符串、非 APPROVE/MAJOR、其他值).

    2026-07-04 修复 (Bug 3): 替代 stage_router 原先的 should_stop=True 静默
    fallback, 让 orchestrator 显式重试或升级处理, 避免反向语义
    (异常→PASS→停止).
    """

    def __init__(self, verdict: str, history_stages: list[str] | None = None) -> None:
        self.verdict = verdict
        self.history_stages = history_stages or []
        super().__init__(
            f"critic 返回非法 verdict: {verdict!r}; "
            f"调用链: {self.history_stages}"
        )


@dataclass
class StageDecision:
    """Stage 推进决策结果 (§B2.2).

    Fields:
        next_stage: 下一 Stage 名 ("architect" | "developer" | "critic").
                   None 表示 Stage 流终止 (APPROVE 或超限).
        should_stop: 是否应停止主循环. True 时 Orchestrator 退出 run().
        stop_reason: 停止原因 (应用户可读). None 表示继续.

    语义:
        - should_stop=False, next_stage=None: critic+APPROVE (由 Judge 触发 GOAL_ACHIEVED)
        - should_stop=True, next_stage=None: critic+MAJOR 超限 (T6) 或 critic+verdict='' (异常)
        - should_stop=False, next_stage="X": 推进到 X Stage
    """

    next_stage: str | None = None
    should_stop: bool = False
    stop_reason: str | None = None


class StageRouter:
    """Stage 状态机路由器 (§B2.2).

    纯函数式判定: 仅根据 (current_stage, verdict, majors_in_a_row, total_majors)
    决定下一步 Stage, 不读写 EngineState 副作用.
    **副作用**: self.history_stages 会记录每次调用时的 current_stage (供
    CriticVerdictInvalid 异常显示调用链).

    用法:
        # 2026-07-04 修复 (Self-Refine / Reflexion 原则 3): max_majors 2→3 + 3→4.
        # Self-Refine (Madaan et al. 2023) 实验: 2-3 轮反馈后质量显著提升,
        # 4+ 轮开始 Degeneration-of-Thought. 旧值 2/3 过严, MAJOR 后立即停 → 没机会
        # 看到 Self-Refine 反馈注入 + 改进. 新值 3/4 让 developer 至少 3 次修复机会.
        router = StageRouter(max_majors_in_a_row=3, max_total_majors=4)
        decision = router.next("critic", "MAJOR", 1, 1)  # → next="developer"
        decision = router.next("critic", "MAJOR", 2, 2)  # → next="developer"
        decision = router.next("critic", "MAJOR", 3, 3)  # → should_stop=True
    """

    def __init__(
        self,
        max_majors_in_a_row: int = 3,
        max_total_majors: int = 4,
    ) -> None:
        """初始化 StageRouter.

        Args:
            max_majors_in_a_row: 连续 MAJOR 计数上限, 超过触发 T6 stop. 默认 3.
            max_total_majors: 累计 MAJOR 计数上限, 超过触发 T6 stop. 默认 4.

        Raises:
            ValueError: 任一参数 < 1 (无意义配置).
        """
        if max_majors_in_a_row < 1:
            raise ValueError(
                f"max_majors_in_a_row 必须 ≥ 1, 当前 {max_majors_in_a_row}"
            )
        if max_total_majors < 1:
            raise ValueError(
                f"max_total_majors 必须 ≥ 1, 当前 {max_total_majors}"
            )
        self.max_majors_in_a_row = max_majors_in_a_row
        self.max_total_majors = max_total_majors
        # 2026-07-04 修复 (Issue #4, 95 分): 初始化 history_stages 列表,
        # next() 追加 current_stage. CriticVerdictInvalid.history_stages 不再空.
        self.history_stages: list[str] = []

    def next(
        self,
        current_stage: str,
        verdict: str,
        majors_in_a_row: int,
        total_majors: int,
        audit_found_issues: bool = False,      # v5.5: DeepAudit 是否发现问题
        plan_refine_count: int = 0,            # v5.5: 当前 T9 回路计数
        max_plan_refines: int = 3,             # v5.5 P1-14: fallback, Orchestrator 从 ConvergenceConfig 显式传入
    ) -> StageDecision:
        """根据当前 Stage + Critic verdict 决定下一步 Stage (§B2.2 T1-T6, T9/T9-LIMIT).

        Args:
            current_stage: 当前 Stage ("" | "architect" | "developer" | "critic").
            verdict: Critic 产出 ("" | "APPROVE" | "MAJOR"). 非 critic 阶段传 "".
            majors_in_a_row: 连续 MAJOR 计数 (≥0).
            total_majors: 累计 MAJOR 计数 (≥0).
            audit_found_issues: v5.5 T9 — DeepAudit 是否发现问题 (default False).
            plan_refine_count: v5.5 T9 — 当前 T9 回路计数 (default 0).
            max_plan_refines: v5.5 T9 — T9 回路最大次数 (default 3).

        Returns:
            StageDecision 含 next_stage / should_stop / stop_reason.
        """
        # 2026-07-04 修复 (Issue #4, 95 分): 记录 current_stage 到 history_stages
        # 供 CriticVerdictInvalid 异常时显示调用链 (不再永远是空).
        if current_stage:
            self.history_stages.append(current_stage)

        # T1: 初始 stage → architect
        if current_stage == "":
            return StageDecision(next_stage="architect", should_stop=False)

        # T2: architect → developer
        if current_stage == "architect":
            return StageDecision(next_stage="developer", should_stop=False)

        # T3: developer → critic
        if current_stage == "developer":
            return StageDecision(next_stage="critic", should_stop=False)

        # T4/T5/T6/T9: critic 阶段
        if current_stage == "critic":
            if verdict == "APPROVE":
                # v5.5 T9: DeepAudit 发现问题 → PLAN-REFINE 回路
                if audit_found_issues:
                    if plan_refine_count >= max_plan_refines:
                        # T9-LIMIT: 超过 plan refine 上限 → 停止
                        return StageDecision(
                            next_stage=None,
                            should_stop=True,
                            stop_reason=(
                                f"T9-LIMIT: plan refine 上限 "
                                f"({plan_refine_count}/{max_plan_refines})"
                            ),
                        )
                    # T9: 回到 architect 进行 PLAN-REFINE
                    return StageDecision(next_stage="architect", should_stop=False)
                # T4: APPROVE → Judge 触发 GOAL_ACHIEVED (本路由不停止)
                return StageDecision(next_stage=None, should_stop=False)

            if verdict == "MAJOR":
                # T6: 超限检查 (先连续后累计)
                if majors_in_a_row >= self.max_majors_in_a_row:
                    return StageDecision(
                        next_stage=None,
                        should_stop=True,
                        stop_reason=(
                            f"MAJOR 超限: 连续{majors_in_a_row}/"
                            f"累计{total_majors}"
                        ),
                    )
                if total_majors >= self.max_total_majors:
                    return StageDecision(
                        next_stage=None,
                        should_stop=True,
                        stop_reason=(
                            f"MAJOR 超限: 连续{majors_in_a_row}/"
                            f"累计{total_majors}"
                        ),
                    )
                # T5: 未超限 → 回到 developer 重做
                return StageDecision(next_stage="developer", should_stop=False)

            # verdict="" 或其他非法值 → 抛 CriticVerdictInvalid (2026-07-04 Bug 3 修复)
            #
            # 旧实现: should_stop=True + reason="verdict 异常" → 反向语义
            # (异常 → PASS → 停止, 整个 loop 2 秒退出 0 代码改动).
            # 新实现: 抛异常让 orchestrator 显式处理 (重试或升级), 不静默归一化.
            # 设计意图"critic 阶段必须给出 verdict"是设计约束, 不是 fallback.
            raise CriticVerdictInvalid(
                verdict=verdict,
                history_stages=self.history_stages,
            )

        # 未知 stage → 安全停止 (防御性, 不抛异常避免 Orchestrator 僵死)
        return StageDecision(
            next_stage=None,
            should_stop=True,
            stop_reason=f"未知 Stage: '{current_stage}'",
        )


def update_majors_count(state: "EngineState", verdict: str) -> None:
    """更新 EngineState 的 MAJOR 计数 (§B3.2).

    行为:
        - "APPROVE": 重置 majors_in_a_row = 0, total_majors 保留.
        - "MAJOR":   majors_in_a_row += 1, total_majors += 1.
        - 其他 ("", 异常值): 不变.
    """
    if verdict == "APPROVE":
        state.write_field("majors_in_a_row", 0, "stage_router")
    elif verdict == "MAJOR":
        state.write_field("majors_in_a_row", state.majors_in_a_row + 1, "stage_router")
        state.write_field("total_majors", state.total_majors + 1, "stage_router")
    # else: verdict="" 或其他 → 不变


def clear_stage_fields(state: Any, stage: str) -> None:
    """清空 EngineState 中指定 Stage 产出的 channel (§B3.3).

    两个使用场景:
    1. 正常 stage 过渡: Orchestrator._step_2i 推进到下一 stage 前清空旧产出
    2. Guardrail retry: 重试当前 stage 前清空旧产出, 避免读到脏数据
    调用方: Orchestrator._step_2i (正常过渡) + guardrail.handle_guardrail_result (retry).

    Args:
        state: EngineState 实例 (duck-typed).
        stage: 要清空的 Stage 名 ("architect" | "developer" | "critic").
               其他值: no-op (防御性).

    v5.4 审计 r2 P1-3: 引用 task_factory.ROLE_FIELD_MAP + ROLE_FIELD_DEFAULTS
    作为单一真相源, 消除重复硬编码.
    """

    field_names = ROLE_FIELD_MAP.get(stage, [])
    for field_name in field_names:
        if field_name in ROLE_FIELD_DEFAULTS:
            setattr(state, field_name, ROLE_FIELD_DEFAULTS[field_name])


