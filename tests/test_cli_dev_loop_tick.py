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
import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main


def _last_json_line(output: str) -> dict:
    """取输出最后一非空行解析为 JSON (跳过 logging/进度 stderr 混入)."""
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


def test_public_cli_records_host_worker_fact_without_manual_outcomes_json(
    tmp_path: Path,
) -> None:
    """公开 CLI 入口完成业务产物到宿主 outcomes 的确定性合并。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='record-fixture'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    runner = CliRunner()
    initialized = runner.invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    action = _last_json_line(initialized.output)

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    private_path = tmp_path / worker["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": worker["worker_id"],
        "status": "completed",
        "payload": {"plan": "按设计实现"},
        "summary": "Architect 完成规划",
    }), encoding="utf-8")

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "codex-native-1",
            "--isolation-evidence", "fork_turns=none",
            "--project-root", str(tmp_path),
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    body = _last_json_line(recorded.output)
    assert body["status"] == "worker_outcome_recorded"
    shared_path = tmp_path / mapped["host_execution"]["work_files"]["outcomes"]
    assert json.loads(shared_path.read_text(encoding="utf-8"))["outcomes"][0][
        "native_worker_handle"
    ] == "codex-native-1"


def test_worker_execution_identity_reuses_same_session_and_rotates_on_takeover(
    tmp_path, monkeypatch
) -> None:
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity
    from auto_engineering.host.runtime_driver import (
        HostRunLease,
        HostRunLeaseStore,
    )

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-a")
    action = {
        "message_id": "action-fence",
        "thread_id": "thread-fence",
        "spawn": {"invocations": []},
    }

    first = _bind_worker_execution_identity(action, tmp_path)
    lease_action = {
        **first,
        "extensions": {
            "ae": {
                "execution_control": {
                    "schema_version": "1.0",
                    "disposition": "CONTINUE",
                    "continuation_required": True,
                    "yield_allowed": False,
                    "allowed_stop_reasons": [],
                },
                "runtime": {"build_id": "build-1"},
            }
        },
    }
    HostRunLeaseStore(tmp_path).save(HostRunLease.from_action(
        lease_action,
        platform="codex",
        host_session_id="session-a",
    ))

    same_session = _bind_worker_execution_identity(action, tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "session-b")
    takeover = _bind_worker_execution_identity(action, tmp_path)

    assert same_session["execution_generation"] == 1
    assert takeover["execution_generation"] == 2
    assert same_session["fencing_token"] != takeover["fencing_token"]


def test_worker_retry_after_failure_journal_gets_new_stable_generation(
    tmp_path, monkeypatch
) -> None:
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-a")
    action = {
        "message_id": "action-retry-generation",
        "thread_id": "thread-retry-generation",
        "spawn": {"invocations": []},
    }
    first = _bind_worker_execution_identity(action, tmp_path)
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-retry-generation.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"status": "worker_failed", "failure_attempt": 1}),
        encoding="utf-8",
    )

    retry = _bind_worker_execution_identity(action, tmp_path)
    retry_read = _bind_worker_execution_identity(action, tmp_path)
    assert first["execution_generation"] == 1
    assert retry["execution_generation"] == 2
    assert retry_read["execution_generation"] == 2
    assert retry["fencing_token"] != first["fencing_token"]


def test_prepare_and_finalize_mapping_share_the_same_worker_artifact_generation(
    tmp_path, monkeypatch
) -> None:
    """宿主发起和 Finalizer 必须指向同一代 Worker 私有产物。"""

    from auto_engineering.cli.dev_loop import (
        _map_bound_action_for_host,
        _prepare_action_for_host,
    )
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.action_builder import ActionBuilder

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-a")
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="thread-manifest",
        current_stage="architect",
        requirement="实现确定性治理内核",
    ))
    action.update({
        "message_id": "action-manifest",
        "correlation_id": "thread-manifest",
        "causation_id": "thread-manifest",
        "capability_requirements": {},
        "extensions": {
            "ae": {
                "execution_control": {
                    "schema_version": "1.0",
                    "disposition": "CONTINUE",
                    "continuation_required": True,
                    "yield_allowed": False,
                    "allowed_stop_reasons": [],
                },
                "runtime": {"build_id": "build-manifest"},
            }
        },
    })

    prepared = _prepare_action_for_host(action, tmp_path, compact_view=False)
    remapped = _map_bound_action_for_host(action, tmp_path)

    prepared_worker = prepared["host_execution"]["workers"][0]
    remapped_worker = remapped["host_execution"]["workers"][0]
    assert prepared_worker["outcome_path"] == remapped_worker["outcome_path"]


def test_cleanup_removes_generation_bound_worker_artifact(
    tmp_path, monkeypatch
) -> None:
    """完成 Action 后不能遗留上一代私有 outcome 诱发下次误读。"""

    from auto_engineering.cli.dev_loop import (
        _cleanup_completed_action_work_files,
        _prepare_action_for_host,
    )
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.action_builder import ActionBuilder

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-cleanup")
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="thread-cleanup",
        current_stage="architect",
        requirement="实现确定性治理内核",
    ))
    action.update({
        "message_id": "action-cleanup",
        "correlation_id": "thread-cleanup",
        "causation_id": "thread-cleanup",
        "capability_requirements": {},
        "extensions": {
            "ae": {
                "execution_control": {
                    "schema_version": "1.0",
                    "disposition": "CONTINUE",
                    "continuation_required": True,
                    "yield_allowed": False,
                    "allowed_stop_reasons": [],
                },
                "runtime": {"build_id": "build-cleanup"},
            }
        },
    })
    prepared = _prepare_action_for_host(action, tmp_path, compact_view=False)
    private_path = tmp_path / prepared["host_execution"]["workers"][0]["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text("{}", encoding="utf-8")
    # 以生产规则计算 Action 工作目录，避免把测试绑定到具体哈希字面量。
    import hashlib
    work_dir = tmp_path / ".ae-state/host-runtime/work/" / hashlib.sha256(
        b"action-cleanup"
    ).hexdigest()[:24]
    work_dir.mkdir(parents=True)
    result_file = work_dir / "result.json"
    result_file.write_text("{}", encoding="utf-8")

    _cleanup_completed_action_work_files(
        root=tmp_path,
        result_file=result_file,
        completed_action=action,
        next_action={"message_id": "next-action"},
    )

    assert not private_path.exists()


def test_status_uses_bound_host_mapping_for_active_action(tmp_path, monkeypatch) -> None:
    """status 展示的宿主 Action 必须与实际执行合同使用同一映射入口。"""

    from auto_engineering.cli import main
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    calls = []

    def spy(action, root):
        calls.append((action, root))
        return action

    monkeypatch.setattr(dev_loop_module, "_map_bound_action_for_host", spy)
    dev_loop_module.run_tick_status(tmp_path)

    assert calls


def test_active_action_rejects_event_and_checkpoint_identity_conflict() -> None:
    """两份运行事实指向不同 Action 时必须 fail-closed。"""

    from auto_engineering.cli.dev_loop import _load_active_action

    class Store:
        def load_active_protocol_action(self, thread_id):
            return {"message_id": "checkpoint-action", "thread_id": thread_id}

    class Events:
        def load_action_snapshot(self, thread_id):
            return {"message_id": "event-action", "thread_id": thread_id}

    with pytest.raises(ValueError, match="STATE_SOURCE_CONFLICT"):
        _load_active_action("thread-1", Store(), Events())


def test_active_event_action_is_authoritative_without_checkpoint_splicing() -> None:
    """EventStore 有 Action 时不得从 checkpoint 补宿主字段。"""

    from auto_engineering.cli.dev_loop import _load_active_action

    event_action = {"message_id": "same-action", "thread_id": "thread-1"}
    checkpoint_action = {
        "message_id": "same-action",
        "thread_id": "thread-1",
        "host_execution": {"work_files": {"result": "stale.json"}},
    }

    class Store:
        def load_active_protocol_action(self, thread_id):
            return checkpoint_action

    class Events:
        def load_action_snapshot(self, thread_id):
            return event_action

    assert _load_active_action("thread-1", Store(), Events()) == event_action


def test_state_source_conflict_is_returned_as_protocol_error_action(
    tmp_path, monkeypatch
) -> None:
    """状态源分叉必须让宿主拿到稳定错误，而不是 Python traceback。"""

    from auto_engineering.cli import main
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.setattr(
        dev_loop_module,
        "_load_active_action",
        lambda *_args: (_ for _ in ()).throw(ValueError("STATE_SOURCE_CONFLICT")),
    )

    result = CliRunner().invoke(
        main,
        ["dev-loop", "--tick", "--result", "missing.json", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["action"] == "error"
    assert payload["error_code"] == "STATE_SOURCE_CONFLICT"
    assert "Traceback" not in result.output


def test_status_reports_recovery_required_on_state_source_conflict(
    tmp_path, monkeypatch
) -> None:
    """status 在状态分叉时只读报告恢复要求，不制造新 Action。"""

    from auto_engineering.cli import main
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.setattr(
        dev_loop_module,
        "_load_active_action",
        lambda *_args: (_ for _ in ()).throw(ValueError("STATE_SOURCE_CONFLICT")),
    )

    result = CliRunner().invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["active_action_error"] == "STATE_SOURCE_CONFLICT"
    assert payload["recovery_required"] is True


def test_finalize_stops_with_stable_error_on_state_source_conflict(
    tmp_path, monkeypatch, capsys
) -> None:
    """Finalizer 遇到状态分叉时不能消费任何宿主产物。"""

    from auto_engineering.cli import main
    from auto_engineering.cli.dev_loop import run_tick_finalize
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.setattr(
        dev_loop_module,
        "_load_active_action",
        lambda *_args: (_ for _ in ()).throw(ValueError("STATE_SOURCE_CONFLICT")),
    )

    run_tick_finalize(
        tmp_path / "outcomes.json",
        tmp_path / "coordinator.json",
        tmp_path,
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert payload["error_code"] == "STATE_SOURCE_CONFLICT"


def test_supervisor_stops_with_stable_error_on_state_source_conflict(
    tmp_path, monkeypatch
) -> None:
    """Supervisor 入口遇到状态分叉时必须显式停止且无 traceback。"""

    from auto_engineering.cli import main
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.setattr(
        dev_loop_module,
        "_load_active_action",
        lambda *_args: (_ for _ in ()).throw(ValueError("STATE_SOURCE_CONFLICT")),
    )

    result = CliRunner().invoke(
        main,
        ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "STATE_SOURCE_CONFLICT" in result.output
    assert "Traceback" not in result.output


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
        summary = _last_json_line(status.output)
        assert summary["next_operation"] == {
            "operation": "resume_active_action",
            "thread_id": thread_id,
            "argv": ["dev-loop", "--resume", thread_id],
        }
        assert summary["active_action"]["stage"] == "project_setup"
        assert "result" in summary["active_action"]["work_files"]

        repeated = runner.invoke(
            main,
            ["dev-loop", "--status", "--project-root", str(tmp_path)],
        )
        assert repeated.exit_code == 0, repeated.output
        repeated_summary = _last_json_line(repeated.output)
        assert repeated_summary["tick"] == summary["tick"]
        assert repeated_summary["active_action"]["message_id"] == (
            summary["active_action"]["message_id"]
        )

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
    def test_status_action_summary_exposes_current_gap_and_work_contract(
        self,
    ) -> None:
        from auto_engineering.cli.dev_loop import _status_action_summary

        summary = _status_action_summary({
            "message_id": "action-7",
            "action": "gap_review",
            "stage": "gap_review",
            "current_gap_index": 1,
            "total_gaps": 3,
            "current_gap": {"id": "gap-2", "summary": "缺少接口错误合同"},
            "work_files": {"result": ".ae-state/work/action-7/result.json"},
            "expected_format": {"decision": {"gap_id": "string"}},
            "context": {"private": "must-not-leak"},
        })

        assert summary == {
            "message_id": "action-7",
            "action": "gap_review",
            "stage": "gap_review",
            "current_gap_index": 1,
            "total_gaps": 3,
            "current_gap": {"id": "gap-2", "summary": "缺少接口错误合同"},
            "work_files": {"result": ".ae-state/work/action-7/result.json"},
            "expected_format": {"decision": {"gap_id": "string"}},
        }

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
        assert "[宿主监督] 已接管 Action" in result.output
        assert _last_json_line(result.output)["message_id"] == "terminal-1"
        assert evidence_calls[0]["host"] == "codex"
        assert evidence_calls[0]["thread_id"]
        assert list((tmp_path / ".ae-state/reports").glob("loop-stop-*.md"))

    def test_supervise_reopens_context_after_result_repair_and_clears_lease(
        self, tmp_path, monkeypatch,
    ) -> None:
        """拒绝→修复→重试必须是完整闭环，不能留下假活跃 lease。"""
        from auto_engineering.host import backends
        from auto_engineering.host import supervisor as supervisor_module
        from auto_engineering.host.invocation import (
            ActionExecutionReceipt,
            HostInvocationProbe,
        )
        from auto_engineering.host.runtime_driver import HostRunLeaseStore

        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        initial_action = _last_json_line(initialized.output)
        contexts: list[str] = []
        operation_calls = 0

        class FakeBackend:
            def __init__(self, **kwargs):
                del kwargs

            def probe(self):
                return HostInvocationProbe.available("codex")

            def execute(self, request):
                context_id = f"fresh-context-{len(contexts) + 1}"
                contexts.append(context_id)
                return ActionExecutionReceipt.from_dict({
                    "schema_version": "1.0",
                    "thread_id": request.thread_id,
                    "action_message_id": request.action_message_id,
                    "build_id": request.build_id,
                    "host_context_id": context_id,
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
                del kwargs

            def run(self, operations):
                nonlocal operation_calls
                operation_calls += 1
                if operation_calls == 1:
                    return {
                        **initial_action,
                        "result_rejection": {
                            "repair_required": True,
                            "error_code": "HOST_EVIDENCE_INVALID",
                        },
                    }
                return {
                    "message_id": "terminal-after-repair",
                    "action": "done",
                    "reason_code": "GOAL_ACHIEVED",
                    "extensions": {"ae": {"execution_control": {
                        "schema_version": "1.0",
                        "disposition": "TERMINAL",
                        "continuation_required": False,
                        "yield_allowed": True,
                        "allowed_stop_reasons": ["goal_achieved"],
                        "reason_code": "GOAL_ACHIEVED",
                    }}},
                }

        class FakeEvidence:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def record_terminal(self, **kwargs):
                del kwargs
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
            env={
                "AE_HOST_PLATFORM": "codex",
                "CODEX_THREAD_ID": "real-session-1",
            },
        )

        assert result.exit_code == 0, result.output
        assert contexts == ["fresh-context-1", "fresh-context-2"]
        assert operation_calls == 2
        assert _last_json_line(result.output)["message_id"] == (
            "terminal-after-repair"
        )
        assert HostRunLeaseStore(tmp_path).load() is None

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
        from auto_engineering.host.runtime_driver import HostRunLeaseStore

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
            env={
                "AE_HOST_PLATFORM": "codex",
                "CODEX_THREAD_ID": "failed-session-1",
            },
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
        assert HostRunLeaseStore(tmp_path).load() is None

    def test_supervise_normalizes_unexpected_host_exception(
        self, tmp_path, monkeypatch,
    ) -> None:
        from auto_engineering.host import backends
        from auto_engineering.host import supervisor as supervisor_module
        from auto_engineering.host.invocation import (
            ActionExecutionReceipt,
            HostInvocationProbe,
        )
        from auto_engineering.host.runtime_driver import HostRunLeaseStore

        initialized = CliRunner().invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output

        class FakeBackend:
            def __init__(self, **kwargs):
                del kwargs

            def probe(self):
                return HostInvocationProbe.available("codex")

            def execute(self, request):
                return ActionExecutionReceipt.from_dict({
                    "schema_version": "1.0",
                    "thread_id": request.thread_id,
                    "action_message_id": request.action_message_id,
                    "build_id": request.build_id,
                    "host_context_id": "unexpected-context-1",
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

        class FailingOperations:
            def __init__(self, **kwargs):
                del kwargs

            def run(self, operations):
                del operations
                raise RuntimeError("unexpected operation failure")

        monkeypatch.setattr(backends, "CodexInvocationBackend", FakeBackend)
        monkeypatch.setattr(
            supervisor_module, "MachineOperationExecutor", FailingOperations,
        )
        result = CliRunner().invoke(
            main,
            ["dev-loop", "--supervise", "--project-root", str(tmp_path)],
            env={
                "AE_HOST_PLATFORM": "codex",
                "CODEX_THREAD_ID": "unexpected-session-1",
            },
        )

        assert result.exit_code != 0
        assert "HOST_SUPERVISOR_PROTOCOL_ERROR" in result.output
        assert "Traceback" not in result.output
        assert list((tmp_path / ".ae-state/reports").glob("loop-stop-*.md"))
        assert HostRunLeaseStore(tmp_path).load() is None

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

    def test_finalize_missing_spawn_outputs_becomes_worker_failure(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """真实 CLI Finalizer 不得把 spawn 空交接误报为输入错误。"""
        dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")
        from auto_engineering.host.spawn_contract import WorkerInvocationSpec
        from auto_engineering.loop import event_store as event_store_module
        from auto_engineering.loop.checkpoint import store as checkpoint_store

        prompt_ref = ".ae-state/effects/prompt/worker.txt"
        invocation = WorkerInvocationSpec(
            worker_id="architect-0",
            role="architect",
            prompt_ref=prompt_ref,
            prompt_sha256="a" * 64,
            requested_effort="xhigh",
            isolation="fresh_context",
            capabilities={
                "may_drive_loop": False,
                "may_spawn_workers": False,
            },
            receipt_path=".ae-state/spawn-proofs/architect-0.json",
        )
        action = {
            "schema_version": "1.1",
            "message_id": "architect-action-1",
            "thread_id": "thread-1",
            "stage": "architect",
            "spawn": {
                "contract_version": "1.0",
                "count": 1,
                "parallel": False,
                "effort": "xhigh",
                "invocations": [invocation.to_dict()],
            },
            "host_execution": {
                "platform": "codex",
                "work_files": {
                    "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                    "coordinator_result": (
                        ".ae-state/host-runtime/work/a/coordinator-result.json"
                    ),
                    "result": ".ae-state/host-runtime/work/a/result.json",
                },
            },
        }

        class FakeStore:
            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs

            def close(self) -> None:
                pass

        class FakeEvents:
            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs

            def load_action_snapshot(self, thread_id: str):
                assert thread_id == "thread-1"
                return action

            def close(self) -> None:
                pass

        monkeypatch.setattr(checkpoint_store, "SQLiteCheckpointStore", FakeStore)
        monkeypatch.setattr(event_store_module, "SQLiteEventStore", FakeEvents)
        monkeypatch.setattr(dev_loop_module, "_active_thread", lambda store: "thread-1")
        monkeypatch.setattr(dev_loop_module, "_map_action_for_host", lambda value: value)

        from auto_engineering.cli.dev_loop import run_tick_finalize

        # 旧调用者传入的路径伪装成合法成功产物；当前 Action 的 work_files
        # 缺失时也必须忽略它，不能把上一 Action 的结果投影进来。
        (tmp_path / "missing-outcomes.json").write_text(
            json.dumps({"outcomes": [{"stale": True}]}), encoding="utf-8"
        )
        (tmp_path / "empty-coordinator.json").write_text(
            json.dumps({"stale": True}), encoding="utf-8"
        )
        run_tick_finalize(
            tmp_path / "missing-outcomes.json",
            tmp_path / "empty-coordinator.json",
            tmp_path,
            output_result_file=tmp_path / "result.json",
        )

        result = json.loads(capsys.readouterr().out.strip())
        assert result["spawned"] is False
        assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
        canonical_result = (
            tmp_path / ".ae-state/host-runtime/work/a/result.json"
        )
        assert json.loads(canonical_result.read_text()) == result

        # 空 JSON 交接与缺文件必须共享同一失败事实；重复提交同一失败
        # 应保持幂等，真正的重试由新的 execution_generation 触发。
        (tmp_path / "empty-coordinator.json").write_text("{}")
        (tmp_path / "missing-outcomes.json").write_text('{"outcomes":[]}')
        run_tick_finalize(
            tmp_path / "missing-outcomes.json",
            tmp_path / "empty-coordinator.json",
            tmp_path,
            output_result_file=tmp_path / "result.json",
        )
        repeated = json.loads(capsys.readouterr().out.strip())
        assert repeated["spawned"] is False
        assert repeated["spawn_error_code"] == "HOST_WORKER_FAILED"
        assert repeated["spawn_retry_attempt"] == 1

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
