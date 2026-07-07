"""M1 Stage 状态机 — StageRouter + StageDecision + 5 helper functions 测试.

设计参考: v5.0-Design-Loop.md §B2.2 (StageRouter 接口契约)
                   + §B3.1-B3.4 (Stage 状态机 + MAJOR 计数 + clear + derive)

测试原则 (per pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- 参数化覆盖 8 转换 (T1-T6 + 边界)
- MAJOR 计数耗尽场景
- StageDecision 数据类字段
- clear_stage_fields 3 stage 映射
- _derive_status 4 边界 (已移除, dead code, v5.4 P0-1)"""

from __future__ import annotations

import re

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.stage_router import (
    StageDecision,
    StageRouter,
    clear_stage_fields,
    update_majors_count,
)


# ---------- StageDecision 数据类字段 ----------

class TestStageDecisionFields:
    """StageDecision 必须含 next_stage / should_stop / stop_reason 三个字段."""

    def test_default_next_stage_none(self) -> None:
        """默认 next_stage=None (Stage 终止信号)."""
        decision = StageDecision(should_stop=False)
        assert decision.next_stage is None

    def test_default_should_stop_false(self) -> None:
        """默认 should_stop=False."""
        decision = StageDecision(next_stage="architect")
        assert decision.should_stop is False

    def test_default_stop_reason_none(self) -> None:
        """默认 stop_reason=None (只在 should_stop=True 时填)."""
        decision = StageDecision(next_stage="developer", should_stop=True)
        assert decision.stop_reason is None  # 显式 None 仍是 None

    def test_explicit_fields(self) -> None:
        """3 字段可显式赋值."""
        decision = StageDecision(
            next_stage="developer",
            should_stop=True,
            stop_reason="MAJOR 超限: 连续2/累计2",
        )
        assert decision.next_stage == "developer"
        assert decision.should_stop is True
        assert decision.stop_reason == "MAJOR 超限: 连续2/累计2"


# ---------- T1-T6 转换表 ----------

class TestStageTransitions:
    """StageRouter.next() 8 转换测试 (T1-T6 + 边界)."""

    def test_t1_empty_to_architect(self) -> None:
        """T1: stage='' → next='architect'."""
        router = StageRouter()
        decision = router.next(
            current_stage="",
            verdict="",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage == "architect"
        assert decision.should_stop is False

    def test_t2_architect_to_developer(self) -> None:
        """T2: architect → developer."""
        router = StageRouter()
        decision = router.next(
            current_stage="architect",
            verdict="",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage == "developer"
        assert decision.should_stop is False

    def test_t3_developer_to_critic(self) -> None:
        """T3: developer → critic."""
        router = StageRouter()
        decision = router.next(
            current_stage="developer",
            verdict="",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage == "critic"
        assert decision.should_stop is False

    def test_t4_critic_approve_should_stop_false(self) -> None:
        """T4: critic + APPROVE → next=None, should_stop=False (Judge 触发 GOAL_ACHIEVED)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage is None
        assert decision.should_stop is False
        assert decision.stop_reason is None

    def test_t5_critic_major_below_limit_returns_developer(self) -> None:
        """T5: critic + MAJOR + 未超限 → developer."""
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=1,  # < 2
            total_majors=1,  # < 3
        )
        assert decision.next_stage == "developer"
        assert decision.should_stop is False

    def test_t6_critic_major_in_a_row_exceeds_should_stop(self) -> None:
        """T6: critic + MAJOR + majors_in_a_row >= max → should_stop=True."""
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=2,  # >= max
            total_majors=2,
        )
        assert decision.next_stage is None
        assert decision.should_stop is True
        assert decision.stop_reason is not None
        assert "MAJOR 超限" in decision.stop_reason

    def test_t6_critic_total_majors_exceeds_should_stop(self) -> None:
        """T6 变体: total_majors >= max_total → should_stop=True."""
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=1,  # < 2 (未超连续)
            total_majors=3,  # >= 3 (超累计)
        )
        assert decision.next_stage is None
        assert decision.should_stop is True
        assert decision.stop_reason is not None
        assert "累计" in decision.stop_reason

    def test_critic_empty_verdict_raises(self) -> None:
        """critic + verdict='' → 抛 CriticVerdictInvalid (Bug 3 prismscan 修复).

        旧行为: should_stop=True (反向语义: 异常 → PASS → 停止)
        新行为: 抛 CriticVerdictInvalid 让 orchestrator 显式处理 (重试/升级).
        """
        from auto_engineering.loop.stage_router import CriticVerdictInvalid

        router = StageRouter()
        with pytest.raises(CriticVerdictInvalid) as exc_info:
            router.next(
                current_stage="critic",
                verdict="",
                majors_in_a_row=0,
                total_majors=0,
            )
        assert exc_info.value.verdict == ""
        assert "critic 返回非法 verdict" in str(exc_info.value)


# ---------- MAJOR 计数耗尽场景 ----------

class TestMajorLimitBoundary:
    """MAJOR 边界: max-1 vs max."""

    def test_majors_in_a_row_at_max_minus_one(self) -> None:
        """majors_in_a_row = max-1: 仍返回 developer."""
        router = StageRouter(max_majors_in_a_row=2)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=1,
            total_majors=2,
        )
        assert decision.next_stage == "developer"

    def test_majors_in_a_row_at_max(self) -> None:
        """majors_in_a_row = max: 触发 stop."""
        router = StageRouter(max_majors_in_a_row=2)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=2,
            total_majors=2,
        )
        assert decision.should_stop is True

    def test_total_majors_at_max_minus_one(self) -> None:
        """total_majors = max_total-1: 仍返回 developer."""
        router = StageRouter(max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=0,  # 连续未超, 但已重置 (APPROVE 后)
            total_majors=2,
        )
        assert decision.next_stage == "developer"

    def test_total_majors_at_max(self) -> None:
        """total_majors = max_total: 触发 stop."""
        router = StageRouter(max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=0,
            total_majors=3,
        )
        assert decision.should_stop is True

    def test_stop_reason_format(self) -> None:
        """stop_reason 格式: 包含 'MAJOR 超限' + 连续/累计数字."""
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)
        decision = router.next(
            current_stage="critic",
            verdict="MAJOR",
            majors_in_a_row=2,
            total_majors=2,
        )
        assert decision.stop_reason is not None
        # 验证格式: "MAJOR 超限: 连续2/累计2" 或类似
        assert re.search(r"连续\s*2", decision.stop_reason)
        assert re.search(r"累计\s*2", decision.stop_reason)


# ---------- update_majors_count ----------

class TestUpdateMajorsCount:
    """MAJOR 计数更新逻辑 (§B3.2)."""

    def test_approve_resets_in_a_row(self) -> None:
        """verdict=APPROVE → majors_in_a_row 重置为 0."""
        state = EngineState(majors_in_a_row=2, total_majors=3)
        update_majors_count(state, "APPROVE")
        assert state.majors_in_a_row == 0
        assert state.total_majors == 3  # total 不重置

    def test_major_increments_both(self) -> None:
        """verdict=MAJOR → majors_in_a_row += 1, total_majors += 1."""
        state = EngineState(majors_in_a_row=1, total_majors=2)
        update_majors_count(state, "MAJOR")
        assert state.majors_in_a_row == 2
        assert state.total_majors == 3

    def test_empty_verdict_no_change(self) -> None:
        """verdict='' → 不变."""
        state = EngineState(majors_in_a_row=1, total_majors=2)
        update_majors_count(state, "")
        assert state.majors_in_a_row == 1
        assert state.total_majors == 2

    def test_initial_zero_increments_to_one(self) -> None:
        """初始 0 → MAJOR → 1."""
        state = EngineState()
        update_majors_count(state, "MAJOR")
        assert state.majors_in_a_row == 1
        assert state.total_majors == 1


# ---------- clear_stage_fields ----------

class TestClearStageFields:
    """clear_stage_fields 3 stage 映射 (§B3.3)."""

    def test_clear_architect_fields(self) -> None:
        """stage='architect' → clear plan / file_list / batch_plan / contracts / audit_findings."""
        state = EngineState(
            plan="some plan",
            file_list=["a.py", "b.py"],
            batch_plan=[{"id": "1"}],
            contracts={"k": "v"},
            audit_findings=[{"severity": "P0", "file": "x.py"}],
            verdict="MAJOR",
            findings=[{"x": 1}],
            files_changed=["x.py"],
            commit_hash="abc",
            test_results={"passed": 1},
            critic_feedback="fb",
        )
        clear_stage_fields(state, "architect")
        assert state.plan == ""
        assert state.file_list == []
        assert state.batch_plan == []
        assert state.contracts == {}
        assert state.audit_findings is None, "audit_findings 应在 architect 阶段清除时重置"
        # 其他字段不应被清空 (Stage 隔离)
        assert state.verdict == "MAJOR"
        assert state.findings == [{"x": 1}]
        assert state.files_changed == ["x.py"]

    def test_clear_developer_fields(self) -> None:
        """stage='developer' → clear files_changed / commit_hash / test_results."""
        state = EngineState(
            plan="kept",
            files_changed=["x.py", "y.py"],
            commit_hash="abc123",
            test_results={"passed": 5, "failed": 0},
            verdict="APPROVE",
            findings=[{"x": 1}],
        )
        clear_stage_fields(state, "developer")
        assert state.files_changed == []
        assert state.commit_hash == ""
        assert state.test_results == {}
        # 其他字段保留
        assert state.plan == "kept"
        assert state.verdict == "APPROVE"

    def test_clear_critic_fields(self) -> None:
        """stage='critic' → clear verdict / findings / critic_feedback."""
        state = EngineState(
            verdict="MAJOR",
            findings=[{"x": 1}],
            critic_feedback="bad code",
            plan="kept",
            files_changed=["kept.py"],
        )
        clear_stage_fields(state, "critic")
        assert state.verdict == ""
        assert state.findings == []
        assert state.critic_feedback == ""
        # 其他字段保留
        assert state.plan == "kept"
        assert state.files_changed == ["kept.py"]


# ---------- EngineState 新字段集成 ----------

class TestNewEngineStateFields:
    """EngineState 17 字段集成 (M1 Task 1)."""

    def test_new_fields_exist(self) -> None:
        """4 个新字段都存在."""
        state = EngineState()
        assert hasattr(state, "batch_plan")
        assert hasattr(state, "majors_in_a_row")
        assert hasattr(state, "total_majors")
        assert hasattr(state, "thread_id")

    def test_thread_id_auto_generated(self) -> None:
        """thread_id 默认自动生成 UUID v4 格式."""
        state = EngineState()
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        assert uuid_pattern.match(state.thread_id), f"Invalid UUID: {state.thread_id}"

    def test_thread_id_unique_per_instance(self) -> None:
        """thread_id 每次实例化都不同."""
        s1 = EngineState()
        s2 = EngineState()
        assert s1.thread_id != s2.thread_id

    def test_thread_id_explicit_override(self) -> None:
        """thread_id 可显式覆盖."""
        state = EngineState(thread_id="custom-id-1234")
        assert state.thread_id == "custom-id-1234"

    def test_majors_default_zero(self) -> None:
        """majors_in_a_row / total_majors 默认 0."""
        state = EngineState()
        assert state.majors_in_a_row == 0
        assert state.total_majors == 0

    def test_batch_plan_default_empty_list(self) -> None:
        """batch_plan 默认空 list (不是 None)."""
        state = EngineState()
        assert state.batch_plan == []
        assert isinstance(state.batch_plan, list)

    def test_field_count_is_18(self) -> None:
        """字段总数 = 22 (v5.5 P0-4: +round).

        v5.5 P0-4: 21 → 22 (+round).
        """
        state = EngineState()
        fields = list(state.__dataclass_fields__.keys())
        assert len(fields) == 22, (
            f"Expected 22 fields (v5.5), got {len(fields)}: {fields}"
        )


# ---------- v5.5 T9/T9-LIMIT 转换 (DeepAudit → PLAN-REFINE 回路) ----------


class TestT9Transition:
    """v5.5 T9: DeepAudit 发现问题 → 回到 architect (PLAN-REFINE)."""

    def test_t9_audit_found_issues_returns_architect(self) -> None:
        """T9: audit_found_issues=True + plan_refine_count < max → next='architect'."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=0,
            max_plan_refines=3,
        )
        assert decision.next_stage == "architect"
        assert decision.should_stop is False

    def test_t9_limit_reached_should_stop(self) -> None:
        """T9-LIMIT: audit_found_issues=True + plan_refine_count >= max → stop."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=3,
            max_plan_refines=3,
        )
        assert decision.next_stage is None
        assert decision.should_stop is True
        assert decision.stop_reason is not None
        assert "T9-LIMIT" in decision.stop_reason
        assert "plan refine 上限" in decision.stop_reason

    def test_t9_exceeds_limit_should_stop(self) -> None:
        """T9-LIMIT: plan_refine_count > max → stop."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=5,
            max_plan_refines=3,
        )
        assert decision.next_stage is None
        assert decision.should_stop is True

    def test_t9_plan_refine_count_at_max_minus_one(self) -> None:
        """T9: plan_refine_count = max-1 → 仍返回 architect (未超限)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=2,
            max_plan_refines=3,
        )
        assert decision.next_stage == "architect"
        assert decision.should_stop is False

    def test_no_audit_issues_returns_normal_t4_behavior(self) -> None:
        """audit_found_issues=False → 正常 T4 行为 (next=None, should_stop=False)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=False,
            plan_refine_count=0,
            max_plan_refines=3,
        )
        assert decision.next_stage is None
        assert decision.should_stop is False

    def test_t9_defaults_backward_compatible(self) -> None:
        """无 T9 参数 → 向后兼容 T4 行为."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
        )
        # 默认 audit_found_issues=False → T4
        assert decision.next_stage is None
        assert decision.should_stop is False

    def test_t9_custom_max_plan_refines(self) -> None:
        """自定义 max_plan_refines=2 → 第 2 次触发 T9-LIMIT."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=2,
            max_plan_refines=2,
        )
        assert decision.next_stage is None
        assert decision.should_stop is True
        assert "T9-LIMIT" in decision.stop_reason