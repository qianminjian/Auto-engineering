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
        assert action["action"] == "project_setup_required"
        assert action["stage"] == "project_setup"
        assert "thread_id" in action
        # checkpoint 落盘 → .ae-state/checkpoints.db 存在
        assert (tmp_path / ".ae-state" / "checkpoints.db").exists()

    def test_init_requires_requirement(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--init", "--project-root", str(tmp_path)])
        assert result.exit_code != 0

    def test_init_uses_full_design_doc_when_requirement_omitted(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text("# Voice Clone\n## 页面\n", encoding="utf-8")
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "dev-loop",
                "--init",
                "--design-doc",
                str(design),
                "--project-root",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 0, result.output
        action = _last_json_line(result.output)
        assert action["action"] == "project_setup_required"

    def test_init_rejects_existing_design_path_as_requirement(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text("# Design\n", encoding="utf-8")
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "dev-loop",
                "--init",
                "design.md",
                "--project-root",
                str(tmp_path),
            ],
        )

        assert result.exit_code != 0
        assert "DESIGN_DOC_REQUIRED" in result.output
        assert "--design-doc design.md" in result.output

    def test_second_init_fails_with_unique_resume_instruction(
        self, tmp_path
    ) -> None:
        runner = CliRunner()
        first = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert first.exit_code == 0, first.output
        thread_id = _last_json_line(first.output)["thread_id"]

        second = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 Y", "--project-root", str(tmp_path)],
        )

        assert second.exit_code != 0
        assert "PROJECT_THREAD_ACTIVE" in second.output
        assert f"--resume {thread_id}" in second.output


class TestTickMode:
    def test_tick_requires_result(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--tick", "--project-root", str(tmp_path)])
        assert result.exit_code == 1
        assert "result" in result.output.lower()

    def test_validate_result_is_non_mutating_and_rejects_invalid_json(
        self, tmp_path
    ) -> None:
        runner = CliRunner()
        init = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert init.exit_code == 0, init.output
        before = runner.invoke(
            main,
            ["dev-loop", "--status", "--project-root", str(tmp_path)],
        )
        result_file = tmp_path / "invalid-result.json"
        result_file.write_text("{", encoding="utf-8")

        validation = runner.invoke(
            main,
            [
                "dev-loop",
                "--validate-result",
                str(result_file),
                "--project-root",
                str(tmp_path),
            ],
        )
        after = runner.invoke(
            main,
            ["dev-loop", "--status", "--project-root", str(tmp_path)],
        )

        assert validation.exit_code == 1
        assert _last_json_line(validation.output)["error_code"] == "RESULT_PARSE_ERROR"
        assert _last_json_line(after.output) == _last_json_line(before.output)

    def test_project_setup_completion_commits_profile_stage_and_next_action(
        self, tmp_path
    ) -> None:
        """真跑回归：独立 CLI 进程恢复后必须原子进入 gap_scan。"""

        design = tmp_path / "design.md"
        design.write_text("# 产品设计\n## 页面\n实现页面。\n", encoding="utf-8")
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            [
                "dev-loop", "--init", "--design-doc", str(design),
                "--project-root", str(tmp_path),
            ],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)
        assert action["stage"] == "project_setup"

        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "package.json").write_text(json.dumps({
            "scripts": {
                "test": "vitest run",
                "lint": "eslint .",
                "typecheck": "tsc --noEmit",
                "build": "vite build",
            },
            "devDependencies": {"typescript": "^5.0.0"},
        }), encoding="utf-8")
        result_file = tmp_path / "project-setup-result.json"
        result_file.write_text(json.dumps({
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "result-project-setup",
            "thread_id": action["thread_id"],
            "tick": action["tick"],
            "stage": "project_setup",
            "causation_id": action["message_id"],
            "correlation_id": action["correlation_id"],
            "extensions": {},
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src", "tests"],
        }), encoding="utf-8")

        validation = runner.invoke(
            main,
            [
                "dev-loop", "--validate-result", str(result_file),
                "--project-root", str(tmp_path),
            ],
        )
        assert validation.exit_code == 0, validation.output

        ticked = runner.invoke(
            main,
            [
                "dev-loop", "--tick", "--result", str(result_file),
                "--project-root", str(tmp_path),
            ],
        )

        assert ticked.exit_code == 0, ticked.output
        next_action = _last_json_line(ticked.output)
        assert next_action["stage"] == "gap_scan"


class TestStatusMode:
    def test_status_accepts_documented_json_format(self, tmp_path) -> None:
        """Skill 文档中的 --format json 调用必须保持兼容。"""
        runner = CliRunner()
        init = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert init.exit_code == 0, init.output

        status = runner.invoke(
            main,
            [
                "dev-loop",
                "--status",
                "--format",
                "json",
                "--project-root",
                str(tmp_path),
            ],
        )

        assert status.exit_code == 0, status.output
        assert _last_json_line(status.output)["current_stage"] == "project_setup"

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
        assert summary["current_stage"] == "project_setup"

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
