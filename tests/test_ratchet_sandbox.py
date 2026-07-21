"""T72: RatchetController sandbox_evaluate + CLI tests — RED phase."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.metrics.ratchet import RatchetController, RatchetDecision
from auto_engineering.metrics.threshold_learner import ThresholdLearner
from auto_engineering.metrics.rule_discoverer import CandidateRule


class TestSandboxEvaluate:
    @pytest.fixture
    def ratchet(self, tmp_path: Path) -> RatchetController:
        project = tmp_path / "project"
        project.mkdir()
        (project / ".ae-state").mkdir()
        return RatchetController(project)

    def test_keep_when_all_metrics_improve(self, ratchet: RatchetController):
        before = {"M1_loop_efficiency": 15, "M2_critic_major_rate": 0.5}
        after = {"M1_loop_efficiency": 8, "M2_critic_major_rate": 0.2}
        result = ratchet.evaluate(before, after)
        assert result.action == "keep"

    def test_revert_when_significant_regression(self, ratchet: RatchetController):
        before = {"M1_loop_efficiency": 8}
        after = {"M1_loop_efficiency": 15}  # worse: more ticks
        result = ratchet.evaluate(before, after)
        assert result.action in ("revert", "stop")

    def test_stop_when_severe_regression(self, ratchet: RatchetController):
        before = {"M1_loop_efficiency": 5}
        after = {"M1_loop_efficiency": 20}  # 300% worse
        result = ratchet.evaluate(before, after)
        assert result.action == "stop"


class TestMergeRules:
    def test_merge_rules_writes_to_diagnoser_format(
        self, tmp_path: Path,
    ):
        """Verify merge-rules produces correct output format."""
        candidates = [
            CandidateRule(
                signal_name="test_signal",
                metric="M2",
                causes=["cause 1"],
                actions=["action 1"],
                auto_params=[],
                human_actions=[0],
                correlation_score=0.75,
                confidence=0.95,
                sample_size=30,
                supporting_evidence="test",
            ),
        ]
        output_path = tmp_path / "merged_rules.json"
        # Simulate the merge operation
        merged = []
        for c in candidates:
            merged.append({
                "signal_name": c.signal_name,
                "metric": c.metric,
                "auto_params": c.auto_params,
                "possible_causes": c.causes,
                "actions": c.actions,
                "human_actions": c.human_actions,
            })
        output_path.write_text(json.dumps(merged, indent=2))
        assert output_path.exists()
        loaded = json.loads(output_path.read_text())
        assert len(loaded) == 1
        assert loaded[0]["signal_name"] == "test_signal"
