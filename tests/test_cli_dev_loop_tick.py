"""test_cli_dev_loop_tick.py — T9c: v5.6 tick 模式 CLI 契约.

覆盖 ae dev-loop --init/--tick/--result/--status/--resume (§B13 CLI 契约):
  - --init "req" → 第一个 action JSON (stdout)
  - --tick 无 --result → 退出码 1 + 结构化 resume 指令
  - --status → restore → 状态摘要 JSON
  - 互斥校验 (--init + --tick 不可同时)
  - legacy ae dev-loop "req" 无 flag 仍走 v5.5 (不误入 tick 分派)

CliRunner + tmp .ae-state, 不跑真实 LLM/子进程 gate (只测 init/校验/status).
"""

from __future__ import annotations

import hashlib
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
        assert (tmp_path / ".ae-state" / ".gitignore").read_text() == (
            "*\n!.gitignore\n"
        )

    def test_product_compact_view_omits_inline_prompt_from_stdout(
        self, tmp_path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dev-loop", "--init", "实现登录功能",
             "--project-root", str(tmp_path)],
            env={"AE_HOST_ACTION_VIEW": "compact"},
        )

        assert result.exit_code == 0, result.output
        action = _last_json_line(result.output)
        assert action["view"] == "compact"
        assert "instruction" not in action
        assert "context" not in action
        assert "subagent_prompt" not in action
        prompt_ref = action["coordinator_prompt_ref"]
        prompt_path = tmp_path / prompt_ref["path"]
        assert prompt_path.is_file()
        assert hashlib.sha256(prompt_path.read_bytes()).hexdigest() == (
            prompt_ref["sha256"]
        )

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
    def test_tick_without_result_returns_active_resume_operation(
        self,
        tmp_path,
    ) -> None:
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        thread_id = _last_json_line(initialized.output)["thread_id"]
        result = runner.invoke(
            main, ["dev-loop", "--tick", "--project-root", str(tmp_path)])
        assert result.exit_code == 1
        error = _last_json_line(result.output)
        assert error["error_code"] == "TICK_RESULT_REQUIRED"
        assert error["next_operation"] == {
            "operation": "resume_active_action",
            "thread_id": thread_id,
            "argv": ["dev-loop", "--resume", thread_id],
        }

    def test_status_exposes_same_active_resume_operation(self, tmp_path) -> None:
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        thread_id = _last_json_line(initialized.output)["thread_id"]

        status = runner.invoke(
            main,
            ["dev-loop", "--status", "--project-root", str(tmp_path)],
        )

        assert status.exit_code == 0, status.output
        assert _last_json_line(status.output)["next_operation"] == {
            "operation": "resume_active_action",
            "thread_id": thread_id,
            "argv": ["dev-loop", "--resume", thread_id],
        }

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
                "test": "node -e \"console.log('1 test passed')\"",
                "lint": "node -e \"console.log('lint passed')\"",
                "typecheck": "node -e \"console.log('typecheck passed')\"",
                "build": "node -e \"console.log('build passed')\"",
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

    def test_status_uses_run_lease_after_active_checkpoint_is_released(
        self, tmp_path, monkeypatch,
    ) -> None:
        from dataclasses import replace

        from auto_engineering.host.runtime_driver import (
            HostRunLease,
            HostRunLeaseStore,
        )
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)
        with SQLiteCheckpointStore(tmp_path / ".ae-state/checkpoints.db") as store:
            assert store.release_project_thread(action["thread_id"]) is True
        lease = HostRunLease.from_action(
            action, platform="codex", host_session_id="terminal-session",
        )
        HostRunLeaseStore(tmp_path).save(replace(
            lease,
            disposition="TERMINAL",
            continuation_required=False,
            yield_allowed=True,
        ))

        status = runner.invoke(
            main, ["dev-loop", "--status", "--project-root", str(tmp_path)],
        )

        assert status.exit_code == 0, status.output
        summary = _last_json_line(status.output)
        assert summary["thread_id"] == action["thread_id"]
        assert summary["current_stage"] == "done"
        assert summary["expected_stage"] == "done"

        generic = runner.invoke(
            main, ["status", "--format", "json", "--project-root", str(tmp_path)],
        )
        assert generic.exit_code == 0, generic.output
        generic_summary = json.loads(generic.output)
        assert generic_summary["thread_id"] == action["thread_id"]
        assert generic_summary["stage"] == "done"


class TestMutexAndLegacy:
    def test_relative_design_doc_resolves_against_explicit_project_root(
        self, tmp_path, monkeypatch,
    ) -> None:
        project = tmp_path / "target"
        launcher = tmp_path / "launcher"
        (project / "design").mkdir(parents=True)
        launcher.mkdir()
        (project / "design/spec.md").write_text(
            "# 设计\n## 模块\n实现模块。\n", encoding="utf-8",
        )
        monkeypatch.chdir(launcher)

        result = CliRunner().invoke(main, [
            "dev-loop", "--init", "按设计实现",
            "--design-doc", "design/spec.md",
            "--project-root", str(project),
        ])

        assert result.exit_code == 0, result.output

    def test_supervisor_normalizes_host_resource_exhaustion(self) -> None:
        from auto_engineering.cli.dev_loop import _host_context_failure_code

        assert _host_context_failure_code(
            "failed", "HOST_CODEX_USAGE_LIMIT"
        ) == "HOST_ACTION_CONTEXT_RESOURCE_EXHAUSTED"
        assert _host_context_failure_code(
            "failed", "HOST_CLAUDE_BUDGET_EXHAUSTED"
        ) == "HOST_ACTION_CONTEXT_RESOURCE_EXHAUSTED"
        assert _host_context_failure_code(
            "failed", "HOST_CODEX_EXECUTION_FAILED"
        ) == "HOST_ACTION_CONTEXT_FAILED"

    def test_supervise_is_internal_mutually_exclusive_mode(
        self, tmp_path, monkeypatch,
    ) -> None:
        import auto_engineering.cli as cli_module

        calls: list[object] = []
        monkeypatch.setattr(
            cli_module,
            "run_action_supervisor",
            lambda root: calls.append(root),
            raising=False,
        )
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert calls == [tmp_path.resolve()]

        conflict = runner.invoke(
            main,
            [
                "dev-loop", "--supervise", "--status",
                "--project-root", str(tmp_path),
            ],
        )
        assert conflict.exit_code != 0
        assert "互斥" in conflict.output

    def test_supervise_drives_real_active_action_to_terminal(
        self, tmp_path, monkeypatch,
    ) -> None:
        from auto_engineering.host import backends
        from auto_engineering.host import supervisor as supervisor_module
        from auto_engineering.host.invocation import (
            ActionExecutionReceipt,
            HostInvocationProbe,
        )

        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output

        class FakeBackend:
            def __init__(self, **kwargs):
                pass

            def probe(self):
                return HostInvocationProbe.available("codex")

            def execute(self, request):
                return ActionExecutionReceipt.from_dict({
                    "schema_version": "1.0",
                    "thread_id": request.thread_id,
                    "action_message_id": request.action_message_id,
                    "build_id": request.build_id,
                    "host_context_id": "fresh-context-1",
                    "backend": "codex",
                    "status": "completed",
                    "exit_code": 0,
                    "work_file_digests": {},
                    "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1},
                })

            def cancel(self, host_context_id):
                raise AssertionError(host_context_id)

        class FakeOperations:
            def __init__(self, **kwargs):
                pass

            def run(self, operations):
                return {
                    "message_id": "terminal-1",
                    "action": "done",
                    "extensions": {"ae": {"execution_control": {
                        "schema_version": "1.0",
                        "disposition": "TERMINAL",
                        "continuation_required": False,
                        "yield_allowed": True,
                        "allowed_stop_reasons": ["goal_achieved"],
                        "reason_code": "GOAL_ACHIEVED",
                    }}},
                }

        evidence_calls: list[dict[str, object]] = []

        class FakeEvidence:
            def __init__(self, *args, **kwargs):
                pass

            def record_terminal(self, **kwargs):
                evidence_calls.append(kwargs)
                return tmp_path / ".ae-state/reports/evidence.json"

        monkeypatch.setattr(backends, "CodexInvocationBackend", FakeBackend)
        monkeypatch.setattr(
            supervisor_module, "MachineOperationExecutor", FakeOperations,
        )
        monkeypatch.setattr(
            supervisor_module, "ProductEvidenceArtifactJournal", FakeEvidence,
        )
        result = runner.invoke(
            main,
            ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
            env={"AE_HOST_PLATFORM": "codex"},
        )
        assert result.exit_code == 0, result.output
        assert _last_json_line(result.output)["message_id"] == "terminal-1"
        assert evidence_calls[0]["host"] == "codex"
        assert evidence_calls[0]["thread_id"]
        assert list((tmp_path / ".ae-state/reports").glob("loop-stop-*.md"))

    def test_supervise_reports_stable_error_without_python_traceback(
        self, tmp_path, monkeypatch,
    ) -> None:
        import auto_engineering.cli as cli_module
        from auto_engineering.host.invocation import ActionExecutionContractError

        def fail(_root):
            raise ActionExecutionContractError("HOST_OPERATION_FINALIZE_FAILED")

        monkeypatch.setattr(cli_module, "run_action_supervisor", fail)
        result = CliRunner().invoke(
            main,
            ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
        )

        assert result.exit_code != 0
        assert "HOST_OPERATION_FINALIZE_FAILED" in result.output
        assert "Traceback" not in result.output

    def test_supervise_persists_stop_report_when_host_operation_raises(
        self, tmp_path, monkeypatch,
    ) -> None:
        from auto_engineering.host import backends
        from auto_engineering.host import supervisor as supervisor_module
        from auto_engineering.host.invocation import (
            ActionExecutionContractError,
            ActionExecutionReceipt,
            HostInvocationProbe,
        )

        initialized = CliRunner().invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output

        class FakeBackend:
            def __init__(self, **kwargs):
                pass

            def probe(self):
                return HostInvocationProbe.available("codex")

            def execute(self, request):
                return ActionExecutionReceipt.from_dict({
                    "schema_version": "1.0",
                    "thread_id": request.thread_id,
                    "action_message_id": request.action_message_id,
                    "build_id": request.build_id,
                    "host_context_id": "failed-context-1",
                    "backend": "codex",
                    "status": "completed",
                    "exit_code": 0,
                    "work_file_digests": {},
                    "usage": {
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                    },
                })

            def cancel(self, host_context_id):
                raise AssertionError(host_context_id)

        class FakeOperations:
            def __init__(self, **kwargs):
                pass

            def run(self, operations):
                raise ActionExecutionContractError(
                    "HOST_OPERATION_FINALIZE_FAILED"
                )

        monkeypatch.setattr(backends, "CodexInvocationBackend", FakeBackend)
        monkeypatch.setattr(
            supervisor_module, "MachineOperationExecutor", FakeOperations,
        )

        result = CliRunner().invoke(
            main,
            ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
            env={"AE_HOST_PLATFORM": "codex"},
        )

        assert result.exit_code != 0
        assert "HOST_OPERATION_FINALIZE_FAILED" in result.output
        reports = list(
            (tmp_path / ".ae-state/reports").glob("loop-stop-*.md")
        )
        assert len(reports) == 1
        report = reports[0].read_text(encoding="utf-8")
        assert "`ERROR`" in report
        assert "HOST_OPERATION_FINALIZE_FAILED" in report
        assert "failed-context-1" in report

    def test_finalize_result_accepts_non_spawn_coordinator_payload(
        self, tmp_path
    ) -> None:
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)
        payload = tmp_path / "coordinator-result.json"
        payload.write_text(
            json.dumps({
                "result_type": "project_setup_completed",
                "artifacts": ["pyproject.toml"],
            }),
            encoding="utf-8",
        )

        result = runner.invoke(
            main,
            [
                "dev-loop",
                "--finalize-result",
                str(payload),
                "--output-result",
                str(tmp_path / "result.json"),
                "--project-root",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 0, result.output
        finalized = _last_json_line(result.output)
        assert finalized["message_type"] == "result"
        assert finalized["causation_id"] == action["message_id"]
        assert finalized["stage"] == action["stage"]
        assert finalized["result_type"] == "project_setup_completed"
        assert finalized["artifacts"] == ["pyproject.toml"]
        assert json.loads(
            (tmp_path / "result.json").read_text(encoding="utf-8")
        ) == finalized

    def test_internal_result_paths_are_bound_to_project_root_after_cwd_drift(
        self, tmp_path, monkeypatch
    ) -> None:
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)

        action_key = hashlib.sha256(
            action["message_id"].encode("utf-8")
        ).hexdigest()[:24]
        work_dir = (
            tmp_path / ".ae-state" / "host-runtime" / "work" / action_key
        )
        work_dir.mkdir(parents=True)
        (work_dir / "coordinator-result.json").write_text(
            json.dumps({
                "result_type": "project_setup_completed",
                "artifacts": [],
            }),
            encoding="utf-8",
        )
        nested = tmp_path / ".ae-state" / "effects" / "prompt"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        finalized = runner.invoke(
            main,
            [
                "dev-loop", "--finalize-result",
                str(work_dir / "coordinator-result.json"),
                "--output-result", str(work_dir / "result.json"),
                "--project-root", str(tmp_path),
            ],
        )
        assert finalized.exit_code == 0, finalized.output
        assert (work_dir / "result.json").is_file()
        assert not (nested / "result.json").exists()

        validated = runner.invoke(
            main,
            [
                "dev-loop", "--validate-result", str(work_dir / "result.json"),
                "--project-root", str(tmp_path),
            ],
        )
        assert validated.exit_code == 0, validated.output

        ticked = runner.invoke(
            main,
            [
                "dev-loop", "--tick", "--result", str(work_dir / "result.json"),
                "--project-root", str(tmp_path),
            ],
        )
        assert ticked.exit_code == 0, ticked.output
        assert not work_dir.exists()

    def test_finalize_rebinds_stale_paths_to_active_action_work_files(
        self, tmp_path
    ) -> None:
        """跨 Tick 误传旧路径时，Finalizer 仍只消费当前 Action 的文件。"""
        runner = CliRunner()
        design = tmp_path / "design.md"
        design.write_text("# 设计\n\n实现一个函数。\n", encoding="utf-8")
        initialized = runner.invoke(
            main,
            [
                "dev-loop", "--init", "实现 X", "--design-doc", str(design),
                "--project-root", str(tmp_path),
            ],
        )
        assert initialized.exit_code == 0, initialized.output
        first = _last_json_line(initialized.output)
        first_files = first["host_execution"]["work_files"]
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "package.json").write_text(
            json.dumps({
                "scripts": {
                    "test": "node -e \"console.log('1 test passed')\"",
                    "lint": "node -e \"console.log('lint passed')\"",
                    "typecheck": "node -e \"console.log('typecheck passed')\"",
                    "build": "node -e \"console.log('build passed')\"",
                },
                "devDependencies": {"typescript": "^5.0.0"},
            }),
            encoding="utf-8",
        )
        first_payload = tmp_path / first_files["coordinator_result"]
        first_payload.parent.mkdir(parents=True)
        first_payload.write_text(
            json.dumps({
                "result_type": "project_setup_completed",
                "artifacts": ["package.json", "src", "tests"],
            }),
            encoding="utf-8",
        )
        first_finalize = runner.invoke(
            main,
            [
                "dev-loop", "--finalize-result", str(first_payload),
                "--output-result", str(tmp_path / first_files["result"]),
                "--project-root", str(tmp_path),
            ],
        )
        assert first_finalize.exit_code == 0, first_finalize.output
        advanced = runner.invoke(
            main,
            [
                "dev-loop", "--tick", "--result",
                str(tmp_path / first_files["result"]),
                "--project-root", str(tmp_path),
            ],
        )
        assert advanced.exit_code == 0, advanced.output
        current = _last_json_line(advanced.output)
        assert current["message_id"] != first["message_id"]
        current_files = current["host_execution"]["work_files"]
        current_payload = tmp_path / current_files["coordinator_result"]
        current_payload.parent.mkdir(parents=True)
        current_payload.write_text(
            json.dumps({
                "gaps": [],
                "section_findings": [{
                    "section_ref": "1",
                    "verdict": "clear",
                    "evidence": ["使用了报告中的错误章节编号"],
                }],
            }),
            encoding="utf-8",
        )
        rejected = runner.invoke(
            main,
            [
                "dev-loop", "--finalize-result", str(current_payload),
                "--output-result", str(tmp_path / current_files["result"]),
                "--project-root", str(tmp_path),
            ],
            env={"AE_HOST_ACTION_VIEW": "compact"},
        )
        assert rejected.exit_code == 0, rejected.output
        repair = _last_json_line(rejected.output)
        assert repair["message_id"] == current["message_id"]
        assert repair["result_rejection"]["repair_required"] is True
        assert repair["result_rejection"]["violations"] == [
            "SECTION_FINDING_UNKNOWN:1",
            f"SECTION_FINDING_MISSING:{current['context']['design_sections'][0]['section_id']}",
        ]
        assert not (tmp_path / current_files["result"]).exists()

        current_payload.write_text(
            json.dumps({
                "gaps": [],
                "section_findings": [{
                    "section_ref": current["context"]["host_design_sections"][0]["section_ref"],
                    "verdict": "clear",
                    "evidence": ["已核对完整设计文档"],
                }],
            }),
            encoding="utf-8",
        )

        # 模拟长会话保留了上一 Action 的参数；旧文件即使存在也不得被消费。
        stale_payload = tmp_path / first_files["coordinator_result"]
        stale_result = tmp_path / first_files["result"]
        stale_payload.parent.mkdir(parents=True, exist_ok=True)
        stale_payload.write_text(json.dumps({"stale": True}), encoding="utf-8")
        finalized = runner.invoke(
            main,
            [
                "dev-loop", "--finalize-result", str(stale_payload),
                "--output-result", str(stale_result),
                "--project-root", str(tmp_path),
            ],
        )

        assert finalized.exit_code == 0, finalized.output
        result = _last_json_line(finalized.output)
        assert result["causation_id"] == current["message_id"]
        assert result["gaps"] == []
        assert (tmp_path / current_files["result"]).is_file()
        assert not stale_result.exists()

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
