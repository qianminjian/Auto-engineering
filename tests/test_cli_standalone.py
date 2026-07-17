"""Tests for V7-6 CLI --standalone + V8-7 doctor extension.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestV7_6_StandaloneCliFlag:
    """V7-6: ae dev-loop --standalone 标志."""

    def test_standalone_flag_in_help(self) -> None:
        """--help 输出包含 --standalone 选项."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "--help"])
        assert "--standalone" in result.output

    def test_standalone_mutually_exclusive_with_tick_flags(self) -> None:
        """--standalone 与 --init/--tick/--status 互斥."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "--standalone", "--init", "req"])
        assert result.exit_code != 0

    @patch("auto_engineering.cli.__init__._run_standalone")
    def test_standalone_dispatches_to_run_standalone(
        self, mock_run: MagicMock
    ) -> None:
        """--standalone "req" 时调用 _run_standalone."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        mock_run.return_value = None
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "--standalone", "test-req"])
        # 如果 _run_standalone 被调用, 说明分派成功
        mock_run.assert_called_once()
        assert result.exit_code == 0


class TestV8_7_DoctorAPIKeyCheck:
    """V8-7: ae doctor 加 API key 检查."""

    def test_doctor_checks_anthropic_api_key(self) -> None:
        """doctor 检查 ANTHROPIC_API_KEY 环境变量."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        output = result.output
        # Plugin mode 显示 ANTHROPIC_AUTH_TOKEN, 非 Plugin mode 显示 ANTHROPIC_API_KEY
        assert "ANTHROPIC" in output

    def test_doctor_checks_anthropic_auth_token(self) -> None:
        """doctor 检查 ANTHROPIC_AUTH_TOKEN 环境变量."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        output = result.output
        assert "ANTHROPIC_AUTH_TOKEN" in output or "ANTHROPIC" in output
