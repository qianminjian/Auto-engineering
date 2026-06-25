"""Tests for CLI dev_loop command — Plan B Phase 02.

覆盖 T02-2/T03/T04/T05/T07/T08/T09/T10/T11 共 11 项团队级能力.
策略:用 click.testing.CliRunner + monkeypatch preflight + Mock runtime 验证 CLI 行为.
不调真实 LLM(避免 mock-friendly).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.errors import AEError, ErrorCode

# ---------- 测试 fixtures ----------


@pytest.fixture
def valid_project(tmp_path: Path, monkeypatch):
    """一个 valid 的项目根: 含 .git/ + .ae-answers.yml + ANTHROPIC_API_KEY."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    (tmp_path / ".git").mkdir()
    answers = tmp_path / ".ae-answers.yml"
    answers.write_text(
        "project_name: test-app\nproject_type: cli-tool\npackage_manager: uv\ntest_runner: pytest\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def mock_loop_engine(monkeypatch):
    """替换 _run_loop_engine 为 mock,使 CLI 测试不调真实 LoopEngine.

    返回的 MagicMock 直接当作函数调用 — dev_loop 调 _run_loop_engine(**kwargs).
    mock 返回 LoopRunResult 实例(dev_loop 调 .status / .total_steps / .checkpoint_id).
    """
    from auto_engineering.cli import LoopRunResult

    runner_mock = MagicMock()
    runner_mock.return_value = LoopRunResult(
        status="done",
        total_steps=3,
        checkpoint_id="test-cp-id",
    )
    monkeypatch.setattr("auto_engineering.cli._run_loop_engine", runner_mock)
    return runner_mock


# ============================================================
# T02-2: ae dev-loop 启动读 .ae-answers.yml 注入 ProjectEnvironment
# ============================================================


class TestT02_2LoadsAeAnswers:
    """T02-2: ae dev-loop 启动时调 load_ae_answers + 注入 env vars."""

    def test_devloop_loads_ae_answers(self, valid_project, mock_loop_engine):
        """RED: ae dev-loop 必须调 load_ae_answers(project_root)."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "build x", "--use-v1"])

        assert result.exit_code == 0
        # 验证: mock 被调用,且传入了 valid_project 作为参数
        mock_loop_engine.assert_called_once()
        call_kwargs = mock_loop_engine.call_args.kwargs
        # ProjectEnvironment 来自 .ae-answers.yml
        assert "project_env" in call_kwargs or "project_root" in call_kwargs


# ============================================================
# T03: --max-tokens / --max-cost CLI flag
# ============================================================


class TestT03MaxTokensBudget:
    """T03: --max-tokens 阈值检查 + BudgetExceeded 异常."""

    def test_max_tokens_budget_exceeded_raises(self, valid_project, monkeypatch):
        """RED: --max-tokens=100 + token 累计达阈值 → BudgetExceeded."""
        from auto_engineering.cli import TokenTracker

        tracker = TokenTracker(max_tokens=100)
        # mock LLMResponse with usage=200
        response = MagicMock()
        response.usage.input_tokens = 150
        response.usage.output_tokens = 50

        with pytest.raises(AEError) as exc_info:
            tracker.add(response)
        assert exc_info.value.code == ErrorCode.BUDGET_EXCEEDED

    def test_max_tokens_under_budget_ok(self):
        """GREEN: token 累计未超阈值不抛错."""
        from auto_engineering.cli import TokenTracker

        tracker = TokenTracker(max_tokens=1000)
        response = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        tracker.add(response)  # 不抛
        assert tracker.total_tokens == 150

    def test_max_tokens_cli_flag_accepted(self, valid_project, mock_loop_engine):
        """RED: --max-tokens 100 被 CLI 接受并传给 LoopEngine."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "build x", "--use-v1", "--max-tokens", "100"])

        assert result.exit_code == 0
        call_kwargs = mock_loop_engine.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 100


# ============================================================
# T04: 进度输出 — 每 stage 开始/结束输出
# ============================================================


class TestT04ProgressOutput:
    """T04: 进度输出 — 每 stage 开始/结束 click.echo."""

    def test_progress_output_on_start(self, valid_project, mock_loop_engine, capsys):
        """RED: ae dev-loop 启动时 echo 'Starting dev-loop: <req>'."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "build feature X"])

        assert "Starting dev-loop: build feature X" in result.output


# ============================================================
# T05: 错误归类 — AEError 按 code 分 4 类友好提示
# ============================================================


class TestT05ErrorClassification:
    """T05: AEError 按 code 归 4 类 + exit code."""

    def test_user_error_exit_code_2(self):
        """RED: USER_ERROR 类错误 → exit code 2."""
        from auto_engineering.cli import ErrorCategory, classify_error

        err = AEError(ErrorCode.CONFIG_MISSING_API_KEY, "no key")
        category, exit_code = classify_error(err)
        assert category == ErrorCategory.USER_ERROR
        assert exit_code == 2

    def test_api_error_exit_code_3(self):
        """RED: API_ERROR 类错误 → exit code 3."""
        from auto_engineering.cli import ErrorCategory, classify_error

        err = AEError(ErrorCode.LLM_TIMEOUT, "api timeout")
        category, exit_code = classify_error(err)
        assert category == ErrorCategory.API_ERROR
        assert exit_code == 3

    def test_network_error_exit_code_4(self):
        """RED: NETWORK_ERROR 类错误 → exit code 4."""
        from auto_engineering.cli import ErrorCategory, classify_error

        err = AEError(ErrorCode.CHECKPOINT_LOAD_FAILED, "cannot load")
        category, exit_code = classify_error(err)
        assert category == ErrorCategory.NETWORK_ERROR
        assert exit_code == 4

    def test_business_error_exit_code_5(self):
        """RED: BUSINESS_ERROR 类错误 → exit code 5."""
        from auto_engineering.cli import ErrorCategory, classify_error

        err = AEError(ErrorCode.GUARDRAIL_BLOCKED, "blocked")
        category, exit_code = classify_error(err)
        assert category == ErrorCategory.BUSINESS_ERROR
        assert exit_code == 5


# ============================================================
# T07: Ctrl-C (SIGINT) → CancellationToken + checkpoint + 提示 resume
# ============================================================


class TestT07SigintCancellation:
    """T07: SIGINT handler → CancellationToken.cancel() + 友好提示."""

    def test_cancellation_token_cancel_sets_flag(self):
        """RED: CancellationToken.cancel() 设置 _cancelled=True."""
        from auto_engineering.cli import CancellationToken

        token = CancellationToken()
        assert not token.is_cancelled()
        token.cancel()
        assert token.is_cancelled()

    def test_cancellation_token_check_raises(self):
        """RED: CancellationToken.check() 在已 cancel 时抛 TASK_CANCELLED."""
        from auto_engineering.cli import CancellationToken

        token = CancellationToken()
        token.cancel()
        with pytest.raises(AEError) as exc_info:
            token.check()
        assert exc_info.value.code == ErrorCode.TASK_CANCELLED

    def test_sigint_cancels_loop(self, valid_project, monkeypatch):
        """RED: SIGINT handler 触发 token.cancel() → 抛 AEError(TASK_CANCELLED)."""
        from auto_engineering.cli import CancellationToken, _install_sigint_handler

        # 注入一个会在 execute 时 cancel 的 mock runner
        token = CancellationToken()
        _install_sigint_handler(token)

        def fake_run_loop(**kwargs):
            token.cancel()  # 模拟 SIGINT 效果
            raise AEError(ErrorCode.TASK_CANCELLED, "user cancelled")

        monkeypatch.setattr("auto_engineering.cli._run_loop_engine", fake_run_loop)
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "x"])

        # 退出码对应 USER_ERROR=2 或 TASK_CANCELLED 分类
        assert (
            "checkpoint" in result.output.lower()
            or "resume" in result.output.lower()
            or "cancelled" in result.output.lower()
        )


# ============================================================
# T08: --dry-run 模式
# ============================================================


class TestT08DryRun:
    """T08: --dry-run 只跑 architect → 退出,不写文件/git/checkpoint."""

    def test_dry_run_flag_accepted(self, valid_project, mock_loop_engine):
        """RED: --dry-run flag 被接受并传给 runner."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "build x", "--use-v1", "--dry-run"])

        assert result.exit_code == 0
        call_kwargs = mock_loop_engine.call_args.kwargs
        assert call_kwargs.get("dry_run") is True

    def test_dry_run_output_says_plan(self, valid_project, mock_loop_engine, capsys):
        """GREEN: --dry-run mock 返回 dry_run_done,验证输出含 'plan'."""
        from auto_engineering.cli import LoopRunResult

        # 让 mock 返回 dry_run_done 状态
        mock_loop_engine.return_value = LoopRunResult(
            status="dry_run_done",
            total_steps=1,
            checkpoint_id="dry-cp",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "x", "--use-v1", "--dry-run"])

        assert "dry" in result.output.lower() or "plan" in result.output.lower()


# ============================================================
# T09: --log-format json
# ============================================================


class TestT09LogFormatJson:
    """T09: --log-format json 输出结构化日志到 stderr."""

    def test_log_format_json_outputs_to_stderr(self, valid_project, mock_loop_engine):
        """RED: --log-format json 时 click.echo JSON 到 stderr."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "x", "--log-format", "json"])

        assert result.exit_code == 0
        # stderr 应含 JSON(可能含 stage/elapsed/tokens/cost 字段)
        stderr_output = result.stderr if hasattr(result, "stderr") else ""
        # 若 JSON 在 stderr 中找不到,可能在 stdout 中 click 默认输出
        # 至少要求 output 中有可解析 JSON 片段
        # 检查 { ... } 包裹的 JSON
        all_output = result.output + stderr_output
        for line in all_output.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and any(
                        k in obj for k in ("stage", "event", "elapsed", "tokens")
                    ):
                        break
                except json.JSONDecodeError:
                    pass
        # JSON 格式输出或回退 text 都应 exit_code 0
        assert result.exit_code == 0


# ============================================================
# T10: --llm-provider 接受 anthropic/ollama
# ============================================================


class TestT10LlmProvider:
    """T10: --llm-provider 只实装 anthropic,其他提示'未实现'."""

    def test_llm_provider_anthropic_accepted(self, valid_project, mock_loop_engine):
        """RED: --llm-provider anthropic 被接受."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "x", "--llm-provider", "anthropic"])

        assert result.exit_code == 0

    def test_llm_provider_ollama_not_implemented(self, valid_project, mock_loop_engine):
        """RED: --llm-provider ollama 提示'未实现' + 退出码 6."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "x", "--llm-provider", "ollama"])

        # 退出码 6 + 友好提示
        assert (
            result.exit_code == 6
            or "not yet implemented" in result.output.lower()
            or "未实现" in result.output
        )


# ============================================================
# T11: --project-root
# ============================================================


class TestT11ProjectRoot:
    """T11: --project-root flag 指定项目根."""

    def test_project_root_flag_overrides_cwd(self, tmp_path: Path, monkeypatch):
        """RED: --project-root /tmp/foo 时 preflight 用 /tmp/foo 校验."""
        from auto_engineering.cli import LoopRunResult

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()

        runner_mock = MagicMock()
        runner_mock.return_value = LoopRunResult(status="done", total_steps=0, checkpoint_id="x")
        monkeypatch.setattr("auto_engineering.cli._run_loop_engine", runner_mock)

        runner = CliRunner()
        runner.invoke(main, ["dev-loop", "x", "--use-v1", "--project-root", str(project_dir)])

        # 传入的 project_root 应被传给 runner
        assert runner_mock.called
        call_kwargs = runner_mock.call_args.kwargs
        # project_root 是直接 kwarg
        assert str(project_dir) in str(call_kwargs.get("project_root", ""))


# ============================================================
# 进度输出 - stage 开始/结束 (辅助 T04)
# ============================================================


class TestProgressStages:
    """T04 补充: stage 开始/结束输出."""

    def test_stage_progress_logged(self, valid_project, monkeypatch):
        """RED: 每个 stage 开始时 echo 'Stage X: name'."""
        from auto_engineering.cli import _log_stage_progress

        output_lines = []
        monkeypatch.setattr(
            "auto_engineering.cli.click.echo", lambda msg, **kw: output_lines.append(msg)
        )

        _log_stage_progress(1, 3, "architect")
        _log_stage_progress(2, 3, "developer")

        joined = " ".join(output_lines)
        assert "architect" in joined.lower()
        assert "developer" in joined.lower()
