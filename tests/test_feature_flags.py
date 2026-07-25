"""T114: FeatureManifest 单元测试.

Covers: FeatureFlag dataclass, FEATURE_MANIFEST completeness, get_feature_status,
feature check, manifest registration enforcement, dynamic RuntimeConfig scanning (AD4).
"""

import inspect
import re

import pytest

from auto_engineering.config.feature_flags import (
    FEATURE_MANIFEST,
    FeatureFlag,
    _count_requirements,
    check_feature,
    get_feature_status,
    list_categories,
)


def _ae_keys_from_runtime_config() -> set[str]:
    """AD4: Dynamically scan RuntimeConfig source for all AE_XXX env var accesses.

    Uses ``inspect.getsource`` to parse the RuntimeConfig class body, extracting
    every ``self.get("AE_XXX")`` and ``self.is_active("AE_XXX")`` key.  This
    replaces the hardcoded EXPECTED_KEYS set — when a developer adds a new
    ``self.get("AE_NEW_FLAG")`` property to RuntimeConfig, this test automatically
    picks it up.

    Returns:
        Set of AE_* env var key strings used by RuntimeConfig.
    """
    from auto_engineering.config import runtime_config
    source = inspect.getsource(runtime_config.RuntimeConfig)
    keys: set[str] = set()
    for match in re.finditer(
        r'self\.(?:get|is_active)\("([A-Z][A-Z_0-9]+)"',
        source,
    ):
        keys.add(match.group(1))
    return {k for k in keys if k.startswith("AE_")}


class TestFeatureFlag:
    def test_default_values(self):
        f = FeatureFlag("AE_TEST", "test feature", "debugging")
        assert f.key == "AE_TEST"
        assert f.description == "test feature"
        assert f.category == "debugging"
        assert f.agent_mode == "both"
        assert f.activation == "AE_TEST=1"
        assert f.default_active is False

    def test_agent_mode_standalone_only(self):
        f = FeatureFlag("AE_X", "standalone only", "provider",
                        agent_mode="standalone_only")
        assert f.agent_mode == "standalone_only"

    def test_activation_custom_text(self):
        f = FeatureFlag("AE_Y", "custom", "safety",
                        activation="AE_Y=1 + extra setup")
        assert f.activation == "AE_Y=1 + extra setup"


class TestFeatureManifestCompleteness:
    """AD4: Dynamic RuntimeConfig scanning — every AE_* key used in RuntimeConfig
    must be registered in FEATURE_MANIFEST.

    When a developer adds a new ``@property`` with ``self.get("AE_NEW_FLAG")`` to
    RuntimeConfig, this test automatically picks it up from the source code —
    no need to manually update EXPECTED_KEYS.
    """

    def test_all_runtime_config_keys_registered_in_manifest(self):
        """Each AE_* key accessed in RuntimeConfig must have a FeatureFlag entry.

        Only enforces the RuntimeConfig → FEATURE_MANIFEST direction.
        Extra entries in FEATURE_MANIFEST that aren't in RuntimeConfig may be
        legitimately used elsewhere (e.g. standalone_driver prefix scanning,
        AE_MODEL_ROLE/AE_PROVIDER_ROLE) — those are checked separately.
        """
        rt_keys = _ae_keys_from_runtime_config()
        manifest_keys = {f.key for f in FEATURE_MANIFEST}
        missing = rt_keys - manifest_keys
        assert not missing, (
            f"RuntimeConfig 使用了以下 AE_* key 但 FEATURE_MANIFEST 中未注册: {sorted(missing)}\n"
            f"  请在 auto_engineering/config/feature_flags.py 的 FEATURE_MANIFEST 中注册"
        )

    def test_feature_manifest_entries_have_usage_path(self):
        """FEATURE_MANIFEST 中每个条目应有明确的使用路径 (AD4).

        不阻断 CI — 仅报告无明确路径的条目供人工审查。
        部分 key（如 AE_MODEL_ROLE）通过 prefix scanning 使用，
        不在 RuntimeConfig 直接访问。
        """
        rt_keys = _ae_keys_from_runtime_config()
        manifest_keys = {f.key for f in FEATURE_MANIFEST}
        extra = manifest_keys - rt_keys
        # Keys known to be used via dynamic/prefix scanning outside RuntimeConfig
        _DYNAMIC_KEYS = {
            "AE_MODEL_ROLE",    # standalone_driver scans AE_MODEL_<ROLE>_UPPER
            "AE_PROVIDER_ROLE",  # standalone_driver scans AE_PROVIDER_<ROLE>_UPPER
        }
        unverified = extra - _DYNAMIC_KEYS
        if unverified:
            # Advisory only — don't fail CI.  Future work: scan all source files.
            import warnings
            warnings.warn(  # noqa: B028
                f"FEATURE_MANIFEST 中以下 key 未在 RuntimeConfig 直接访问，"
                f"且不在已知动态 key 列表中: {sorted(unverified)}.\n"
                f"  请确认它们仍在使用，或从 FEATURE_MANIFEST 中删除."
            )

    def test_no_duplicate_keys(self):
        keys = [f.key for f in FEATURE_MANIFEST]
        duplicates = {k for k in keys if keys.count(k) > 1}
        assert not duplicates, f"Duplicate keys in FEATURE_MANIFEST: {duplicates}"

    def test_all_have_category(self):
        for f in FEATURE_MANIFEST:
            assert f.category, f"Missing category for {f.key}"

    def test_all_have_description(self):
        for f in FEATURE_MANIFEST:
            assert f.description, f"Missing description for {f.key}"
            assert len(f.description) > 5, (
                f"Description too short for {f.key}: '{f.description}'")


class TestGetFeatureStatus:
    def test_active_when_env_var_set(self):
        env = {"AE_DEBUG": "1"}
        status = get_feature_status(env)
        assert status["AE_DEBUG"]["active"] is True

    def test_inactive_when_default_active_but_not_set(self):
        env: dict[str, str] = {}
        status = get_feature_status(env)
        # AE_PII_ENABLED is default_active=True but being absent means active
        ae_pii = status.get("AE_PII_ENABLED")
        if ae_pii:
            assert ae_pii["active"] is True

    def test_inactive_when_not_set_and_default_false(self):
        env: dict[str, str] = {}
        status = get_feature_status(env)
        assert status["AE_METRICS"]["active"] is False

    def test_otlp_inactive_when_not_configured(self):
        env: dict[str, str] = {}
        status = get_feature_status(env)
        assert status["AE_OTLP_ENDPOINT"]["active"] is False

    def test_returns_all_registered_keys(self):
        env: dict[str, str] = {}
        status = get_feature_status(env)
        manifest_keys = {f.key for f in FEATURE_MANIFEST}
        assert set(status.keys()) == manifest_keys

    def test_pii_disabled_disables_sub_flags(self):
        """AE_PII_ENABLED=0 should show sub-flags as inactive."""
        env = {"AE_PII_GUARDRAIL": "1", "AE_PII_ENABLED": "0"}
        status = get_feature_status(env)
        assert status["AE_PII_GUARDRAIL"]["active"] is False


class TestCheckFeature:
    def test_existing_key_returns_feature(self):
        f = check_feature("AE_METRICS")
        assert f.key == "AE_METRICS"

    def test_unknown_key_raises_keyerror(self):
        with pytest.raises(KeyError, match="NOT_A_REAL_KEY"):
            check_feature("NOT_A_REAL_KEY")


class TestListCategories:
    def test_returns_categories(self):
        cats = list_categories()
        assert isinstance(cats, list)
        assert "observability" in cats
        assert "safety" in cats


class TestCheckFeatureGuard:
    """AD4: check_feature() guard — 新增 env var 必须先注册 FEATURE_MANIFEST."""

    def test_known_key_returns_feature_flag(self):
        result = check_feature("AE_METRICS")
        assert isinstance(result, FeatureFlag)
        assert result.key == "AE_METRICS"
        assert result.category == "observability"

    def test_unknown_key_raises_keyerror_with_guidance(self):
        with pytest.raises(KeyError, match="Register it in"):
            check_feature("AE_NOT_REGISTERED")

    def test_all_manifest_keys_pass_guard(self):
        """每个 FEATURE_MANIFEST 中注册的 key 都能通过 check_feature."""
        for f in FEATURE_MANIFEST:
            result = check_feature(f.key)
            assert result.key == f.key


class TestCountRequirements:
    """AD3: _count_requirements — 度量需求计数可见性."""

    def test_returns_none_when_metrics_dir_missing(self, tmp_path):
        """metrics 目录不存在时返回 None."""
        result = _count_requirements(tmp_path)
        assert result is None

    def test_counts_dirs_with_summary_json(self, tmp_path):
        """正确计数含 summary.json 的需求子目录."""
        reqs_dir = tmp_path / ".ae-state" / "metrics" / "requirements"
        # Create 3 requirements with summary.json
        for i in range(3):
            req_dir = reqs_dir / f"req-{i}"
            req_dir.mkdir(parents=True)
            (req_dir / "summary.json").write_text("{}")
        # Create 1 dir without summary.json (shouldn't count)
        (reqs_dir / "incomplete").mkdir(parents=True)

        result = _count_requirements(tmp_path)
        assert result == 3

    def test_returns_none_when_requirements_dir_missing(self, tmp_path):
        """metrics 目录存在但 requirements 子目录不存在时返回 None."""
        metrics_dir = tmp_path / ".ae-state" / "metrics"
        metrics_dir.mkdir(parents=True)
        result = _count_requirements(tmp_path)
        assert result is None
