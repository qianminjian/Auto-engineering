"""v5.1 Quality Gate 测试 — TDDGate + StageTransitionGate.

借鉴:
- CrewAI GuardrailResult: success/result/error 三态
- SonarQube Quality Gate: 度量+阈值条件, 任一不满足→blocked
"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.gates.quality_gate import TDDGate, StageTransitionGate


class TestTDDGate:
    def test_passes_when_test_files_exist(self, tmp_path):
        gate = TDDGate(project_root=tmp_path)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_feat.py").write_text("def test_ok(): pass")

        state = EngineState(requirement="test")
        state.files_changed = ["src/feat.py", "tests/test_feat.py"]

        verdict = gate.check("developer", state, project_root=tmp_path)
        assert verdict.passed, verdict.message

    def test_fails_when_no_test_files_for_src_changes(self, tmp_path):
        gate = TDDGate(project_root=tmp_path)

        state = EngineState(requirement="test")
        state.files_changed = ["src/feat.py", "src/utils.py"]

        verdict = gate.check("developer", state, project_root=tmp_path)
        assert not verdict.passed
        assert "Red phase" in verdict.message

    def test_fails_when_test_file_empty(self, tmp_path):
        gate = TDDGate(project_root=tmp_path)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_feat.py").write_text("")

        state = EngineState(requirement="test")
        state.files_changed = ["src/feat.py", "tests/test_feat.py"]

        verdict = gate.check("developer", state, project_root=tmp_path)
        assert not verdict.passed
        assert "为空" in verdict.message

    def test_passes_when_no_src_changes(self, tmp_path):
        gate = TDDGate(project_root=tmp_path)
        state = EngineState(requirement="test")
        state.files_changed = []

        verdict = gate.check("developer", state, project_root=tmp_path)
        assert verdict.passed

    def test_not_applied_to_architect_or_critic(self):
        gate = TDDGate()
        assert "architect" not in gate.applies_to_stages
        assert "critic" not in gate.applies_to_stages
        assert "developer" in gate.applies_to_stages


class TestStageTransitionGate:
    def test_architect_stage_checks_requirement(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="build login feature")
        verdict = gate.check("architect", state)
        assert verdict.passed, verdict.message

    def test_architect_stage_fails_empty_requirement(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="")
        verdict = gate.check("architect", state)
        assert not verdict.passed
        assert "requirement_not_empty" in verdict.message

    def test_developer_stage_fails_missing_architect_outputs(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="test")
        # architect 产出全部缺失
        state.plan = ""
        state.file_list = []
        state.batch_plan = []

        verdict = gate.check("developer", state)
        assert not verdict.passed
        assert "plan" in verdict.message.lower()

    def test_developer_stage_passes_with_architect_outputs(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="test")
        state.plan = "Implement login with JWT"
        state.file_list = ["src/auth.py", "tests/test_auth.py"]
        state.batch_plan = [
            {
                "id": "T1",
                "description": "Implement login",
                "expected_output": "login function working",
            }
        ]

        verdict = gate.check("developer", state)
        assert verdict.passed, verdict.message

    def test_critic_stage_fails_missing_developer_outputs(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="test")
        state.files_changed = []
        state.test_results = {}

        verdict = gate.check("critic", state)
        assert not verdict.passed

    def test_critic_stage_passes_with_developer_outputs(self):
        gate = StageTransitionGate()
        state = EngineState(requirement="test")
        state.files_changed = ["src/auth.py", "tests/test_auth.py"]
        state.test_results = {"total": 5, "passed": 5, "failed": 0}

        verdict = gate.check("critic", state)
        assert verdict.passed, verdict.message

    def test_applies_to_all_stages(self):
        gate = StageTransitionGate()
        assert "architect" in gate.applies_to_stages
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages
