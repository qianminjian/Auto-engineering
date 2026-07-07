"""v5.5 Phase 2 — Orchestrator T9 + DeepAudit 集成测试.

测试覆盖:
    1. OrchestratorConfig 接受 ConvergenceConfig v5.5 扩展字段
    2. EngineState 包含 audit_findings + plan_refine_count
    3. StageRouter.next() 接受 T9 参数并返回 T9 转换
    4. StageRouter 返回 T9-LIMIT (plan_refine_count >= max_plan_refines)
    5. Orchestrator._run_deep_audit() 返回 (bool, list[dict])
    6. GateVerdict.details 含 findings
    7. Orchestrator._sync_design_docs() 骨架不抛异常
    8. T9 flow: audit found issues → skip judge → back to architect
    9. Normal flow: no audit issues → judge convergence → GOAL_ACHIEVED
    10. EngineState v5.5 字段 round-trip

测试原则 (per pytest-memory-management.md):
    - 单文件 pytest --no-cov --timeout=60
    - 用 mock/fake 避免真实 LLM 调用
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.gates.base import GateVerdict
from auto_engineering.loop.convergence import ConvergenceConfig, ConvergenceJudge
from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
from auto_engineering.loop.stage_router import StageRouter


class TestOrchestratorV55Integration:
    """v5.5 Phase 2 完整集成: Orchestrator + StageRouter + EngineState + DeepAudit."""

    # --- 1. OrchestratorConfig 接受 ConvergenceConfig 扩展字段 ---

    def test_config_accepts_v55_fields(self) -> None:
        """OrchestratorConfig 接受 ConvergenceConfig v5.5 扩展字段."""
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=10,
                auto_tune=True,
                max_plan_refines=5,
                min_samples_for_learning=8,
            ),
        )
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        assert orch.judge is not None
        assert orch.judge.config.auto_tune is True
        assert orch.judge.config.max_plan_refines == 5
        assert orch.judge.config.min_samples_for_learning == 8

    def test_config_default_v55_fields(self) -> None:
        """默认 OrchestratorConfig → ConvergenceConfig 默认值."""
        config = OrchestratorConfig()
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        assert orch.judge.config.auto_tune is False
        assert orch.judge.config.max_plan_refines == 3
        assert orch.judge.config.min_samples_for_learning == 5

    # --- 2. EngineState 包含 audit_findings + plan_refine_count ---

    def test_state_has_v55_fields_with_defaults(self) -> None:
        """Orchestrator._state 包含 audit_findings + plan_refine_count."""
        config = OrchestratorConfig()
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        assert orch._state is not None
        assert orch._state.audit_findings is None
        assert orch._state.plan_refine_count == 0
        assert orch._state.strengths is None
        assert orch._state.assessment is None

    def test_state_v55_fields_round_trip(self) -> None:
        """v5.5 字段 to_dict/from_dict round-trip."""
        state = EngineState(
            audit_findings=[
                {"severity": "P0", "file": "x.py", "line": 10,
                 "description": "null deref", "dimension": "代码质量",
                 "evidence": "...", "suggested_fix": "...",
                 "agent_source": "code_quality"},
            ],
            plan_refine_count=2,
            strengths=["clean code"],
            assessment="Minor issues",
        )
        restored = EngineState.from_dict(state.to_dict())
        assert restored.audit_findings == state.audit_findings
        assert restored.plan_refine_count == 2
        assert restored.strengths == state.strengths
        assert restored.assessment == state.assessment

    # --- 3. StageRouter.next() 接受 T9 参数 ---

    def test_stage_router_t9_back_to_architect(self) -> None:
        """T9: audit_found_issues=True + under limit → next='architect'."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
            audit_found_issues=True,
            plan_refine_count=1,
            max_plan_refines=3,
        )
        assert decision.next_stage == "architect"
        assert decision.should_stop is False

    def test_stage_router_t9_backward_compatible(self) -> None:
        """无 T9 参数 → 向后兼容 T4 (APPROVE → next=None)."""
        router = StageRouter()
        decision = router.next(
            current_stage="critic",
            verdict="APPROVE",
            majors_in_a_row=0,
            total_majors=0,
        )
        assert decision.next_stage is None
        assert decision.should_stop is False

    # --- 4. StageRouter 返回 T9-LIMIT ---

    def test_stage_router_t9_limit_stop(self) -> None:
        """T9-LIMIT: plan_refine_count >= max_plan_refines → should_stop=True."""
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
        assert "T9-LIMIT" in decision.stop_reason

    def test_stage_router_t9_limit_custom_max(self) -> None:
        """T9-LIMIT 自定义 max_plan_refines=2."""
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
        assert decision.should_stop is True

    # --- 5. _run_deep_audit() 返回 (bool, list[dict]) ---

    def test_run_deep_audit_returns_tuple(self, tmp_path: Path) -> None:
        """_run_deep_audit() 返回 (bool, list[dict])."""
        config = OrchestratorConfig(project_root=tmp_path)
        orch = Orchestrator(
            requirement="x", tasks=[], executor=None, config=config,
        )
        audit_found, findings = orch._run_deep_audit(tmp_path)
        assert isinstance(audit_found, bool)
        assert isinstance(findings, list)

    def test_run_deep_audit_no_files_no_findings(self, tmp_path: Path) -> None:
        """空项目 → audit_found_issues=False, findings=[]."""
        config = OrchestratorConfig(project_root=tmp_path)
        orch = Orchestrator(
            requirement="x", tasks=[], executor=None, config=config,
        )
        audit_found, findings = orch._run_deep_audit(tmp_path)
        assert audit_found is False
        assert findings == []

    # --- 5a. Task 4.1: JSONL 审计历史写入 ---

    def test_run_deep_audit_writes_jsonl(self, tmp_path: Path) -> None:
        """_run_deep_audit() 完成后写入 JSONL 审计历史."""
        config = OrchestratorConfig(project_root=tmp_path)
        orch = Orchestrator(
            requirement="x", tasks=[], executor=None, config=config,
        )
        orch._run_deep_audit(tmp_path)

        jsonl_path = tmp_path / ".ae-state" / "audit-history.jsonl"
        assert jsonl_path.exists(), "JSONL 审计历史文件应存在"

        import json
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) >= 1, "应至少写入一条记录"
        entry = json.loads(lines[0])
        assert "p0_count" in entry
        assert "p1_count" in entry
        assert "p2_count" in entry
        assert "p1_threshold" in entry
        assert "total_files" in entry
        assert "plan_refine_triggered" in entry
        assert "timestamp" in entry

    # --- 6. GateVerdict.details 含 findings ---

    def test_gate_verdict_details_has_findings(self) -> None:
        """GateVerdict.details 含 findings 列表."""
        verdict = GateVerdict(
            gate_name="DeepAuditGate",
            passed=False,
            message="FAIL (P0=1, P1=2)",
            details={
                "p0_count": 1, "p1_count": 2, "p2_count": 3,
                "findings": [
                    {"severity": "P0", "file": "x.py", "line": 10,
                     "description": "null deref"},
                ],
            },
            suggestions=["Add null check"],
        )
        assert "findings" in verdict.details
        assert len(verdict.details["findings"]) == 1
        assert verdict.details["findings"][0]["severity"] == "P0"

    def test_gate_verdict_passed_no_findings(self) -> None:
        """GateVerdict passed → findings 为空."""
        verdict = GateVerdict(
            gate_name="DeepAuditGate",
            passed=True,
            message="PASS (P0=0, P1=0/6, P2=0)",
            details={"p0_count": 0, "p1_count": 0, "p2_count": 0, "findings": []},
        )
        assert verdict.passed is True
        assert verdict.details["findings"] == []

    # --- 7. _sync_design_docs() 骨架 ---

    def test_sync_design_docs_does_not_raise(self) -> None:
        """_sync_design_docs() 骨架不抛异常."""
        state = EngineState(requirement="test")
        config = OrchestratorConfig()
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        orch._sync_design_docs(state)  # Should not raise

    # --- 8. ConvergenceFacade._all_gates_passed 逻辑 ---

    def test_all_gates_passed_empty_history(self) -> None:
        """空 gate_results → ConvergenceFacade._all_gates_passed 返回 True."""
        from auto_engineering.loop.convergence_facade import ConvergenceFacade

        assert ConvergenceFacade._all_gates_passed({}) is True

    # --- 9. Orchestrator 初始化包含 v5.5 字段 ---

    def test_orchestrator_init_has_v55_routing(self) -> None:
        """Orchestrator.__post_init__ 包含 v5.5 内部状态."""
        config = OrchestratorConfig()
        orch = Orchestrator(
            requirement="test", tasks=[], executor=None, config=config,
        )
        assert orch._state is not None
        assert orch._state.audit_findings is None
        assert orch._state.plan_refine_count == 0
        assert orch._router is not None, "StageRouter 应在 __post_init__ 初始化"

    # --- 10. Critic findings severity 映射端到端 ---

    def test_severity_mapping_integration(self) -> None:
        """Critic outcome findings severity 映射: Critical→P0, Important→P1, Minor→P2."""
        from auto_engineering.loop.round import TaskOutcome
        from auto_engineering.loop.task_factory import apply_outcome_to_state

        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "Critical", "file": "a.py", "line": 1,
                     "issue": "crash"},
                    {"severity": "Important", "file": "b.py", "line": 2,
                     "issue": "leak"},
                    {"severity": "Minor", "file": "c.py", "line": 3,
                     "issue": "style"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P0"
        assert state.findings[1]["severity"] == "P1"
        assert state.findings[2]["severity"] == "P2"
