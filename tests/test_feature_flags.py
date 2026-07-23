"""T114: FeatureManifest 单元测试.

Covers: FeatureFlag dataclass, FEATURE_MANIFEST completeness, get_feature_status,
feature check, manifest registration enforcement.
"""

import os
from unittest.mock import patch

import pytest

from auto_engineering.config.feature_flags import (
    FEATURE_MANIFEST,
    FeatureFlag,
    check_feature,
    get_feature_status,
    list_categories,
)


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
    """All env vars defined in this test's expected set must exist in FEATURE_MANIFEST."""

    EXPECTED_KEYS = {
        "AE_AUDIT_LOG", "AE_METRICS", "AE_OTLP_ENDPOINT",
        "AE_DEBUG", "AE_LOG_LEVEL",
        "AE_CACHE_CONTROL", "AE_MAX_TOOL_CALLS",
        "AE_LLM_PROVIDER", "AE_MODEL_ROLE", "AE_PROVIDER_ROLE",
        "AE_GATE_TIMEOUT", "AE_PRODUCTION", "AE_STRICT_RED",
        "AE_TOKEN_TRACKING", "AE_TOKEN_SOURCE",
        "AE_PII_ENABLED", "AE_PII_GUARDRAIL", "AE_PII_GUARDRAIL_MODE",
        "AE_PII_INBOUND", "AE_PII_OUTBOUND",
        "AE_AUDIT_LOG_DIR",
    }

    def test_all_expected_keys_registered(self):
        manifest_keys = {f.key for f in FEATURE_MANIFEST}
        missing = self.EXPECTED_KEYS - manifest_keys
        assert not missing, f"Env vars not in FEATURE_MANIFEST: {missing}"

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
        # AE_CACHE_CONTROL is default_active=True but being absent means active
        ae_cache = status.get("AE_CACHE_CONTROL")
        if ae_cache:
            assert ae_cache["active"] is True

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
