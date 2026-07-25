"""T70: ThresholdLearner tests — RED phase."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.metrics.threshold_learner import (
    ThresholdEstimate,
    ThresholdLearner,
)


class TestThresholdEstimate:
    def test_posterior_mean_defaults_to_midpoint_of_range(self):
        est = ThresholdEstimate("M1_tick_limit", alpha=2.0, beta=2.0,
                                min_value=5, max_value=30)
        assert est.posterior_mean == pytest.approx(17.5, rel=1e-6)

    def test_posterior_mean_converges_after_observations(self):
        est = ThresholdEstimate("test", alpha=2.0, beta=2.0,
                                min_value=0, max_value=100)
        for _ in range(10):
            est.observe(True)
        assert est.posterior_mean == pytest.approx(85.714, rel=1e-2)

    def test_posterior_mean_decreases_after_failures(self):
        est = ThresholdEstimate("test", alpha=2.0, beta=2.0,
                                min_value=0, max_value=100)
        for _ in range(10):
            est.observe(False)
        assert est.posterior_mean == pytest.approx(14.286, rel=1e-2)

    def test_confidence_decreases_with_more_observations(self):
        est = ThresholdEstimate("test")
        c0 = est.confidence
        for _ in range(10):
            est.observe(True)
        assert est.confidence < c0

    def test_total_obs_excludes_prior_pseudo_counts(self):
        est = ThresholdEstimate("test", alpha=2.0, beta=2.0)
        assert est.total_obs == 0
        est.observe(True)
        est.observe(True)
        est.observe(False)
        assert est.total_obs == 3

    def test_is_ready_requires_min_obs(self):
        est = ThresholdEstimate("test", min_obs=5)
        assert not est.is_ready()
        for _ in range(5):
            est.observe(True)
        assert est.is_ready()

    def test_observe_works_well_increments_alpha(self):
        est = ThresholdEstimate("test", alpha=2.0, beta=2.0)
        est.observe(True)
        assert est.alpha == 3.0
        assert est.beta == 2.0

    def test_observe_not_well_increments_beta(self):
        est = ThresholdEstimate("test", alpha=2.0, beta=2.0)
        est.observe(False)
        assert est.alpha == 2.0
        assert est.beta == 3.0


class TestThresholdLearner:
    @pytest.fixture
    def metrics_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".ae-state" / "metrics"
        d.mkdir(parents=True)
        return d

    def test_init_creates_10_estimates(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        assert len(learner._estimates) == 10

    def test_init_loads_saved_posteriors(self, metrics_dir: Path):
        baselines = metrics_dir / "baselines"
        baselines.mkdir(parents=True)
        state = {"M1_tick_limit": {"alpha": 10.0, "beta": 2.0}}
        (baselines / "threshold_posteriors.json").write_text(json.dumps(state))
        learner = ThresholdLearner(metrics_dir)
        assert learner._estimates["M1_tick_limit"].alpha == 10.0
        assert learner._estimates["M1_tick_limit"].beta == 2.0

    def test_observe_requirement_updates_all_estimates(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        summary = {
            "M1_loop_efficiency": 8,
            "M2_critic_major_rate": 0.3,
            "M4_plan_refine_count": 1,
            "M5_token_efficiency": {"total_tokens": 50000},
        }
        signals: list[dict] = []
        learner.observe_requirement(summary, signals)
        for est in learner._estimates.values():
            assert est.total_obs == 1

    def test_observe_requirement_with_signals_marks_failure(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        summary = {
            "M1_loop_efficiency": 15,
            "M2_critic_major_rate": 0.6,
            "M4_plan_refine_count": 5,
            "M5_token_efficiency": {"total_tokens": 500000},
        }
        signals = [
            {"name": "slow_convergence"},
            {"name": "critic_major_increasing"},
            {"name": "plan_refine_spike"},
            {"name": "token_efficiency_drop"},
        ]
        learner.observe_requirement(summary, signals)
        assert learner._estimates["M1_tick_limit"].beta > 2.0
        assert learner._estimates["M2_cons_rise"].beta > 2.0
        assert learner._estimates["M4_refine_limit"].beta > 2.0
        assert learner._estimates["M5_token_limit"].beta > 2.0

    def test_propose_adjustments_returns_empty_when_not_ready(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        proposals = learner.propose_adjustments()
        assert proposals == []

    def test_propose_adjustments_returns_proposals_when_deviation_above_5pct(
        self, metrics_dir: Path,
    ):
        learner = ThresholdLearner(metrics_dir)
        for _ in range(30):
            learner._estimates["M1_tick_limit"].observe(False)
        proposals = learner.propose_adjustments()
        m1_proposals = [p for p in proposals if p["param"] == "M1_tick_limit"]
        assert len(m1_proposals) == 1

    def test_save_and_load_roundtrip(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        for _ in range(5):
            learner._estimates["M1_tick_limit"].observe(True)
        learner._save_state()
        path = metrics_dir / "baselines" / "threshold_posteriors.json"
        assert path.exists()
        state = json.loads(path.read_text())
        assert state["M1_tick_limit"]["alpha"] == 7.0
        learner2 = ThresholdLearner(metrics_dir)
        assert learner2._estimates["M1_tick_limit"].alpha == 7.0

    def test_get_current_value_falls_back_to_defaults(self, metrics_dir: Path):
        learner = ThresholdLearner(metrics_dir)
        assert learner._get_current_value("M1_tick_limit") == 12.0
        assert learner._get_current_value("max_refine_per_source") == 2.0
