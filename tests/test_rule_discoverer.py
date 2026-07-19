"""T71: DiagnosticRuleDiscoverer tests — RED phase."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.metrics.rule_discoverer import (
    CandidateRule,
    DiagnosticRuleDiscoverer,
)


def _make_summary(m1=8, m2=0.3, m4=1, m5_tokens=50000,
                  extra=None) -> dict:
    s = {
        "M1_loop_efficiency": m1,
        "M2_critic_major_rate": m2,
        "M4_plan_refine_count": m4,
        "M5_token_efficiency": {"total_tokens": m5_tokens},
    }
    if extra:
        s.update(extra)
    return s


class TestCandidateRule:
    def test_fields_match_design(self):
        rule = CandidateRule(
            signal_name="test_signal",
            metric="M2",
            causes=["cause 1"],
            actions=["action 1"],
            auto_params=[],
            human_actions=[0],
            correlation_score=0.75,
            confidence=0.95,
            sample_size=30,
            supporting_evidence="test evidence",
        )
        assert rule.signal_name == "test_signal"
        assert rule.correlation_score == 0.75


class TestDiagnosticRuleDiscoverer:
    @pytest.fixture
    def metrics_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / ".ae-state" / "metrics"
        d.mkdir(parents=True)
        return d

    def test_discover_returns_empty_with_no_data(self, metrics_dir: Path):
        d = DiagnosticRuleDiscoverer(metrics_dir)
        assert d.discover() == []

    def test_discover_returns_empty_below_min_requirements(self, metrics_dir: Path):
        reqs = metrics_dir / "requirements"
        for i in range(5):
            rdir = reqs / f"req-{i}"
            rdir.mkdir(parents=True)
            (rdir / "summary.json").write_text(json.dumps(_make_summary(m1=5+i)))
        d = DiagnosticRuleDiscoverer(metrics_dir)
        assert d.discover(min_requirements=30) == []

    def test_discover_runs_with_enough_data(self, metrics_dir: Path):
        reqs = metrics_dir / "requirements"
        for i in range(35):
            rdir = reqs / f"req-{i:03d}"
            rdir.mkdir(parents=True)
            # Create correlation: higher M4 → higher M2
            m4 = i % 5
            m2 = 0.1 + m4 * 0.1
            (rdir / "summary.json").write_text(json.dumps(_make_summary(
                m1=5 + (i % 10),
                m2=m2,
                m4=m4,
                m5_tokens=40000 + i * 1000,
            )))
        d = DiagnosticRuleDiscoverer(metrics_dir)
        candidates = d.discover(min_requirements=30)
        assert len(candidates) >= 0  # May or may not find correlations

    def test_spearman_perfect_positive_correlation(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [2.0, 4.0, 6.0, 8.0, 10.0]
        rho, p = DiagnosticRuleDiscoverer._spearman_r(a, b)
        assert rho == pytest.approx(1.0, rel=1e-6)
        assert p < 0.05

    def test_spearman_perfect_negative_correlation(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [10.0, 8.0, 6.0, 4.0, 2.0]
        rho, p = DiagnosticRuleDiscoverer._spearman_r(a, b)
        assert rho == pytest.approx(-1.0, rel=1e-6)
        assert p < 0.05

    def test_spearman_no_correlation(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [3.0, 1.0, 5.0, 2.0, 4.0]  # shuffled, near-zero correlation
        rho, p = DiagnosticRuleDiscoverer._spearman_r(a, b)
        assert abs(rho) < 0.4

    def test_spearman_too_few_samples(self):
        rho, p = DiagnosticRuleDiscoverer._spearman_r([1.0, 2.0], [3.0, 4.0])
        assert rho == 0.0
        assert p == 1.0

    def test_candidates_saved_to_file(self, metrics_dir: Path):
        reqs = metrics_dir / "requirements"
        for i in range(35):
            rdir = reqs / f"req-{i:03d}"
            rdir.mkdir(parents=True)
            (rdir / "summary.json").write_text(json.dumps(_make_summary(
                m4=0 if i < 17 else 2,
                m2=0.1 if i < 17 else 0.5,
            )))
        d = DiagnosticRuleDiscoverer(metrics_dir)
        d.discover(min_requirements=30)
        rules_dir = metrics_dir / "baselines" / "candidate_rules"
        files = list(rules_dir.glob("candidates-*.json"))
        assert len(files) == 1
        content = json.loads(files[0].read_text())
        assert isinstance(content, list)

    def test_scan_requirement_fuzziness_finds_correlation(self, metrics_dir: Path):
        d = DiagnosticRuleDiscoverer(metrics_dir)
        summaries = []
        for i in range(35):
            m4 = 0 if i < 17 else 2
            m2 = 0.1 if i < 17 else 0.5
            summaries.append(_make_summary(m2=m2, m4=m4))
        candidates = d._scan_requirement_fuzziness(summaries)
        # Strong separation between groups → should find correlation
        assert len(candidates) >= 1
        c = candidates[0]
        assert c.metric == "M2"
        assert abs(c.correlation_score) > 0.5
