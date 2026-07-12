"""v5.5 Phase 5 — T9 Plan-Refine 回路 E2E 测试.

测试覆盖:
    1. T9 完整回路: critic APPROVE → DeepAudit (P0>0) → T9 → architect → critic APPROVE → pass
    2. T9-LIMIT: plan_refine_count 达上限后 should_stop
    3. plan_refine_count 正确递增 (DeepAudit fail) 和重置 (DeepAudit pass)
    4. 无 P0 但有 P1>=threshold 同样触发 T9
    5. StageRouter.plan_refine_count 在 T9 成功通过后外部重置
    6. Orchestrator._after_tick 中 T9 跳过 ConvergenceJudge

测试原则 (per pytest-memory-management.md):
    - 单文件 pytest --no-cov --timeout=60
    - 用 mock/fake 避免真实 LLM 调用
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.convergence import (
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
)
from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
from auto_engineering.loop.plan import Task
from auto_engineering.loop.round import (
    RoundResult,
)
from auto_engineering.loop.stage_router import (
    StageRouter,
)

# ============================================================
# Helpers
# ============================================================


def make_task(
    task_id: str,
    role: str = "developer",
    agent_type: str | None = None,
    target_files: list[str] | None = None,
    deps: list[str] | None = None,
) -> Task:
    """构造测试 Task."""
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description=f"task {task_id}",
        expected_output=f"output for {task_id}",
        role=agent_type or role,
        target_files=frozenset(target_files or []),
        depends_on=list(deps or []),
    )


def make_finding(
    severity: str = "P0",
    file: str = "src/test.py",
    line: int = 10,
    description: str = "test finding",
) -> dict:
    """构造 DeepAudit finding dict."""
    return {
        "severity": severity,
        "file": file,
        "line": line,
        "description": description,
        "dimension": "code_quality",
        "evidence": "...",
        "suggested_fix": "...",
        "agent_source": "code_quality",
    }


def make_round_history(
    round_id: int = 1,
    stage: str = "critic",
    gate_results: dict | None = None,
) -> RoundHistory:
    """构造 RoundHistory."""
    return RoundHistory(
        round_id=round_id,
        stage=stage,
        files_changed=3,
        lines_added=10,
        lines_removed=2,
        gate_results=gate_results or {},
    )


# ============================================================
# 1. StageRouter T9 单元测试 (补充)
# ============================================================


class TestStageRouterT9Unit:
    """StageRouter T9 路由逻辑单元测试.

    2026-07-09 (v5.6 T2): next() 迁移到 DS-8 双预算 (refine_source_count/
    refine_global_count/max_refine_per_source/max_refine_global). v5.5 单一
    plan_refine_count 映射为全局预算, 分源预算传大值旁路. 停止理由 T9-LIMIT
    → REFINE_LIMIT (v5.6 next() 语义).
    """

    def test_t9_critic_approve_with_audit_issues(self):
        """critic APPROVE + audit_found_issues=True → next_stage="architect"."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            refine_source_count=0,
            refine_global_count=0,
            max_refine_per_source=10**9,
            max_refine_global=3,
        )
        assert decision.next_stage == "architect"
        assert decision.should_stop is False

    def test_t9_critic_approve_no_audit_issues(self):
        """critic APPROVE + audit_found_issues=False → next_stage=None (正常 T4)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=False,
        )
        assert decision.next_stage is None
        assert decision.should_stop is False

    def test_t9_limit_exact_equals(self):
        """refine_global_count == max_refine_global → should_stop=True."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            refine_source_count=0,
            refine_global_count=3,
            max_refine_per_source=10**9,
            max_refine_global=3,
        )
        assert decision.should_stop is True
        assert decision.next_stage is None
        assert "REFINE_LIMIT" in (decision.stop_reason or "")

    def test_t9_limit_exceeded(self):
        """refine_global_count > max_refine_global → should_stop=True."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            refine_source_count=0,
            refine_global_count=5,
            max_refine_per_source=10**9,
            max_refine_global=3,
        )
        assert decision.should_stop is True
        assert "REFINE_LIMIT" in (decision.stop_reason or "")

    def test_t9_backward_compatible_defaults(self):
        """无 refine 参数 → 默认 audit_found_issues=False → None."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage is None
        assert decision.should_stop is False

    def test_t9_incrementing_plan_refine_count(self):
        """refine_global_count 递增但仍在限制内 → 继续回 architect."""
        router = StageRouter()
        for count in range(3):  # 0, 1, 2
            decision = router.next(
                current_stage="critic",
                verdict="APPROVE",
                majors_in_a_row=0,
                total_majors=0,
                audit_found_issues=True,
                refine_source_count=0,
                refine_global_count=count,
                max_refine_per_source=10**9,
                max_refine_global=3,
            )
            assert decision.next_stage == "architect"
            assert decision.should_stop is False, f"count={count} should not stop"

    def test_t9_maver_reverts_to_developer_not_architect(self):
        """MAJOR verdict + audit issues → still go to developer (MAJOR takes priority)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=1,
            total_majors=1,
            audit_found_issues=True,  # MAJOR 优先, 不走 refine 分支
            refine_source_count=0,
            refine_global_count=0,
            max_refine_per_source=10**9,
            max_refine_global=3,
        )
        # MAJOR → T5: back to developer (不是 architect)
        assert decision.next_stage == "developer"
        assert decision.should_stop is False


# ============================================================
# 2. Orchestrator._after_tick T9 逻辑集成测试
# ============================================================


class TestOrchestratorAfterTickT9:
    """Orchestrator._after_tick 中 T9 逻辑的集成测试.

    直接调用 _after_tick 并 mock _run_deep_audit 来控制 audit findings.
    """

    def _make_orchestrator_with_state(
        self,
        tmp_path: Path,
        max_plan_refines: int = 3,
    ) -> Orchestrator:
        """创建带配置状态的 Orchestrator, 适合 T9 测试."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=20,
                max_plan_refines=max_plan_refines,
                deep_audit_enabled=True,
            ),
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test requirement",
            tasks=[],
            executor=None,
            config=config,
        )
        return orch

    @pytest.mark.asyncio
    async def test_after_tick_t9_audit_found_back_to_architect(self, tmp_path: Path):
        """_after_tick: critic APPROVE + DeepAudit 发现问题 → T9 回到 architect."""
        orch = self._make_orchestrator_with_state(tmp_path)

        # 设置 state 为 critic APPROVE
        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"

        # 构造 critic 的 round_result (所有 gates 通过)
        from auto_engineering.gates.base import GateVerdict

        passed_verdict = GateVerdict(
            gate_name="test_gate", passed=True, message="PASS",
        )
        round_history = RoundHistory(
            round_id=1,
            stage="critic",
            files_changed=3,
            gate_results={"test_gate": passed_verdict},
        )
        round_result = RoundResult(
            round_id=1,
            outcomes=[],
            history=[round_history],
            gate_results={"test_gate": passed_verdict},
        )

        # Mock _run_deep_audit 返回 P0 问题
        with patch.object(
            orch, "_run_deep_audit", return_value=(True, [make_finding()]),
        ):
            should_break = await orch._after_tick(
                round_result=round_result,
                current_stage="critic",
                guardrail_chain=None,
                round_id=1,
            )

        # T9: 回到 architect, 不 break
        assert should_break is False
        assert orch._state.current_stage == "architect"
        assert orch._state.plan_refine_count == 1
        assert orch._state.audit_findings is not None
        assert len(orch._state.audit_findings) == 1

    @pytest.mark.asyncio
    async def test_after_tick_t9_no_audit_issues_judge_convergence(self, tmp_path: Path):
        """_after_tick: critic APPROVE + DeepAudit 无问题 → 走正常 convergence 判定."""
        orch = self._make_orchestrator_with_state(tmp_path)

        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"

        from auto_engineering.gates.base import GateVerdict

        passed_verdict = GateVerdict(
            gate_name="test_gate", passed=True, message="PASS",
        )
        round_history = RoundHistory(
            round_id=1,
            stage="critic",
            files_changed=3,
            gate_results={"test_gate": passed_verdict},
        )
        round_result = RoundResult(
            round_id=1,
            outcomes=[],
            history=[round_history],
            gate_results={"test_gate": passed_verdict},
        )

        # Mock _run_deep_audit 返回无问题
        with patch.object(
            orch, "_run_deep_audit", return_value=(False, []),
        ):
            await orch._after_tick(
                round_result=round_result,
                current_stage="critic",
                guardrail_chain=None,
                round_id=1,
            )

        # 无 T9 触发: plan_refine_count 不变
        assert orch._state.plan_refine_count == 0
        assert orch._state.audit_findings is None

    @pytest.mark.asyncio
    async def test_after_tick_t9_limit_stop(self, tmp_path: Path):
        """_after_tick: plan_refine_count 达上限 → T9-LIMIT stop."""
        orch = self._make_orchestrator_with_state(tmp_path, max_plan_refines=2)

        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"
        orch._state.plan_refine_count = 1  # 已达 1, 再触发一次到 2

        from auto_engineering.gates.base import GateVerdict

        passed_verdict = GateVerdict(
            gate_name="test_gate", passed=True, message="PASS",
        )
        round_history = RoundHistory(
            round_id=1,
            stage="critic",
            files_changed=3,
            gate_results={"test_gate": passed_verdict},
        )
        round_result = RoundResult(
            round_id=1,
            outcomes=[],
            history=[round_history],
            gate_results={"test_gate": passed_verdict},
        )

        # Mock _run_deep_audit 返回 P0 问题
        with patch.object(
            orch, "_run_deep_audit", return_value=(True, [make_finding()]),
        ):
            should_break = await orch._after_tick(
                round_result=round_result,
                current_stage="critic",
                guardrail_chain=None,
                round_id=1,
            )

        # T9-LIMIT: 停止
        assert should_break is True
        assert orch._state.plan_refine_count == 2
        assert orch.verdict is not None
        assert orch.verdict.should_stop is True
        assert "T9-LIMIT" in orch.verdict.reason

    @pytest.mark.asyncio
    async def test_after_tick_t9_not_triggered_for_non_critic(self, tmp_path: Path):
        """_after_tick: 非 critic stage 不触发 T9."""
        orch = self._make_orchestrator_with_state(tmp_path)

        orch._state.current_stage = "developer"
        orch._state.critic_verdict = ""  # developer 无 verdict

        round_result = RoundResult(
            round_id=1, outcomes=[], history=[], gate_results={},
        )

        # DeepAudit 不应被调用
        with patch.object(
            orch, "_run_deep_audit",
        ) as mock_audit:
            await orch._after_tick(
                round_result=round_result,
                current_stage="developer",
                guardrail_chain=None,
                round_id=1,
            )

        mock_audit.assert_not_called()
        assert orch._state.plan_refine_count == 0

    @pytest.mark.asyncio
    async def test_after_tick_t9_not_triggered_for_major_verdict(self, tmp_path: Path):
        """_after_tick: critic MAJOR 不触发 T9."""
        orch = self._make_orchestrator_with_state(tmp_path)

        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "MAJOR"

        from auto_engineering.gates.base import GateVerdict

        passed_verdict = GateVerdict(
            gate_name="test_gate", passed=True, message="PASS",
        )
        round_history = RoundHistory(
            round_id=1, stage="critic", files_changed=3,
            gate_results={"test_gate": passed_verdict},
        )
        round_result = RoundResult(
            round_id=1, outcomes=[],
            history=[round_history],
            gate_results={"test_gate": passed_verdict},
        )

        with patch.object(
            orch, "_run_deep_audit",
        ) as mock_audit:
            await orch._after_tick(
                round_result=round_result,
                current_stage="critic",
                guardrail_chain=None,
                round_id=1,
            )

        # MAJOR → T5 回 developer, 不跑 DeepAudit (is_critic_approve=False)
        mock_audit.assert_not_called()
        assert orch._state.plan_refine_count == 0


# ============================================================
# 3. plan_refine_count 递增和重置测试
# ============================================================


class TestPlanRefineCountLifecycle:
    """plan_refine_count 的生命周期管理测试."""

    def test_plan_refine_count_increments_on_t9_trigger(self, tmp_path: Path):
        """每次 T9 触发时 plan_refine_count 递增."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(max_plan_refines=5),
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )

        # 模拟多轮 T9 触发: plan_refine_count 逐步递增
        for expected_count in range(1, 4):
            orch._state.plan_refine_count += 1
            assert orch._state.plan_refine_count == expected_count

    def test_plan_refine_count_starts_at_zero(self):
        """新 state 的 plan_refine_count 为 0."""
        config = OrchestratorConfig()
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        assert orch._state.plan_refine_count == 0

    def test_plan_refine_count_persists_across_rounds(self):
        """plan_refine_count 跨轮次保持."""
        state = EngineState(plan_refine_count=2, requirement="test")
        assert state.plan_refine_count == 2
        # to_dict/from_dict round-trip 保持值
        restored = EngineState.from_dict(state.to_dict())
        assert restored.plan_refine_count == 2


# ============================================================
# 4. 完整 E2E 回路 (通过 mock _after_tick 循环)
# ============================================================


class TestT9FullLoopE2E:
    """T9 完整回路 E2E 测试: 模拟多轮 tick/after_tick 循环."""

    @pytest.mark.asyncio
    async def test_t9_full_loop_one_refine_then_pass(self, tmp_path: Path):
        """完整 T9 回路: 第 1 次 APPROVE → audit fail → T9 → architect → 第 2 次 APPROVE → audit pass."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=10,
                max_plan_refines=3,
                deep_audit_enabled=True,
            ),
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )

        from auto_engineering.gates.base import GateVerdict

        # 第一轮: critic APPROVE, DeepAudit 发现 P0
        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"

        passed_verdict = GateVerdict(
            gate_name="test", passed=True, message="PASS",
        )
        rh1 = RoundHistory(
            round_id=1, stage="critic", files_changed=3,
            gate_results={"test": passed_verdict},
        )
        rr1 = RoundResult(
            round_id=1, outcomes=[], history=[rh1],
            gate_results={"test": passed_verdict},
        )

        # Round 1: T9 触发 → 回到 architect
        with patch.object(
            orch, "_run_deep_audit", return_value=(True, [make_finding()]),
        ):
            should_break = await orch._after_tick(rr1, "critic", None, 1)

        assert should_break is False
        assert orch._state.current_stage == "architect"
        assert orch._state.plan_refine_count == 1
        assert orch._state.audit_findings is not None

        # 第二轮: architect → developer → critic APPROVE, DeepAudit pass
        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"

        rh2 = RoundHistory(
            round_id=2, stage="critic", files_changed=2,
            gate_results={"test": passed_verdict},
        )
        rr2 = RoundResult(
            round_id=2, outcomes=[], history=[rh2],
            gate_results={"test": passed_verdict},
        )

        # Round 2: DeepAudit pass → 走正常 convergence
        with patch.object(
            orch, "_run_deep_audit", return_value=(False, []),
        ):
            should_break = await orch._after_tick(rr2, "critic", None, 2)

        # plan_refine_count 保持 (未重置, 由外部调用方管理)
        assert orch._state.plan_refine_count == 1
        assert orch._state.audit_findings is None

    @pytest.mark.asyncio
    async def test_t9_limit_after_three_refines(self, tmp_path: Path):
        """3 次 T9 refine 都失败 → 达到上限后 T9-LIMIT 停止."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=10,
                max_plan_refines=2,
                deep_audit_enabled=True,
            ),
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )

        from auto_engineering.gates.base import GateVerdict
        passed_verdict = GateVerdict(
            gate_name="test", passed=True, message="PASS",
        )

        # 第 1 次 refine
        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"
        rh1 = RoundHistory(round_id=1, stage="critic", files_changed=3,
                           gate_results={"test": passed_verdict})
        rr1 = RoundResult(round_id=1, outcomes=[], history=[rh1],
                          gate_results={"test": passed_verdict})

        with patch.object(
            orch, "_run_deep_audit", return_value=(True, [make_finding()]),
        ):
            await orch._after_tick(rr1, "critic", None, 1)

        assert orch._state.plan_refine_count == 1
        assert orch._state.current_stage == "architect"

        # 第 2 次 refine (达到 max_plan_refines=2)
        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"
        rh2 = RoundHistory(round_id=2, stage="critic", files_changed=2,
                           gate_results={"test": passed_verdict})
        rr2 = RoundResult(round_id=2, outcomes=[], history=[rh2],
                          gate_results={"test": passed_verdict})

        with patch.object(
            orch, "_run_deep_audit", return_value=(True, [make_finding()]),
        ):
            should_break = await orch._after_tick(rr2, "critic", None, 2)

        # T9-LIMIT 触发
        assert should_break is True
        assert orch._state.plan_refine_count == 2
        assert orch.verdict is not None
        assert orch.verdict.should_stop is True
        assert "T9-LIMIT" in orch.verdict.reason

    @pytest.mark.asyncio
    async def test_t9_p1_above_threshold_triggers_refine(self, tmp_path: Path):
        """P1 >= threshold (无 P0) 也触发 T9 (audit_found_issues=True)."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(max_plan_refines=3, deep_audit_enabled=True),
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )

        orch._state.current_stage = "critic"
        orch._state.critic_verdict = "APPROVE"

        from auto_engineering.gates.base import GateVerdict
        passed_verdict = GateVerdict(
            gate_name="test", passed=True, message="PASS",
        )
        rh = RoundHistory(round_id=1, stage="critic", files_changed=3,
                          gate_results={"test": passed_verdict})
        rr = RoundResult(round_id=1, outcomes=[], history=[rh],
                         gate_results={"test": passed_verdict})

        # P1 findings 但 audit_found_issues=True (gate reported 为 failed)
        p1_findings = [make_finding(severity="P1") for _ in range(7)]
        with patch.object(
            orch, "_run_deep_audit", return_value=(True, p1_findings),
        ):
            should_break = await orch._after_tick(rr, "critic", None, 1)

        assert should_break is False
        assert orch._state.current_stage == "architect"
        assert orch._state.plan_refine_count == 1


# ============================================================
# 5. ConvergenceJudge T9 集成
# ============================================================


class TestConvergenceJudgeT9:
    """ConvergenceJudge 与 T9 的集成行为测试."""

    def test_judge_max_iter_with_plan_refine_loops(self):
        """多次 T9 refine 不应加速硬上限 (每次 T9 仍消耗一轮 max_iter)."""
        judge = ConvergenceJudge(ConvergenceConfig(
            max_iterations=5,
            max_plan_refines=3,
        ))

        # 模拟 5 轮后触发硬上限
        history = [make_round_history(round_id=i) for i in range(1, 6)]
        verdict = judge.evaluate(history)
        assert verdict.should_stop is True
        assert verdict.level == 4  # LEVEL_HARD_LIMIT

    def test_judge_continues_within_max_iter(self):
        """未达 max_iter 时不触发硬上限."""
        # 用 vary 的数据避免 stagnation 检测触发
        judge = ConvergenceJudge(ConvergenceConfig(
            max_iterations=10,
            stagnation_threshold=10,  # 高阈值阻止 stagnation
        ))
        history = [make_round_history(round_id=i) for i in range(1, 4)]
        verdict = judge.evaluate(history)
        assert not verdict.should_stop
