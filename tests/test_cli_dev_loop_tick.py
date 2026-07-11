"""test_cli_dev_loop_tick.py — T9c: v5.6 tick 模式 CLI 契约.

覆盖 ae dev-loop --init/--tick/--result/--status/--resume (§B13 CLI 契约):
  - --init "req" → 第一个 action JSON (stdout)
  - --tick 无 --result → 退出码 1 + 错误信息
  - --status → restore → 状态摘要 JSON
  - 互斥校验 (--init + --tick 不可同时)
  - legacy ae dev-loop "req" 无 flag 仍走 v5.5 (不误入 tick 分派)

CliRunner + tmp .ae-state, 不跑真实 LLM/子进程 gate (只测 init/校验/status).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from auto_engineering.cli import main


def _last_json_line(output: str) -> dict:
    """取输出最后一非空行解析为 JSON (跳过 logging/进度 stderr 混入)."""
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


class TestInitMode:
    def test_init_emits_architect_action(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dev-loop", "--init", "实现登录功能",
             "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        action = _last_json_line(result.output)
        assert action["action"] == "architect"
        assert action["stage"] == "architect"
        assert "thread_id" in action
        # checkpoint 落盘 → .ae-state/checkpoints.db 存在
        assert (tmp_path / ".ae-state" / "checkpoints.db").exists()

    def test_init_requires_requirement(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--init", "--project-root", str(tmp_path)])
        assert result.exit_code != 0


class TestTickMode:
    def test_tick_requires_result(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--tick", "--project-root", str(tmp_path)])
        assert result.exit_code == 1
        assert "result" in result.output.lower()


class TestStatusMode:
    def test_init_then_status_roundtrip(self, tmp_path) -> None:
        """--init 落 checkpoint → 独立 --status 调用 restore 并输出状态."""
        runner = CliRunner()
        init = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert init.exit_code == 0, init.output
        init_action = _last_json_line(init.output)
        thread_id = init_action["thread_id"]

        status = runner.invoke(
            main, ["dev-loop", "--status", "--project-root", str(tmp_path)])
        assert status.exit_code == 0, status.output
        summary = _last_json_line(status.output)
        assert summary["thread_id"] == thread_id
        assert summary["current_stage"] == "architect"

    def test_status_without_checkpoint_errors(self, tmp_path) -> None:
        """无 checkpoint → restore raise → 非零退出 (不静默假成功)."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--status", "--project-root", str(tmp_path)])
        assert result.exit_code != 0


class TestMutexAndLegacy:
    def test_init_and_tick_mutex(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dev-loop", "--init", "req", "--tick",
             "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "互斥" in result.output

    def test_no_requirement_no_flags_errors(self, tmp_path) -> None:
        """裸 ae dev-loop 无 requirement 无 flag → 用法错误 (不进 legacy LLM 路径)."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--project-root", str(tmp_path)])
        assert result.exit_code != 0
