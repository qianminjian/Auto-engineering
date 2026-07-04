"""Tests for config/settings.py — v3.0 §八 8.1 完整 Settings dataclass.

覆盖:
    - Settings.from_env() 从环境变量加载 (除 ANTHROPIC_API_KEY)
    - 所有字段默认值
    - 环境变量覆盖默认值

2026-07-04 修复 (v5.0 深度审计): ANTHROPIC_API_KEY 不在 Settings
(settings.py:11-14 明确说明), 由 Anthropic SDK 自动从 env 读.
原测试期望 Settings 含 anthropic_api_key 字段 + from_env 读 key,
与设计文档不符. 重写测试以符合设计.
"""

from __future__ import annotations

import pytest

from auto_engineering.config.settings import Settings


class TestSettingsFromEnv:
    """Settings.from_env() 类方法 (不读 ANTHROPIC_API_KEY, SDK 自动读)."""

    def test_from_env_loads_anthropic_model(self, monkeypatch):
        """ANTHROPIC_MODEL 环境变量覆盖默认模型."""
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")
        s = Settings.from_env()
        assert s.anthropic_model == "claude-opus-4-6"

    def test_from_env_loads_max_steps(self, monkeypatch):
        """AE_MAX_STEPS 环境变量覆盖默认 max_steps."""
        monkeypatch.setenv("AE_MAX_STEPS", "25")
        s = Settings.from_env()
        assert s.max_steps == 25

    def test_from_env_loads_max_tool_calls(self, monkeypatch):
        """AE_MAX_TOOL_CALLS 环境变量覆盖默认 max_tool_calls."""
        monkeypatch.setenv("AE_MAX_TOOL_CALLS", "20")
        s = Settings.from_env()
        assert s.max_tool_calls == 20

    def test_from_env_loads_retry_max_attempts(self, monkeypatch):
        """AE_RETRY_MAX_ATTEMPTS 环境变量覆盖默认 retry_max_attempts."""
        monkeypatch.setenv("AE_RETRY_MAX_ATTEMPTS", "5")
        s = Settings.from_env()
        assert s.retry_max_attempts == 5

    def test_from_env_loads_retry_timeout(self, monkeypatch):
        """AE_RETRY_TIMEOUT 环境变量覆盖默认 retry_timeout (浮点数)."""
        monkeypatch.setenv("AE_RETRY_TIMEOUT", "60.5")
        s = Settings.from_env()
        assert s.retry_timeout == 60.5

    def test_from_env_loads_checkpoint_dir(self, monkeypatch):
        """AE_CHECKPOINT_DIR 环境变量覆盖默认 checkpoint_dir."""
        monkeypatch.setenv("AE_CHECKPOINT_DIR", "/tmp/custom-checkpoints")
        s = Settings.from_env()
        assert s.checkpoint_dir == "/tmp/custom-checkpoints"

    def test_from_env_does_not_load_anthropic_api_key(self):
        """ANTHROPIC_API_KEY 不在 Settings (由 SDK 自动从 env 读).

        2026-07-04 修复: 显式验证 Settings 无 anthropic_api_key 字段.
        SDK 在实际 LLM 调用时自动从 env 读, 不依赖 Settings 中转.
        """
        s = Settings.from_env()
        assert not hasattr(s, "anthropic_api_key"), (
            "Settings 不应含 anthropic_api_key 字段 "
            "(SDK 自动从 env 读, 见 settings.py:11-14)"
        )


class TestSettingsDefaults:
    """Settings 默认值."""

    def test_default_model(self):
        """默认 anthropic_model 是 claude-sonnet-4-6."""
        s = Settings()
        assert s.anthropic_model == "claude-sonnet-4-6"

    def test_default_checkpoint_dir(self):
        """默认 checkpoint_dir 是 .ae-state (修复: 原测试期望 .ae-checkpoints 错)."""
        s = Settings()
        assert s.checkpoint_dir == ".ae-state"

    def test_default_max_steps(self):
        """默认 max_steps 是 50 (修复: 原测试期望 10 错)."""
        s = Settings()
        assert s.max_steps == 50

    def test_default_max_tool_calls(self):
        """默认 max_tool_calls 是 10."""
        s = Settings()
        assert s.max_tool_calls == 10

    def test_default_retry_max_attempts(self):
        """默认 retry_max_attempts 是 3."""
        s = Settings()
        assert s.retry_max_attempts == 3

    def test_default_retry_timeout(self):
        """默认 retry_timeout 是 120.0."""
        s = Settings()
        assert s.retry_timeout == 120.0


class TestSettingsFields:
    """Settings 字段完整性 (v3.0 §八 8.1)."""

    def test_has_all_required_fields(self):
        """Settings 必须有 v3.0 §八 8.1 列出的全部字段 (除 anthropic_api_key).

        2026-07-04 修复: anthropic_api_key 不在 Settings (见 settings.py:11-14).
        """
        s = Settings()
        assert hasattr(s, "anthropic_model")
        assert hasattr(s, "checkpoint_dir")
        assert hasattr(s, "max_steps")
        assert hasattr(s, "max_tool_calls")
        assert hasattr(s, "retry_max_attempts")
        assert hasattr(s, "retry_timeout")
        assert not hasattr(s, "anthropic_api_key")
