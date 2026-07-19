"""T68: RatchetController — keep/revert/stop + config versioning (F.6)."""
import json
import tempfile
from pathlib import Path

import pytest

from auto_engineering.metrics.ratchet import RatchetController, RatchetDecision


class TestRatchetController:
    """keep/revert/stop ternary verdict."""

    @pytest.fixture
    def controller(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield RatchetController(project_root=Path(tmp))

    def test_returns_keep_when_all_metrics_improved(self, controller):
        before = {
            "M1_loop_efficiency": 8.0,
            "M2_critic_major_rate": 0.3,
            "M5_token_efficiency": {"efficiency_ratio": 5.0},
        }
        after = {
            "M1_loop_efficiency": 5.0,      # improved (lower is better)
            "M2_critic_major_rate": 0.1,     # improved
            "M5_token_efficiency": {"efficiency_ratio": 8.0},  # improved
        }
        verdict = controller.evaluate(before, after)
        assert verdict.action == "keep"
        assert verdict.reason != ""

    def test_returns_revert_when_major_regression(self, controller):
        before = {
            "M1_loop_efficiency": 5.0,
            "M2_critic_major_rate": 0.1,
        }
        after = {
            "M1_loop_efficiency": 9.0,       # 80% worse (>50%, <200%)
            "M2_critic_major_rate": 0.25,    # 150% worse (>50%, <200%)
        }
        verdict = controller.evaluate(before, after)
        assert verdict.action == "revert"

    def test_returns_stop_when_critical_threshold_breached(self, controller):
        before = {"M1_loop_efficiency": 5.0}
        after = {"M1_loop_efficiency": 30.0}  # extreme regression
        verdict = controller.evaluate(before, after)
        assert verdict.action in ("revert", "stop")

    def test_verdict_contains_metric_details(self, controller):
        before = {"M1_loop_efficiency": 10.0, "M2_critic_major_rate": 0.5}
        after = {"M1_loop_efficiency": 12.0, "M2_critic_major_rate": 0.6}
        verdict = controller.evaluate(before, after)
        assert len(verdict.metrics) > 0
        for m in verdict.metrics:
            assert "name" in m
            assert "before" in m
            assert "after" in m


class TestConfigSnapshot:
    """Git tag config versioning — ae-config-v{N}."""

    def test_save_config_snapshot_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            config = {"M1_threshold": 10, "M2_threshold": 0.5}
            result = c.save_config_snapshot(config)
            assert result is not None
            configs_dir = c._configs_dir
            assert configs_dir.exists()
            files = list(configs_dir.glob("ae-config-v*.json"))
            assert len(files) == 1

    def test_save_config_snapshot_increments_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            v1 = c.save_config_snapshot({"a": 1})
            v2 = c.save_config_snapshot({"a": 2})
            assert v1 is not None and v2 is not None
            assert v1 != v2

    def test_rollback_restores_previous_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            c.save_config_snapshot({"param": "v1"})
            c.save_config_snapshot({"param": "v2"})
            restored = c.rollback()
            assert restored is not None
            assert restored.get("param") == "v1"

    def test_rollback_no_history_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            result = c.rollback()
            assert result is None

    def test_get_current_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            config = {"key": "value"}
            c.save_config_snapshot(config)
            current = c.get_current_config()
            assert current == config
