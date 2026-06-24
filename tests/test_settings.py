"""Tests for config/settings.py — v3.0 §八 8.1 完整 Settings dataclass.

覆盖:
    - Settings.from_env() 从环境变量加载
    - 缺 ANTHROPIC_API_KEY 时抛 CONFIG_MISSING_API_KEY
    - 所有字段默认值
    - 环境变量覆盖默认值
"""

from __future__ import annotations

import pytest

from auto_engineering.config.settings import Settings
from auto_engineering.errors import AEError, ErrorCode


class TestSettingsFromEnv:
    """Settings.from_env() 类方法."""

    def test_from_env_loads_anthropic_api_key(self, monkeypatch):
        """RED: Settings.from_env() 必须从环境变量加载 ANTHROPIC_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-12345")
        s = Settings.from_env()
        assert s.anthropic_api_key == "sk-test-key-12345"

    def test_from_env_raises_when_api_key_missing(self, monkeypatch):
        """RED: 缺 ANTHROPIC_API_KEY 时抛 AEError(CONFIG_MISSING_API_KEY)."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(AEError) as exc_info:
            Settings.from_env()
        assert exc_info.value.code == ErrorCode.CONFIG_MISSING_API_KEY

    def test_from_env_custom_anthropic_model(self, monkeypatch):
        """RED: ANTHROPIC_MODEL 环境变量覆盖默认模型."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")
        s = Settings.from_env()
        assert s.anthropic_model == "claude-opus-4-6"

    def test_from_env_custom_max_steps(self, monkeypatch):
        """RED: AE_MAX_STEPS 环境变量覆盖默认 max_steps."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("AE_MAX_STEPS", "25")
        s = Settings.from_env()
        assert s.max_steps == 25

    def test_from_env_custom_max_tool_calls(self, monkeypatch):
        """RED: AE_MAX_TOOL_CALLS 环境变量覆盖默认 max_tool_calls."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("AE_MAX_TOOL_CALLS", "20")
        s = Settings.from_env()
        assert s.max_tool_calls == 20

    def test_from_env_custom_retry_max_attempts(self, monkeypatch):
        """RED: AE_RETRY_MAX_ATTEMPTS 环境变量覆盖默认 retry_max_attempts."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("AE_RETRY_MAX_ATTEMPTS", "5")
        s = Settings.from_env()
        assert s.retry_max_attempts == 5

    def test_from_env_custom_retry_timeout(self, monkeypatch):
        """RED: AE_RETRY_TIMEOUT 环境变量覆盖默认 retry_timeout (浮点数)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("AE_RETRY_TIMEOUT", "60.5")
        s = Settings.from_env()
        assert s.retry_timeout == 60.5

    def test_from_env_custom_checkpoint_dir(self, monkeypatch):
        """RED: AE_CHECKPOINT_DIR 环境变量覆盖默认 checkpoint_dir."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("AE_CHECKPOINT_DIR", "/tmp/custom-checkpoints")
        s = Settings.from_env()
        assert s.checkpoint_dir == "/tmp/custom-checkpoints"


class TestSettingsDefaults:
    """Settings 默认值."""

    def test_default_model(self):
        """默认 anthropic_model 是 claude-sonnet-4-6."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.anthropic_model == "claude-sonnet-4-6"

    def test_default_checkpoint_dir(self):
        """默认 checkpoint_dir 是 .ae-checkpoints."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.checkpoint_dir == ".ae-checkpoints"

    def test_default_max_steps(self):
        """默认 max_steps 是 10."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.max_steps == 10

    def test_default_max_tool_calls(self):
        """默认 max_tool_calls 是 10."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.max_tool_calls == 10

    def test_default_retry_max_attempts(self):
        """默认 retry_max_attempts 是 3."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.retry_max_attempts == 3

    def test_default_retry_timeout(self):
        """默认 retry_timeout 是 120.0."""
        s = Settings(anthropic_api_key="sk-test")
        assert s.retry_timeout == 120.0


class TestSettingsFields:
    """Settings 字段完整性 (v3.0 §八 8.1)."""

    def test_has_all_required_fields(self):
        """Settings 必须有 v3.0 §八 8.1 列出的全部字段."""
        s = Settings(anthropic_api_key="sk-test")
        assert hasattr(s, "anthropic_api_key")
        assert hasattr(s, "anthropic_model")
        assert hasattr(s, "checkpoint_dir")
        assert hasattr(s, "max_steps")
        assert hasattr(s, "max_tool_calls")
        assert hasattr(s, "retry_max_attempts")
        assert hasattr(s, "retry_timeout")
