"""T68: RatchetController — keep/revert/stop + config versioning (F.6)."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_engineering.metrics.ratchet import RatchetController


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

    def test_get_current_config_returns_none_without_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            assert c.get_current_config() is None

    def test_rollback_rejects_non_mapping_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            (c._configs_dir / "ae-config-v1.json").write_text("[]")
            (c._configs_dir / "ae-config-v2.json").write_text("{}")
            assert c.rollback() is None

    def test_revert_config_requires_existing_snapshot_and_writes_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            assert c.revert_config("ae-config-v9") is False
            target = c._configs_dir / "ae-config-v2.json"
            target.write_text('{"mode": "safe"}')

            assert c.revert_config("ae-config-v2") is True
            assert c.get_current_config() == {"mode": "safe"}

    def test_save_config_snapshot_falls_back_when_git_tag_raises(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))

            def raise_os_error(*args, **kwargs):
                raise OSError("git unavailable")

            monkeypatch.setattr(
                "auto_engineering.metrics.ratchet.subprocess.run",
                raise_os_error,
            )
            result = c.save_config_snapshot({"mode": "fallback"})

            assert result is not None
            assert result.endswith("ae-config-v1.json")

    def test_merge_rule_appends_to_existing_rule_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = RatchetController(project_root=Path(tmp))
            rules_path = c._metrics_dir / "baselines" / "merged_rules.json"
            rules_path.parent.mkdir(parents=True)
            rules_path.write_text('[{"signal_name": "old"}]')
            rule = SimpleNamespace(
                signal_name="new",
                metric="M2",
                auto_params=["p"],
                causes=["cause"],
                actions=["action"],
                human_actions=["review"],
            )

            c._merge_rule(rule)

            loaded = json.loads(rules_path.read_text())
            assert [item["signal_name"] for item in loaded] == ["old", "new"]
            assert loaded[-1]["possible_causes"] == ["cause"]


def test_ratchet_evaluate_covers_optional_baselines_and_zero_values(
    tmp_path: Path, monkeypatch,
):
    controller = RatchetController(project_root=tmp_path)
    monkeypatch.setattr(controller, "_detect_current_version", lambda: 3)

    result = controller.evaluate(
        before={"both_zero": 0, "zero_up": 0, "zero_down": 0, "invalid": object()},
        after={"both_zero": 0, "zero_up": 2, "zero_down": -1, "invalid": 4},
        before_metrics={"fallback": 10, "missing": None},
        after_metrics={"fallback": 12, "missing": 3},
    )
    metrics = {item["name"]: item for item in result.metrics}

    assert result.config_version == "ae-config-v3"
    assert result.previous_version == "ae-config-v2"
    assert "both_zero" not in metrics
    assert metrics["zero_up"]["direction"] == "improved"
    assert metrics["zero_down"]["direction"] == "regressed"
    assert metrics["fallback"]["after"] == 12.0
    assert "missing" not in metrics


def test_ratchet_detect_version_skips_malformed_tags_and_falls_back(
    tmp_path: Path, monkeypatch,
):
    controller = RatchetController(project_root=tmp_path)

    monkeypatch.setattr(
        "auto_engineering.metrics.ratchet.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="ae-config-vbad\nae-config-v2\n"
        ),
    )
    assert controller._detect_current_version() == 2

    (controller._configs_dir / "ae-config-v1.json").write_text("{}")
    (controller._configs_dir / "ae-config-v2.json").write_text("{}")

    def raise_os_error(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(
        "auto_engineering.metrics.ratchet.subprocess.run", raise_os_error
    )
    assert controller._detect_current_version() == 2


def test_extract_numeric_handles_nested_missing_and_unsupported_values():
    assert RatchetController._extract_numeric({"efficiency_ratio": None}) is None
    assert RatchetController._extract_numeric({"total_tokens": 4}) == 4.0
    assert RatchetController._extract_numeric("not-a-number") is None
