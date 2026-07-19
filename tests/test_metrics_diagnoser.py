"""T67: Diagnoser — 5 diagnostic rules with human_actions (F.5-aligned)."""
import pytest

from auto_engineering.metrics.signals import Signal


# We test the Diagnoser in isolation — import after creation
class TestDiagnoser:
    """Diagnoser rule engine — maps signals to diagnoses."""

    @pytest.fixture
    def diagnoser(self):
        from auto_engineering.metrics.diagnoser import Diagnoser
        return Diagnoser()

    def test_maps_critic_major_increasing_to_rule(self, diagnoser):
        signal = Signal(
            name="critic_major_increasing",
            severity="WARN",
            metric="M2_critic_major_rate",
            value=0.8,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is not None
        assert diagnosis.signal_name == "critic_major_increasing"
        assert len(diagnosis.possible_causes) > 0
        assert len(diagnosis.suggested_actions) > 0
        assert len(diagnosis.needs_human) >= 0
        assert isinstance(diagnosis.auto_adjustable, list)

    def test_maps_token_efficiency_drop_to_rule(self, diagnoser):
        signal = Signal(
            name="token_efficiency_drop",
            severity="WARN",
            metric="M5_token_efficiency",
            value=300000,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is not None
        assert any("context" in c.lower() or "token" in c.lower()
                   for c in diagnosis.possible_causes)
        assert "token_budget_warning" in diagnosis.auto_adjustable

    def test_maps_plan_refine_spike_to_rule(self, diagnoser):
        signal = Signal(
            name="plan_refine_spike",
            severity="WARN",
            metric="M4_plan_refine_count",
            value=5.0,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is not None
        assert diagnosis.signal_name == "plan_refine_spike"
        assert "max_refine_per_source" in diagnosis.auto_adjustable

    def test_maps_slow_convergence_to_rule(self, diagnoser):
        signal = Signal(
            name="slow_convergence",
            severity="CRITICAL",
            metric="M1_loop_efficiency",
            value=25.0,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is not None
        assert diagnosis.signal_name == "slow_convergence"
        assert "max_iter" in diagnosis.auto_adjustable

    def test_maps_verification_always_leaf_to_rule(self, diagnoser):
        signal = Signal(
            name="verification_always_leaf",
            severity="INFO",
            metric="M3_verification_trigger_rate",
            value=0.0,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is not None
        assert diagnosis.signal_name == "verification_always_leaf"
        assert len(diagnosis.auto_adjustable) == 0  # no auto params

    def test_unknown_signal_returns_none(self, diagnoser):
        signal = Signal(
            name="nonexistent_signal",
            severity="INFO",
            metric="M1_loop_efficiency",
            value=0,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis is None

    def test_diagnosis_contains_severity(self, diagnoser):
        signal = Signal(
            name="critic_major_increasing",
            severity="CRITICAL",
            metric="M2_critic_major_rate",
            value=0.9,
        )
        diagnosis = diagnoser.diagnose(signal)
        assert diagnosis.severity == "CRITICAL"

    def test_all_5_rules_exist(self, diagnoser):
        """Design spec: 5 diagnostic rules total (F.5)."""
        assert len(diagnoser._rules) == 5
        expected_signals = {
            "critic_major_increasing",
            "plan_refine_spike",
            "slow_convergence",
            "token_efficiency_drop",
            "verification_always_leaf",
        }
        assert set(diagnoser._rules.keys()) == expected_signals

    def test_auto_adjustable_present_on_all_rules(self, diagnoser):
        """Every rule must have auto_params key (even if empty)."""
        for signal_name, rule in diagnoser._rules.items():
            assert "auto_params" in rule, (
                f"Rule '{signal_name}' missing auto_params key"
            )
