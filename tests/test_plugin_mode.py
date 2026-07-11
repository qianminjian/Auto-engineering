"""utils/plugin_mode.py 测试 — prismscan Bug 4 修复核心 (2026-07-04).

覆盖 3 个函数:
    - detect_plugin_mode(): 4 级 fallback 检测 plugin mode
    - detect_plugin_mode_detail(): 同上 + 返回触发信号名
    - has_llm_credentials(): 检查 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN

覆盖范围:
    - 4 级 fallback 优先级 (CLAUDE_CODE > CLAUDE_CODE_ENTRYPOINT > ANTHROPIC_CLI > ANTHROPIC_AUTH_TOKEN)
    - 边界 (None / empty / mixed)
    - has_llm_credentials 双 key 检查
    - 与 prismscan Bug 4 修复一致性 (orchestrator/agent.run_agent/doctor 共用)
"""

from __future__ import annotations

import pytest


class TestDetectPluginMode:
    """detect_plugin_mode() 4 级 fallback 检测 plugin mode."""

    def test_returns_false_when_no_plugin_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无任何 plugin 信号 → False (CLI 调试模式)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert detect_plugin_mode() is False

    def test_claude_code_env_var_triggers_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE=1 → True (最高优先级)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.setenv("CLAUDE_CODE", "1")
        assert detect_plugin_mode() is True

    def test_claude_code_empty_string_does_not_trigger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE='' → False (空字符串视为未设, 防误判)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.setenv("CLAUDE_CODE", "")
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert detect_plugin_mode() is False

    def test_claude_code_entrypoint_triggers_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli → True (子进程入口信号, 优先级 1)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        assert detect_plugin_mode() is True

    def test_anthropic_cli_claude_substring_triggers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_CLI 含 'claude' 子串 → True (优先级 2)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.setenv("ANTHROPIC_CLI", "claude-cli-something")
        assert detect_plugin_mode() is True

    def test_anthropic_cli_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_CLI 大小写不敏感 ('CLAUDE' 也命中)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.setenv("ANTHROPIC_CLI", "CLAUDE-MIXED-CASE")
        assert detect_plugin_mode() is True

    def test_anthropic_cli_without_claude_substring(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_CLI 不含 'claude' → 不触发 (如 ANTHROPIC_CLI=openai-cli)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.setenv("ANTHROPIC_CLI", "openai-cli")
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert detect_plugin_mode() is False

    def test_anthropic_auth_token_triggers_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_AUTH_TOKEN 设置 → True (OAuth 注入信号, 优先级 3, 最低)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-test")
        assert detect_plugin_mode() is True

    def test_priority_claude_code_over_entrypoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE + CLAUDE_CODE_ENTRYPOINT 都设 → CLAUDE_CODE 优先 (本身不影响 True/False, 但 detail 返回 CLAUDE_CODE)."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode, detect_plugin_mode_detail

        monkeypatch.setenv("CLAUDE_CODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
        assert detect_plugin_mode() is True
        _, signal = detect_plugin_mode_detail()
        assert signal == "CLAUDE_CODE", "应返回最高优先级信号 CLAUDE_CODE"

    def test_priority_entrypoint_over_anthropic_cli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE_ENTRYPOINT + ANTHROPIC_CLI 都设 → ENTRYPOINT 优先."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
        monkeypatch.setenv("ANTHROPIC_CLI", "claude-something")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
        _, signal = detect_plugin_mode_detail()
        assert signal == "CLAUDE_CODE_ENTRYPOINT"

    def test_priority_anthropic_cli_over_auth_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_CLI + ANTHROPIC_AUTH_TOKEN 都设 → ANTHROPIC_CLI 优先."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.setenv("ANTHROPIC_CLI", "claude-cli")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
        _, signal = detect_plugin_mode_detail()
        assert signal == "ANTHROPIC_CLI (claude substring)"


class TestDetectPluginModeDetail:
    """detect_plugin_mode_detail() 返回触发信号名."""

    def test_returns_no_plugin_signal_when_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无信号 → (False, 'no plugin signal')."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        is_plugin, signal = detect_plugin_mode_detail()
        assert is_plugin is False
        assert signal == "no plugin signal"

    def test_returns_claude_code_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_CODE → (True, 'CLAUDE_CODE')."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

        monkeypatch.setenv("CLAUDE_CODE", "1")
        is_plugin, signal = detect_plugin_mode_detail()
        assert is_plugin is True
        assert signal == "CLAUDE_CODE"

    def test_returns_anthropic_cli_substring_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_CLI=claude-* → (True, 'ANTHROPIC_CLI (claude substring)')."""
        from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.setenv("ANTHROPIC_CLI", "claude-cli-v1")
        is_plugin, signal = detect_plugin_mode_detail()
        assert is_plugin is True
        assert "ANTHROPIC_CLI" in signal
        assert "claude substring" in signal


class TestHasLlmCredentials:
    """has_llm_credentials() 检查可用 LLM 凭据."""

    def test_returns_false_when_no_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无任何 key → False."""
        from auto_engineering.utils.plugin_mode import has_llm_credentials

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        assert has_llm_credentials() is False

    def test_returns_true_with_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_API_KEY=sk-test → True."""
        from auto_engineering.utils.plugin_mode import has_llm_credentials

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-12345")
        assert has_llm_credentials() is True

    def test_returns_true_with_auth_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ANTHROPIC_AUTH_TOKEN=token → True (OAuth)."""
        from auto_engineering.utils.plugin_mode import has_llm_credentials

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01-test")
        assert has_llm_credentials() is True

    def test_returns_true_with_both_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """两个 key 都设 → True (不冲突, 都视为有凭据)."""
        from auto_engineering.utils.plugin_mode import has_llm_credentials

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-ant-oat01")
        assert has_llm_credentials() is True

    def test_returns_false_with_empty_strings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空字符串 key → False (防御性)."""
        from auto_engineering.utils.plugin_mode import has_llm_credentials

        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "")
        assert has_llm_credentials() is False


class TestPluginModeIntegration:
    """plugin_mode 与项目内其他模块集成."""

    def test_cli_agent_uses_detect_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cli/agent.py run_agent 使用 detect_plugin_mode (不重复实现)."""

        # agent.run_agent 应该 import + 调用 detect_plugin_mode
        # (静态分析 + 运行时验证)
        import inspect

        from auto_engineering.cli import agent

        source = inspect.getsource(agent.run_agent)
        assert "detect_plugin_mode" in source, (
            "cli/agent.py:run_agent 必须用 detect_plugin_mode (防 prismscan Bug 4 退化)"
        )

    def test_orchestrator_uses_detect_plugin_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """orchestrator.__post_init__ 使用 detect_plugin_mode."""
        import inspect

        from auto_engineering.loop import orchestrator

        # 找 OrchestratorConfig dataclass 源
        source = inspect.getsource(orchestrator)
        assert "detect_plugin_mode" in source, (
            "loop/orchestrator.py:OrchestratorConfig 必须用 detect_plugin_mode"
        )

    def test_doctor_reports_plugin_mode_via_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """doctor._check_plugin_mode 使用 detect_plugin_mode_detail."""
        import inspect

        from auto_engineering.cli import doctor

        source = inspect.getsource(doctor)
        assert "detect_plugin_mode_detail" in source, (
            "cli/doctor.py 必须用 detect_plugin_mode_detail (显示具体触发信号)"
        )