"""v2.1 Phase C — E2E 测试: ae dev-loop 真 CLI 调用 + v2.0 路径.

设计: 真实 subprocess 调 `ae dev-loop --help` + mock 调 ae dev-loop
(用 mock AnthropicProvider + mock LLM Response) 验证 v2.0 路径端到端.

约束 (TDD 协议):
- 真实 CLI 调用, 不能只 mock 函数
- 单文件 pytest --no-cov --timeout=60
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main

# ============================================================
# C.5 — E2E: subprocess ae dev-loop --help 含 v2.0 提及
# ============================================================


class TestC5E2ESubprocessHelp:
    """C.5: 真 subprocess 调 `ae dev-loop --help` 含 v2.0 mention."""

    def test_subprocess_dev_loop_help_mentions_v2(self, tmp_path: Path, monkeypatch):
        """E2E: subprocess 调 ae dev-loop --help, 验证 v2.0 mention."""
        # 找 venv 里的 ae CLI
        venv_ae = Path(__file__).parent.parent / ".venv" / "bin" / "ae"
        if not venv_ae.exists():
            pytest.skip(f"ae CLI not found at {venv_ae}")

        # 真实 subprocess 调用
        result = subprocess.run(
            [str(venv_ae), "dev-loop", "--help"],
            capture_output=True,
            text=True,
            env={**os.environ, "ANTHROPIC_API_KEY": "test-key-not-real"},
            cwd=str(tmp_path),
            timeout=30,
        )

        assert result.returncode == 0, f"ae dev-loop --help failed: {result.stderr}"
        # 验证: v2.0 + orchestrator 至少一个出现
        output = result.stdout
        assert "v2.0" in output or "orchestrator" in output.lower(), (
            f"ae dev-loop --help should mention v2.0/orchestrator, got: {output[:500]}"
        )
        # 验证: --use-v1 flag 出现
        assert "--use-v1" in output, f"--use-v1 flag missing from help: {output[:500]}"


# ============================================================
# C.6 — E2E: 临时目录跑 ae dev-loop (mock 模式) 验证 v2.0 stage 输出
# ============================================================


class TestC6E2EMockRuntime:
    """C.6: CliRunner 端到端跑 dev-loop, 验证 v2.0 stage 输出."""

    def test_e2e_dev_loop_uses_v2_orchestrator_path(
        self, tmp_path: Path, monkeypatch
    ):
        """E2E: dev-loop 在 valid project + API key 下走 v2.0 路径, 输出 v2.0 stage 标记."""
        # 准备 valid project
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text(
            "project_name: test-app\n"
            "project_type: cli-tool\n"
            "package_manager: uv\n"
            "test_runner: pytest\n"
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        monkeypatch.chdir(tmp_path)

        # Mock v2.0 Orchestrator (避免真跑 LLM)
        from auto_engineering.cli import OrchestratorRunResult

        monkeypatch.setattr(
            "auto_engineering.cli._run_v2_orchestrator",
            lambda **kwargs: OrchestratorRunResult(
                status="done",
                total_steps=2,
                checkpoint_id="e2e-v2-cp",
            ),
        )

        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "build a feature"])

        # 验证: exit 0
        assert result.exit_code == 0, f"unexpected exit: {result.output}"
        # 验证: 输出含 v2.0 阶段标记
        assert "[engine] using v2.0 orchestrator" in result.output, (
            f"missing v2.0 orchestrator marker in: {result.output}"
        )
        # 验证: 完成总结
        assert "dev-loop complete" in result.output, (
            f"missing completion summary in: {result.output}"
        )
