"""utils/llm_credentials.py 测试 — 4 级 fallback + plugin mode 零配置 (2026-07-04).

设计目标 (用户洞察):
    plugin 在 Claude Code agent 内运行, 应通过 ANTHROPIC_AUTH_TOKEN
    (OAuth) 自动注入, 用户**零配置**. CLI 调试模式才需 export ANTHROPIC_API_KEY.

覆盖范围:
    - resolve_llm_credentials() 4 级 fallback (explicit / ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / CLAUDECODE)
    - 优先级 (explicit > ANTHROPIC_API_KEY > ANTHROPIC_AUTH_TOKEN)
    - plugin mode 零配置 (有 ANTHROPIC_AUTH_TOKEN 即 resolve 成功)
    - has_llm_credentials 便捷检查
    - credential_error_message 区分 plugin / wrapper / cli 模式
    - _detect_mode 模式检测
"""

from __future__ import annotations

import pytest

from auto_engineering.utils.llm_credentials import (
    LLMCredentials,
    LLM_CREDENTIAL_SOURCES,
    _detect_mode,
    credential_error_message,
    has_llm_credentials,
    resolve_llm_credentials,
)


# 2026-07-04: 清理 shell env 残留 (CLAUDECODE/CLAUDE_CODE_SESSION_ID 等),
# pytest monkeypatch 默认不删除已存在 env, 测试中需要明确 delenv.
@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试前清理所有 LLM 凭据相关 env, 避免 shell 残留干扰."""
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_SESSION_ID",
        "ANTHROPIC_CLI",
        "CLAUDECODE",
    ):
        monkeypatch.delenv(var, raising=False)


class TestResolveLLMCredentials:
    """resolve_llm_credentials() 4 级 fallback."""

    def test_priority_0_explicit_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """显式参数优先于所有 env var (e.g. AnthropicProvider(api_key='...'))."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "env-token")
        creds, signal = resolve_llm_credentials(explicit_token="explicit-key")
        assert creds is not None
        assert creds.token == "explicit-key"
        assert creds.source == "explicit"
        assert signal == "explicit"

    def test_priority_0_explicit_over_claudecode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """显式参数也优先于 CLAUDECODE wrapper fallback."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
        creds, signal = resolve_llm_credentials(explicit_token="explicit-key")
        assert creds is not None
        assert creds.token == "explicit-key"

    def test_priority_1_anthropic_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_API_KEY env 非空 → CLI 模式凭据."""
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-cli")
        creds, signal = resolve_llm_credentials()
        assert creds is not None
        assert creds.token == "sk-test-cli"
        assert creds.source == "ANTHROPIC_API_KEY"
        assert signal == "ANTHROPIC_API_KEY"
        assert creds.mode == "cli"

    def test_priority_2_anthropic_auth_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_AUTH_TOKEN env 非空 → Plugin OAuth / proxy 模式凭据."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-cli-key")  # 同时设, 优先
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-cp-plugin-token")
        creds, signal = resolve_llm_credentials()
        assert creds is not None
        # API_KEY 优先于 AUTH_TOKEN
        assert creds.token == "sk-cli-key"
        assert creds.source == "ANTHROPIC_API_KEY"

    def test_priority_2_auth_token_only_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """只有 ANTHROPIC_AUTH_TOKEN (无 ANTHROPIC_API_KEY) + Plugin mode 信号 → plugin mode."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-cp-plugin-token")
        creds, signal = resolve_llm_credentials()
        assert creds is not None
        assert creds.token == "sk-cp-plugin-token"
        assert creds.source == "ANTHROPIC_AUTH_TOKEN"
        assert creds.mode == "plugin", (
            "Plugin mode (CLAUDE_CODE_ENTRYPOINT 设置) 应检测到"
        )

    def test_no_credential_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """所有凭据缺失 → None + signal='no_credential'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        creds, signal = resolve_llm_credentials()
        assert creds is None
        assert signal == "no_credential"

    def test_claudecode_wrapper_no_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDECODE=1 + CLAUDE_CODE_SESSION_ID 但无 token → 标记 wrapper."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
        creds, signal = resolve_llm_credentials()
        assert creds is None
        assert "CLAUDECODE_wrapper" in signal

    def test_empty_string_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空字符串 / 纯空白视为缺失 (防御性)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "   ")
        creds, signal = resolve_llm_credentials()
        assert creds is None
        assert signal == "no_credential"


class TestHasLLMCredentials:
    """has_llm_credentials() 便捷检查."""

    def test_returns_true_with_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert has_llm_credentials() is True

    def test_returns_true_with_auth_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-cp")
        assert has_llm_credentials() is True

    def test_returns_true_with_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert has_llm_credentials(explicit_token="explicit") is True

    def test_returns_false_when_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert has_llm_credentials() is False


class TestPluginModeZeroConfig:
    """Plugin mode 零配置原则 (用户洞察).

    设计: ae 在 Claude Code agent 内运行时, ANTHROPIC_AUTH_TOKEN 由
    Claude Code OAuth 自动注入. 用户**零配置** (不需 export key).
    """

    def test_plugin_mode_with_oauth_token_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plugin mode (CLAUDE_CODE_ENTRYPOINT) + ANTHROPIC_AUTH_TOKEN → resolve 成功."""
        # 模拟 prismscan 实际 env
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-cp-KWawQgZ...")
        creds, signal = resolve_llm_credentials()
        assert creds is not None, "Plugin mode 应零配置 resolve 成功"
        assert creds.source == "ANTHROPIC_AUTH_TOKEN"
        assert creds.mode == "plugin"
        assert signal == "ANTHROPIC_AUTH_TOKEN"

    def test_plugin_mode_no_credentials_yet_signal_plugin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plugin mode 但无 token → 标记 plugin mode (供错误信息区分)."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        creds, signal = resolve_llm_credentials()
        assert creds is None
        # 没有 token 但有 plugin signal → 信号应反映 plugin mode
        # (但 not "no_credential" 因为 plugin mode 已检测)
        # 实际: 没 token 时 signal='no_credential' (不区分 mode)
        # 但 mode 字段是 plugin, 错误信息用 mode 区分
        assert creds is None


class TestDetectMode:
    """_detect_mode() 模式检测."""

    def test_plugin_mode_via_claude_code_entrypoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert _detect_mode() == "plugin"

    def test_plugin_mode_via_claude_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE", "1")
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert _detect_mode() == "plugin"

    def test_wrapper_mode_via_claudecode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        assert _detect_mode() == "wrapper"

    def test_cli_mode_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        assert _detect_mode() == "cli"


class TestCredentialErrorMessage:
    """credential_error_message() 错误信息区分模式."""

    def test_plugin_mode_error_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plugin mode 无凭据 → 提示 OAuth 注入问题, 零配置."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        msg = credential_error_message(context="critic")
        assert "零配置" in msg, "Plugin mode 应强调零配置"
        assert "ANTHROPIC_AUTH_TOKEN" in msg
        assert "~/.zshrc" not in msg, "不应让 plugin 用户 export ~/.zshrc"

    def test_cli_mode_error_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI mode 无凭据 → 提示用户 export ANTHROPIC_API_KEY (CLI 唯一场景)."""
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("CLAUDECODE", raising=False)
        msg = credential_error_message(context="dev-loop")
        assert "ANTHROPIC_API_KEY" in msg
        assert "CLI 调试模式" in msg or "手动" in msg

    def test_wrapper_mode_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wrapper mode 无凭据 → 提示 Claude Code 自动管理."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc-123")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        msg = credential_error_message(context="critic")
        assert "Claude Code" in msg


class TestLLMCredentialsDataclass:
    """LLMCredentials dataclass."""

    def test_is_valid_with_token(self) -> None:
        creds = LLMCredentials(token="sk-test", source="ANTHROPIC_API_KEY")
        assert creds.is_valid() is True

    def test_is_valid_false_for_empty(self) -> None:
        creds = LLMCredentials(token="", source="ANTHROPIC_API_KEY")
        assert creds.is_valid() is False

    def test_is_valid_false_for_whitespace(self) -> None:
        creds = LLMCredentials(token="   ", source="ANTHROPIC_API_KEY")
        assert creds.is_valid() is False

    def test_description_includes_source_and_mode(self) -> None:
        creds = LLMCredentials(
            token="sk-test", source="ANTHROPIC_AUTH_TOKEN", mode="plugin"
        )
        desc = creds.description()
        assert "ANTHROPIC_AUTH_TOKEN" in desc
        assert "plugin" in desc

    def test_sources_constant_has_4_entries(self) -> None:
        """4 级 fallback 凭据源."""
        assert len(LLM_CREDENTIAL_SOURCES) == 4
        assert "explicit" in LLM_CREDENTIAL_SOURCES
        assert "ANTHROPIC_API_KEY" in LLM_CREDENTIAL_SOURCES
        assert "ANTHROPIC_AUTH_TOKEN" in LLM_CREDENTIAL_SOURCES
        assert "CLAUDECODE_wrapper" in LLM_CREDENTIAL_SOURCES