"""test_cli_dev_loop_tick.py — T9c: v5.8 tick 模式 CLI 契约.

覆盖 ae dev-loop --init/--tick/--result/--status/--resume (§B13 CLI 契约):
  - --init "req" → 第一个 action JSON (stdout)
  - --tick 无 --result → 退出码 1 + 结构化 resume 指令
  - --status → restore → 状态摘要 JSON
  - 互斥校验 (--init + --tick 不可同时)
  - 裸 ae dev-loop 无 flag 不进入旧路径

CliRunner + tmp .ae-state, 不跑真实 LLM/子进程 gate (只测 init/校验/status).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path

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
    assert not (tmp_path / "ae.toml").exists()
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


def test_public_cli_records_codex_status_only_wait_with_bound_observation(
    tmp_path: Path,
) -> None:
    """Codex wait completed:null 时，观察事实可安全桥接私有 outcome。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='codex-status-only-fixture'\n", encoding="utf-8"
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
        "summary": "Worker 完成",
    }), encoding="utf-8")

    observed = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-observation",
            "--worker-id", worker["worker_id"],
            "--observation-status", "completed",
            "--observation-wait-attempt", "1",
            "--owner-known",
            "--observation-handle", "codex-native-status-only",
            "--project-root", str(tmp_path),
        ],
    )
    assert observed.exit_code == 0, observed.output

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "codex-native-status-only",
            "--native-result-file", worker["native_result_path"],
            "--native-status-only",
            "--actual-model", "unreported",
            "--isolation-evidence", "fork_turns=none",
            "--project-root", str(tmp_path),
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    body = _last_json_line(recorded.output)
    assert body["status"] == "worker_outcome_recorded"
    assert body["outcome"]["native_worker_handle"] == "codex-native-status-only"


def test_public_cli_routes_invalid_worker_artifact_to_failure_outcome(
    tmp_path: Path,
) -> None:
    """私有 Worker 产物非法时，公开 CLI 仍返回统一失败事实。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='invalid-worker-artifact-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    private_path = tmp_path / worker["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    malformed_private = {"batch_id": "private-invalid"}
    private_path.write_text(json.dumps(malformed_private), encoding="utf-8")

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "claude-native-1",
            "--actual-model", "sonnet",
            "--isolation-evidence", "fresh_context",
            "--native-result-file", str(tmp_path / worker["native_result_path"]),
            "--project-root", str(tmp_path),
        ],
    )

    assert recorded.exit_code == 0, recorded.output
    body = _last_json_line(recorded.output)
    assert body["status"] == "worker_outcome_recorded"
    assert body["failure_code"] == "HOST_WORKER_OUTPUT_INVALID"
    assert body["outcome"]["status"] == "failed"
    assert json.loads(private_path.read_text(encoding="utf-8")) == malformed_private
    shared_path = tmp_path / mapped["host_execution"]["work_files"]["outcomes"]
    assert json.loads(shared_path.read_text(encoding="utf-8"))["outcomes"][0][
        "status"
    ] == "failed"


def test_public_cli_routes_invalid_native_business_result_to_failure_outcome(
    tmp_path: Path,
) -> None:
    """原生回包缺少结构化业务 JSON 时，不能进入 Coordinator 修复死循环。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='invalid-native-result-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    native_path = tmp_path / worker["native_result_path"]
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "agentId": "claude-native-invalid",
        "status": "completed",
        "content": [{"type": "text", "text": "只返回了自然语言，没有业务 JSON"}],
    }), encoding="utf-8")

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "claude-native-invalid",
            "--actual-model", "unreported",
            "--isolation-evidence", "fresh_context",
            "--native-result-file", str(native_path),
            "--project-root", str(tmp_path),
        ],
    )

    assert recorded.exit_code == 0, recorded.output
    body = _last_json_line(recorded.output)
    assert body["status"] == "worker_outcome_recorded"
    assert body["failure_code"] == "HOST_WORKER_OUTPUT_INVALID"
    assert body["outcome"]["status"] == "failed"


def test_public_cli_finalize_preserves_invalid_native_failure(
    tmp_path: Path,
) -> None:
    """record 与 finalize 串联时不得把已记录失败改写成缺失结果。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='invalid-native-finalize-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    native_path = tmp_path / worker["native_result_path"]
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "agentId": "claude-native-invalid-finalize",
        "status": "completed",
        "content": [{"type": "text", "text": "只有自然语言"}],
    }), encoding="utf-8")

    recorded = runner.invoke(main, [
        "dev-loop", "--record-worker-outcome",
        "--worker-id", worker["worker_id"],
        "--worker-status", "completed",
        "--native-worker-handle", "claude-native-invalid-finalize",
        "--actual-model", "unreported",
        "--isolation-evidence", "fresh_context",
        "--native-result-file", str(native_path),
        "--project-root", str(tmp_path),
    ])
    assert recorded.exit_code == 0, recorded.output
    assert _last_json_line(recorded.output)["failure_code"] == (
        "HOST_WORKER_OUTPUT_INVALID"
    )

    work_files = mapped["host_execution"]["work_files"]
    coordinator = tmp_path / work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text("{}", encoding="utf-8")
    result_file = tmp_path / work_files["result"]
    finalized = runner.invoke(main, [
        "dev-loop", "--finalize-result", str(coordinator),
        "--output-result", str(result_file),
        "--project-root", str(tmp_path),
    ])
    assert finalized.exit_code == 0, finalized.output
    result = _last_json_line(finalized.output)
    assert result["spawned"] is False
    assert result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert "HOST_WORKER_OUTPUT_INVALID" in result["spawn_error"]
    assert "HOST_WORKER_OUTPUT_MISSING" not in result["spawn_error"]


def test_public_cli_fails_closed_with_structured_error_when_native_handle_is_missing(
    tmp_path: Path,
) -> None:
    """缺少原生句柄时停在宿主边界，不写共享 outcomes 或伪造完成事实。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='missing-handle-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
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

    failed = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--actual-model", "unreported",
            "--isolation-evidence", "fresh_context",
            "--project-root", str(tmp_path),
        ],
    )

    assert failed.exit_code == 1, failed.output
    body = _last_json_line(failed.output)
    assert body["error_code"] == "HOST_WORKER_ATTESTATION_MISSING"
    assert body["worker_id"] == worker["worker_id"]
    assert body["stop_reason"] == "native_worker_handle_missing"
    assert not (tmp_path / mapped["host_execution"]["work_files"]["outcomes"]).exists()


def test_public_cli_records_native_result_when_worker_did_not_write_private_outcome(
    tmp_path: Path,
) -> None:
    """原生返回漏写 outcome 时，公开 CLI 不应把可恢复问题升级为人工 Gate。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='native-result-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    native_path = tmp_path / worker["native_result_path"]
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "agentId": "claude-native-1",
        "content": [{
            "type": "text",
            "text": "```json\n{\"batch_id\":\"B1\","
            "\"test_results\":{\"passed\":8}}\n```",
        }],
    }), encoding="utf-8")

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "claude-native-1",
            "--native-result-file", str(native_path),
            "--actual-model", "unreported",
            "--isolation-evidence", "fresh_context",
            "--project-root", str(tmp_path),
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    private = json.loads(
        (tmp_path / worker["outcome_path"]).read_text(encoding="utf-8")
    )
    assert private["worker_id"] == worker["worker_id"]
    assert private["payload"]["batch_id"] == "B1"
    assert _last_json_line(recorded.output)["status"] == "worker_outcome_recorded"


def test_public_cli_can_stage_native_result_from_stdin(
    tmp_path: Path,
) -> None:
    """宿主无需先用 shell 写临时文件即可完成同一回写边界。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='native-stdin-fixture'\n", encoding="utf-8"
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

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    native_result = {
        "agentId": "claude-native-stdin-1",
        "content": [{
            "type": "text",
            "text": "```json\n{\"batch_id\":\"B1\","
            "\"test_results\":{\"passed\":9}}\n```",
        }],
    }

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "claude-native-stdin-1",
            "--native-result-file", worker["native_result_path"],
            "--native-result-stdin",
            "--actual-model", "unreported",
            "--isolation-evidence", "fresh_context",
            "--project-root", str(tmp_path),
        ],
        input=json.dumps(native_result, ensure_ascii=False),
    )

    assert recorded.exit_code == 0, recorded.output
    native_path = tmp_path / worker["native_result_path"]
    assert json.loads(native_path.read_text(encoding="utf-8")) == native_result
    private = json.loads(
        (tmp_path / worker["outcome_path"]).read_text(encoding="utf-8")
    )
    assert private["payload"]["test_results"]["passed"] == 9


def test_tick_preflight_projects_attestation_repair_before_worker_failure(
    tmp_path: Path,
) -> None:
    """宿主漏回写不能先消耗 Core 的 Worker 失败预算。"""
    from auto_engineering.cli.dev_loop import (
        _project_submitted_worker_failure_recovery,
    )
    from auto_engineering.host.path_contract import worker_outcome_path
    from auto_engineering.host.spawn_contract import WorkerInvocationSpec

    invocation = WorkerInvocationSpec(
        worker_id="architect-0",
        role="architect",
        prompt_ref=".ae-state/effects/prompt/worker.txt",
        prompt_sha256="a" * 64,
        requested_effort="xhigh",
        isolation="fresh_context",
        capabilities={
            "may_drive_loop": False,
            "may_spawn_workers": False,
        },
        receipt_path=".ae-state/spawn-proofs/architect-0.json",
        outcome_path=".ae-state/host-runtime/worker-outcomes/architect-0.json",
    )
    invocation = WorkerInvocationSpec(
        **{
            **invocation.to_dict(),
            "outcome_path": worker_outcome_path(
                "architect-action-preflight", "architect-0", 1
            ),
        }
    )
    action = {
        "schema_version": "1.1",
        "message_id": "architect-action-preflight",
        "thread_id": "thread-preflight",
        "stage": "architect",
        "action": "architect",
        "project_root": str(tmp_path),
        "execution_generation": 1,
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "parallel": False,
            "effort": "xhigh",
            "invocations": [invocation.to_dict()],
        },
        "host_execution": {
            "platform": "codex",
            "workers": [{
                "worker_id": invocation.worker_id,
                "outcome_path": invocation.outcome_path,
                "record_worker_outcome": {
                    "argv_template": ["runner", "--record-worker-outcome"],
                },
            }],
            "work_files": {
                "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                "coordinator_result": (
                    ".ae-state/host-runtime/work/a/coordinator-result.json"
                ),
                "result": ".ae-state/host-runtime/work/a/result.json",
            },
        },
    }
    private_path = tmp_path / invocation.outcome_path
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": invocation.worker_id,
        "status": "completed",
        "payload": {"plan": "按设计实现"},
        "summary": "Architect 已完成规划",
    }), encoding="utf-8")
    journal_path = (
        tmp_path / ".ae-state/host-runtime/outcomes/"
        / f"{action['message_id']}.json"
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps({"status": "worker_failed", "failure_attempt": 2}),
        encoding="utf-8",
    )

    recovered = _project_submitted_worker_failure_recovery(
        action=action,
        submitted_result={
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_FAILED",
            "spawn_retry_attempt": 1,
        },
        root=tmp_path,
    )

    assert recovered is not None
    assert recovered["host_execution"]["recovery"]["status"] == (
        "worker_attestation_pending"
    )
    assert recovered["host_execution"]["recovery"]["spawn_permitted"] is False
    assert "spawn" not in recovered
    assert recovered["host_execution"]["recovery"]["record_plan"]["count"] == 1


def test_tick_preflight_projects_native_result_repair_before_worker_failure(
    tmp_path: Path,
) -> None:
    """原生回包已落盘但漏调用 record 时不得消费 Worker 失败预算。"""
    from auto_engineering.cli.dev_loop import (
        _project_submitted_worker_failure_recovery,
    )
    from auto_engineering.host.path_contract import (
        worker_native_result_path,
        worker_outcome_path,
    )
    from auto_engineering.host.spawn_contract import WorkerInvocationSpec

    invocation = WorkerInvocationSpec(
        worker_id="architect-0",
        role="architect",
        prompt_ref=".ae-state/effects/prompt/worker.txt",
        prompt_sha256="b" * 64,
        requested_effort="xhigh",
        isolation="fresh_context",
        capabilities={
            "may_drive_loop": False,
            "may_spawn_workers": False,
        },
        receipt_path=".ae-state/spawn-proofs/architect-0.json",
        outcome_path=worker_outcome_path("native-result-repair", "architect-0", 1),
    )
    native_ref = worker_native_result_path(
        "native-result-repair", "architect-0", 1
    )
    action = {
        "schema_version": "1.1",
        "message_id": "native-result-repair",
        "thread_id": "thread-native-result-repair",
        "stage": "architect",
        "action": "architect",
        "project_root": str(tmp_path),
        "execution_generation": 1,
        "spawn": {
            "contract_version": "1.0",
            "count": 1,
            "parallel": False,
            "effort": "xhigh",
            "invocations": [invocation.to_dict()],
        },
        "host_execution": {
            "platform": "claude-code",
            "workers": [{
                "worker_id": invocation.worker_id,
                "outcome_path": invocation.outcome_path,
                "native_result_path": native_ref,
                "record_worker_outcome": {
                    "argv_template": ["runner", "--record-worker-outcome"],
                },
            }],
            "work_files": {
                "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                "coordinator_result": (
                    ".ae-state/host-runtime/work/a/coordinator-result.json"
                ),
                "result": ".ae-state/host-runtime/work/a/result.json",
            },
        },
    }
    native_path = tmp_path / native_ref
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(
        json.dumps({"retrieval_status": "success", "result": "structured"}),
        encoding="utf-8",
    )

    recovered = _project_submitted_worker_failure_recovery(
        action=action,
        submitted_result={
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_FAILED",
            "spawn_retry_attempt": 1,
        },
        root=tmp_path,
    )

    assert recovered is not None
    assert recovered["host_execution"]["recovery"]["status"] == (
        "worker_attestation_pending"
    )
    assert recovered["host_execution"]["recovery"]["detail"] == (
        "native_result_ready_without_record_worker_outcome"
    )
    assert recovered["host_execution"]["recovery"]["spawn_permitted"] is False
    assert "spawn" not in recovered
    assert recovered["host_execution"]["recovery"]["record_plan"]["count"] == 1



def test_public_init_blocks_any_older_unfinished_event_thread(
    tmp_path: Path,
) -> None:
    """较新的终态 thread 不能掩盖较早的未终态 thread。"""

    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    def append_event(thread_id: str, event_type: LoopEventType, payload: dict) -> None:
        events.append([LoopEvent.create(
            thread_id=thread_id,
            sequence=events.next_sequence(thread_id),
            event_type=event_type,
            payload=payload,
            correlation_id=thread_id,
        )])

    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    with SQLiteEventStore(state_dir / "events.db") as events:
        append_event("unfinished-thread", LoopEventType.LOOP_INITIALIZED, {})
        append_event("finished-thread", LoopEventType.LOOP_INITIALIZED, {})
        append_event("finished-thread", LoopEventType.LOOP_COMPLETED, {})

    result = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "PROJECT_THREAD_ACTIVE" in result.output
    assert "unfinished-thread" in result.output


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


def test_worker_execution_identity_reuses_fact_generation_during_native_recovery(
    tmp_path, monkeypatch
) -> None:
    """跨宿主接管时，已有 native-result 必须继续绑定原代路径。"""
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity
    from auto_engineering.host.path_contract import worker_native_result_path
    from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

    monkeypatch.setenv("AE_HOST_PLATFORM", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-a")
    action = {
        "message_id": "action-native-recovery",
        "thread_id": "thread-native-recovery",
        "spawn": {"invocations": [{"worker_id": "architect-0"}]},
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
        platform="claude-code",
        host_session_id="session-a",
    ))
    native_path = tmp_path / worker_native_result_path(
        action["message_id"], "architect-0", 1,
    )
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-b")
    takeover = _bind_worker_execution_identity(action, tmp_path)

    assert takeover["execution_generation"] == 1
    assert takeover["fencing_token"] != first["fencing_token"]


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
    preflight = _bind_worker_execution_identity(
        action, tmp_path, include_failure_journal=False
    )
    assert first["execution_generation"] == 1
    assert retry["execution_generation"] == 2
    assert retry_read["execution_generation"] == 2
    assert preflight["execution_generation"] == 1
    assert retry["fencing_token"] != first["fencing_token"]


def test_worker_retry_ignores_invalid_prior_native_artifact(
    tmp_path, monkeypatch
) -> None:
    """非法旧 native 回包不能占住重试代际并制造 outcomes 冲突。"""
    from auto_engineering.cli.dev_loop import _bind_worker_execution_identity
    from auto_engineering.host.path_contract import worker_native_result_path
    from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

    monkeypatch.setenv("AE_HOST_PLATFORM", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-a")
    action = {
        "message_id": "action-invalid-native-retry",
        "thread_id": "thread-invalid-native-retry",
        "spawn": {"invocations": [{"worker_id": "developer-0"}]},
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
        platform="claude-code",
        host_session_id="session-a",
    ))
    native_path = tmp_path / worker_native_result_path(
        action["message_id"], "developer-0", 1,
    )
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(json.dumps({
        "status": "completed",
        "content": [{"type": "text", "text": "not a business JSON"}],
    }), encoding="utf-8")
    journal = tmp_path / ".ae-state/host-runtime/outcomes/action-invalid-native-retry.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({
        "status": "worker_failed",
        "failure_attempt": 1,
    }), encoding="utf-8")

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-b")
    retry = _bind_worker_execution_identity(action, tmp_path)

    assert first["execution_generation"] == 1
    assert retry["execution_generation"] == 2


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

    private_path = tmp_path / prepared_worker["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(json.dumps({
        "worker_id": prepared_worker["worker_id"],
        "status": "completed",
        "payload": {"plan": "按设计实现"},
        "summary": "Worker 已完成业务产出",
    }), encoding="utf-8")
    resumed = _prepare_action_for_host(action, tmp_path, compact_view=False)
    assert "spawn" not in resumed
    assert resumed["host_execution"]["recovery"]["status"] == (
        "worker_attestation_pending"
    )
    assert resumed["host_execution"]["recovery"]["spawn_permitted"] is False


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
    work_dir.mkdir(parents=True, exist_ok=True)
    result_file = work_dir / "result.json"
    result_file.write_text("{}", encoding="utf-8")

    _cleanup_completed_action_work_files(
        root=tmp_path,
        result_file=result_file,
        completed_action=action,
        next_action={"message_id": "next-action"},
    )

    assert not private_path.exists()


def test_cleanup_preserves_work_files_until_core_accepts_result(
    tmp_path, monkeypatch
) -> None:
    """Core 拒绝候选 Result 时必须保留工作文件供同一 Action 修复。"""

    from auto_engineering.cli.dev_loop import _cleanup_completed_action_work_files

    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "session-cleanup-repair")
    message_id = "action-cleanup-repair"
    import hashlib
    work_dir = tmp_path / ".ae-state/host-runtime/work/" / hashlib.sha256(
        message_id.encode()
    ).hexdigest()[:24]
    work_dir.mkdir(parents=True, exist_ok=True)
    files = {
        name: work_dir / name
        for name in ("outcomes.json", "coordinator-result.json", "result.json")
    }
    for path in files.values():
        path.write_text("{}", encoding="utf-8")

    _cleanup_completed_action_work_files(
        root=tmp_path,
        result_file=files["result.json"],
        completed_action={"message_id": message_id},
        next_action={"message_id": "next-action"},
        commit_confirmed=False,
    )

    assert all(path.exists() for path in files.values())


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

    def spy(action, root, **kwargs):
        calls.append((action, root))
        return action

    monkeypatch.setattr(dev_loop_module, "_map_bound_action_for_host", spy)
    dev_loop_module.run_tick_status(tmp_path)

    assert calls


def test_status_reports_legacy_active_action_without_crashing(tmp_path, monkeypatch, capsys) -> None:
    """旧在途 Action 只能给出稳定恢复提示，不能让 status 裸崩。"""
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.setattr(
        dev_loop_module,
        "_load_active_action",
        lambda thread_id, events: {
            "message_id": "legacy-action",
            "thread_id": thread_id,
            "action": "developer",
            "stage": "developer",
            "spawn": {"agents": []},
        },
    )
    from auto_engineering.host.spawn_contract import SpawnContractError
    monkeypatch.setattr(
        dev_loop_module,
        "_map_bound_action_for_host",
        lambda action, root, **kwargs: (_ for _ in ()).throw(
            SpawnContractError("SPAWN_LEGACY_FIELD_REJECTED")
        ),
    )

    dev_loop_module.run_tick_status(tmp_path)
    summary = json.loads(capsys.readouterr().out)

    assert summary["active_action_error"] == "SPAWN_LEGACY_FIELD_REJECTED"
    assert summary["recovery_required"] is True


def test_active_action_uses_event_store_as_the_only_source() -> None:
    """正常运行只消费 EventStore，不从其他状态源拼接 Action。"""

    from auto_engineering.cli.dev_loop import _load_active_action

    class Events:
        def load_action_snapshot(self, thread_id):
            return {"message_id": "event-action", "thread_id": thread_id}

    assert _load_active_action("thread-1", Events()) == {
        "message_id": "event-action",
        "thread_id": "thread-1",
    }


def test_active_event_action_is_authoritative_without_state_splicing() -> None:
    """EventStore 有 Action 时不得从其他状态源补宿主字段。"""

    from auto_engineering.cli.dev_loop import _load_active_action

    event_action = {"message_id": "same-action", "thread_id": "thread-1"}
    class Events:
        def load_action_snapshot(self, thread_id):
            return event_action

    assert _load_active_action("thread-1", Events()) == event_action


def test_active_action_does_not_fall_back_when_event_is_missing() -> None:
    """EventStore 缺少 Action 时必须返回空值，不能消费第二状态源。"""

    from auto_engineering.cli.dev_loop import _load_active_action

    class Events:
        def load_action_snapshot(self, thread_id):
            return None

    assert _load_active_action("thread-1", Events()) is None


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


def test_status_reports_recovery_required_on_design_source_drift(
    tmp_path, monkeypatch
) -> None:
    """历史状态的设计源漂移必须稳定报告恢复要求，不输出 traceback。"""

    from auto_engineering.cli import main
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output

    def raise_source_drift(*_args, **_kwargs):
        raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")

    monkeypatch.setattr(
        TickOrchestrator, "restore_from_event_store", raise_source_drift
    )
    result = CliRunner().invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["active_action_error"] == "DESIGN_LEDGER_SOURCE_MISMATCH"
    assert payload["recovery_required"] is True
    assert "Traceback" not in result.output


def test_status_projects_persisted_state_reconciliation_gate_after_design_drift(
    tmp_path, monkeypatch
) -> None:
    """已持久化的恢复 Gate 不应被设计源漂移遮蔽成另一种错误。"""

    from auto_engineering.cli import main
    dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    thread_id = _last_json_line(initialized.output)["thread_id"]
    gate = {
        "message_id": "gate-1",
        "thread_id": thread_id,
        "tick": 2,
        "stage": "developer",
        "action": "gate",
        "gate": {"id": "state_reconciliation", "options": [{"id": "reinitialize"}]},
        "expected_format": {"gate_resolution": {"gate_id": "state_reconciliation"}},
    }

    monkeypatch.setattr(
        TickOrchestrator,
        "restore_from_event_store",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")
        ),
    )
    monkeypatch.setattr(dev_loop_module, "_load_active_action", lambda *_args: gate)

    result = CliRunner().invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["active_action"]["action"] == "gate"
    assert payload["active_action"]["gate"]["id"] == "state_reconciliation"
    assert "active_action_error" not in payload


def test_tick_returns_protocol_error_on_design_source_drift(
    tmp_path, monkeypatch
) -> None:
    """tick 恢复设计源漂移时必须返回协议错误，而不是中断宿主进程。"""

    from auto_engineering.cli import main
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    result_file = tmp_path / "result.json"
    result_file.write_text("{}", encoding="utf-8")

    def raise_source_drift(*_args, **_kwargs):
        raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")

    monkeypatch.setattr(
        TickOrchestrator, "restore_from_event_store", raise_source_drift
    )
    result = CliRunner().invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["action"] == "error"
    assert payload["error_code"] == "DESIGN_LEDGER_SOURCE_MISMATCH"
    assert "Traceback" not in result.output


def test_validate_returns_protocol_error_on_design_source_drift(
    tmp_path, monkeypatch
) -> None:
    """validate 恢复设计源漂移时必须返回稳定错误且不校验旧 Result。"""

    from auto_engineering.cli import main
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    result_file = tmp_path / "result.json"
    result_file.write_text("{}", encoding="utf-8")

    def raise_source_drift(*_args, **_kwargs):
        raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")

    monkeypatch.setattr(
        TickOrchestrator, "restore_from_event_store", raise_source_drift
    )
    result = CliRunner().invoke(
        main,
        [
            "dev-loop", "--validate-result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _last_json_line(result.output)
    assert payload["action"] == "error"
    assert payload["error_code"] == "DESIGN_LEDGER_SOURCE_MISMATCH"
    assert "Traceback" not in result.output


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


def test_finalize_reports_exhausted_result_repair_without_traceback(
    tmp_path, monkeypatch, capsys
) -> None:
    """修复预算耗尽时，公开 Finalizer 必须返回结构化错误而非 traceback。"""

    from auto_engineering.cli.dev_loop import run_tick_finalize
    from auto_engineering.host.execution_assembler import HostExecutionAssembler
    from auto_engineering.host.outcome_journal import OutcomeJournalTransitionError

    initialized = CliRunner().invoke(
        main,
        ["dev-loop", "--init", "实现登录功能", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    action = _last_json_line(initialized.output)
    work_files = action["host_execution"]["work_files"]
    coordinator = tmp_path / work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text("{}", encoding="utf-8")

    def raise_exhausted(*_args, **_kwargs):
        raise OutcomeJournalTransitionError("OUTCOME_REPAIR_EXHAUSTED")

    monkeypatch.setattr(HostExecutionAssembler, "finalize", raise_exhausted)
    monkeypatch.setattr(HostExecutionAssembler, "finalize_to_file", raise_exhausted)
    run_tick_finalize(None, coordinator, tmp_path)

    payload = _last_json_line(capsys.readouterr().out)
    assert payload["action"] == "error"
    assert payload["error_code"] == "HOST_RESULT_REPAIR_EXHAUSTED"



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
        # 新运行只创建 EventStore，不生成第二套持久化状态。
        assert (tmp_path / ".ae-state" / "events.db").exists()
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
        work_files = action["host_execution"]["work_files"]
        coordinator_file = tmp_path / work_files["coordinator_result"]
        result_file = tmp_path / work_files["result"]
        coordinator_file.parent.mkdir(parents=True, exist_ok=True)
        coordinator_file.write_text(json.dumps({
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src", "tests"],
        }), encoding="utf-8")

        finalized = runner.invoke(
            main,
            [
                "dev-loop", "--finalize-result", str(coordinator_file),
                "--output-result", str(result_file),
                "--project-root", str(tmp_path),
            ],
        )
        assert finalized.exit_code == 0, finalized.output
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

    def test_node_project_setup_accepts_marked_entry_via_public_cli(
        self, tmp_path
    ) -> None:
        """公开 CLI 不得把 Node 工具链的最小入口误判为业务实现。"""
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
        (tmp_path / "src" / "main.js").write_text(
            "// setup smoke entry — replaced after architect stage\n"
            "export {};\n",
            encoding="utf-8",
        )
        (tmp_path / "tests" / "smoke.test.js").write_text(
            "// setup smoke\n", encoding="utf-8"
        )
        (tmp_path / "package.json").write_text(json.dumps({
            "scripts": {
                "test": "node -e \"console.log('test passed')\"",
                "lint": "node -e \"console.log('lint passed')\"",
                "typecheck": "node -e \"console.log('typecheck passed')\"",
                "build": "node -e \"console.log('build passed')\"",
            },
        }), encoding="utf-8")
        work_files = action["host_execution"]["work_files"]
        coordinator_file = tmp_path / work_files["coordinator_result"]
        result_file = tmp_path / work_files["result"]
        coordinator_file.parent.mkdir(parents=True, exist_ok=True)
        coordinator_file.write_text(json.dumps({
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src/main.js", "tests/smoke.test.js"],
        }), encoding="utf-8")

        finalized = runner.invoke(main, [
            "dev-loop", "--finalize-result", str(coordinator_file),
            "--output-result", str(result_file), "--project-root", str(tmp_path),
        ])
        assert finalized.exit_code == 0, finalized.output
        validated = runner.invoke(main, [
            "dev-loop", "--validate-result", str(result_file),
            "--project-root", str(tmp_path),
        ])
        assert validated.exit_code == 0, validated.output
        ticked = runner.invoke(main, [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ])

        assert ticked.exit_code == 0, ticked.output
        assert _last_json_line(ticked.output)["stage"] == "gap_scan"

    def test_project_setup_failure_result_is_bounded_across_public_cli_ticks(
        self, tmp_path
    ) -> None:
        """公开 CLI 必须把宿主失败逐 Tick 交回 Core，第三次进入 WAIT_RESOURCE。"""
        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现一个页面", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)
        assert action["action"] == "project_setup_required"

        for attempt in range(1, 4):
            work_files = action["host_execution"]["work_files"]
            coordinator = tmp_path / work_files["coordinator_result"]
            result = tmp_path / work_files["result"]
            coordinator.parent.mkdir(parents=True, exist_ok=True)
            coordinator.write_text(json.dumps({
                "result_type": "project_setup_failed",
                "artifacts": [],
                "failure_code": "PROJECT_SETUP_BUILD_FAILED",
                "failure_summary": "构建产物包含绝对路径 symlink",
                "attempts_in_action": 2,
            }), encoding="utf-8")
            finalized = runner.invoke(main, [
                "dev-loop", "--finalize-result", str(coordinator),
                "--output-result", str(result), "--project-root", str(tmp_path),
            ])
            assert finalized.exit_code == 0, finalized.output
            validated = runner.invoke(main, [
                "dev-loop", "--validate-result", str(result),
                "--project-root", str(tmp_path),
            ])
            assert validated.exit_code == 0, validated.output
            retryable_result = result.read_bytes()
            ticked = runner.invoke(main, [
                "dev-loop", "--tick", "--result", str(result),
                "--project-root", str(tmp_path),
            ])
            assert ticked.exit_code == 0, ticked.output
            action = _last_json_line(ticked.output)
            if attempt < 3:
                assert action["action"] == "project_setup_required"
                assert action["setup_failure_streak"] == attempt

        assert action["action"] == "resource_wait"
        assert action["reason_code"] == "PROJECT_SETUP_RETRY_EXHAUSTED"
        assert action["setup_failure_streak"] == 3

        from auto_engineering.loop.event_store import SQLiteEventStore

        with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
            event_count_before_yield_replay = len(events.load_stream(action["thread_id"]))

        # WAIT_RESOURCE 是当前宿主调用的 yield 边界；即使宿主按当前等待
        # Action 重新生成 Result，CLI 也只能返回同一等待视图，不能继续消费 Tick。
        retry_payload = json.loads(retryable_result)
        retry_payload["message_id"] = "setup-after-resource-wait"
        retry_payload["causation_id"] = action["message_id"]
        retry_payload["tick"] = action["tick"]
        wait_result = tmp_path / action["host_execution"]["work_files"]["result"]
        wait_result.parent.mkdir(parents=True, exist_ok=True)
        wait_result.write_text(json.dumps(retry_payload), encoding="utf-8")
        replayed = runner.invoke(main, [
            "dev-loop", "--tick", "--result", str(wait_result),
            "--project-root", str(tmp_path),
        ])
        assert replayed.exit_code == 0, replayed.output
        replayed_action = _last_json_line(replayed.output)
        assert replayed_action["action"] == "resource_wait"
        assert replayed_action["reason_code"] == "PROJECT_SETUP_RETRY_EXHAUSTED"
        assert replayed_action["setup_failure_streak"] == 3
        assert replayed_action["active_action_message_id"] == action["active_action_message_id"]

        with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
            assert len(events.load_stream(action["thread_id"])) == event_count_before_yield_replay

        # WAIT_RESOURCE 仍允许宿主在修复项目能力后恢复原 Setup Action。
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
        recovery_files = replayed_action["host_execution"]["work_files"]
        recovery_coordinator = tmp_path / recovery_files["coordinator_result"]
        recovery_result = tmp_path / recovery_files["result"]
        recovery_coordinator.parent.mkdir(parents=True, exist_ok=True)
        recovery_coordinator.write_text(json.dumps({
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src", "tests"],
        }), encoding="utf-8")
        recovered = runner.invoke(main, [
            "dev-loop", "--finalize-result", str(recovery_coordinator),
            "--output-result", str(recovery_result), "--project-root", str(tmp_path),
        ])
        assert recovered.exit_code == 0, recovered.output
        recovered_validation = runner.invoke(main, [
            "dev-loop", "--validate-result", str(recovery_result),
            "--project-root", str(tmp_path),
        ])
        assert recovered_validation.exit_code == 0, recovered_validation.output
        recovered_tick = runner.invoke(main, [
            "dev-loop", "--tick", "--result", str(recovery_result),
            "--project-root", str(tmp_path),
        ])
        assert recovered_tick.exit_code == 0, recovered_tick.output
        assert _last_json_line(recovered_tick.output)["action"] == "architect"


class TestStatusMode:
    def test_status_action_summary_exposes_current_gap_and_work_contract(
        self,
    ) -> None:
        from auto_engineering.cli.dev_loop import _status_action_summary

        summary = _status_action_summary({
            "message_id": "action-7",
            "correlation_id": "thread-1",
            "causation_id": "result-6",
            "thread_id": "thread-1",
            "tick": 2,
            "action": "gap_review",
            "stage": "gap_review",
            "current_gap_index": 1,
            "total_gaps": 3,
            "current_gap": {"id": "gap-2", "summary": "缺少接口错误合同"},
            "gap_review_contract": {
                "display_scope": "current_gap_only",
                "decision_count": 1,
                "gap_id_source": "current_gap.id",
                "forbidden_context": [
                    "historical_gap_scan_gaps",
                    "future_gap_details",
                    "batch_decisions",
                ],
            },
            "work_files": {"result": ".ae-state/work/action-7/result.json"},
            "expected_format": {"decision": {"gap_id": "string"}},
            "context": {"private": "must-not-leak"},
        })

        assert summary == {
            "message_id": "action-7",
            "correlation_id": "thread-1",
            "causation_id": "result-6",
            "thread_id": "thread-1",
            "tick": 2,
            "action": "gap_review",
            "stage": "gap_review",
            "current_gap_index": 1,
            "total_gaps": 3,
            "current_gap": {"id": "gap-2", "summary": "缺少接口错误合同"},
            "gap_review_contract": {
                "display_scope": "current_gap_only",
                "decision_count": 1,
                "gap_id_source": "current_gap.id",
                "forbidden_context": [
                    "historical_gap_scan_gaps",
                    "future_gap_details",
                    "batch_decisions",
                ],
            },
            "work_files": {"result": ".ae-state/work/action-7/result.json"},
            "expected_format": {"decision": {"gap_id": "string"}},
        }

    def test_status_action_summary_exposes_issued_build_identity(self) -> None:
        from auto_engineering.cli.dev_loop import _status_action_summary

        summary = _status_action_summary({
            "message_id": "action-7",
            "extensions": {
                "ae": {
                    "runtime_revision": {
                        "engine_build_id": "build-issued",
                    },
                },
            },
        })

        assert summary["runtime_identity"] == {
            "engine_build_id": "build-issued",
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
        payload = _last_json_line(status.output)
        assert payload["current_stage"] == "project_setup"
        assert payload["runtime_identity"]["status"] == "match"

    def test_init_then_status_roundtrip(self, tmp_path) -> None:
        """--init 落 EventStore → 独立 --status 调用恢复并输出状态."""
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

    def test_resume_reloads_same_active_action_from_event_store(self, tmp_path) -> None:
        """新的 CLI 调用必须从 EventStore 恢复同一个 active Action。"""

        environment = dict(os.environ)
        source_root = str(Path(__file__).parents[1])
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (source_root, environment.get("PYTHONPATH")) if item
        )

        def run_cli(*arguments: str) -> dict:
            completed = subprocess.run(
                [str(Path(source_root) / "scripts" / "ae-run"), *arguments],
                cwd=tmp_path,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr or completed.stdout
            return _last_json_line(completed.stdout)

        initial_action = run_cli(
            "dev-loop", "--init", "实现跨进程恢复", "--project-root", str(tmp_path),
        )
        assert (tmp_path / ".ae-state" / ".ae-runtime" / "bin" / "python").is_file()

        resumed_action = run_cli(
            "dev-loop", "--resume", initial_action["thread_id"],
            "--project-root", str(tmp_path),
        )

        assert resumed_action["thread_id"] == initial_action["thread_id"]
        assert resumed_action["message_id"] == initial_action["message_id"]
        assert resumed_action["tick"] == initial_action["tick"]
        assert resumed_action["stage"] == initial_action["stage"]
        assert resumed_action.get("spawn") == initial_action.get("spawn")

    def test_status_without_event_store_errors(self, tmp_path) -> None:
        """无 EventStore → restore raise → 非零退出 (不静默假成功)."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--status", "--project-root", str(tmp_path)])
        assert result.exit_code != 0

    def test_status_does_not_use_terminal_lease_as_event_fact(
        self, tmp_path, monkeypatch,
    ) -> None:
        from dataclasses import replace

        from auto_engineering.host.runtime_driver import (
            HostRunLease,
            HostRunLeaseStore,
        )

        runner = CliRunner()
        initialized = runner.invoke(
            main,
            ["dev-loop", "--init", "实现 X", "--project-root", str(tmp_path)],
        )
        assert initialized.exit_code == 0, initialized.output
        action = _last_json_line(initialized.output)
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
        assert summary["current_stage"] == "project_setup"
        assert summary["expected_stage"] == "project_setup"

        generic = runner.invoke(
            main, ["status", "--format", "json", "--project-root", str(tmp_path)],
        )
        assert generic.exit_code == 0, generic.output
        generic_summary = json.loads(generic.output)
        assert generic_summary["thread_id"] == action["thread_id"]
        assert generic_summary["stage"] == "project_setup"


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
        work_files = action["host_execution"]["work_files"]
        payload = tmp_path / work_files["coordinator_result"]
        payload.parent.mkdir(parents=True, exist_ok=True)
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
                str(tmp_path / "stale-coordinator-result.json"),
                "--output-result",
                str(tmp_path / "stale-result.json"),
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
        canonical_result = tmp_path / work_files["result"]
        assert json.loads(
            canonical_result.read_text(encoding="utf-8")
        ) == finalized
        assert not (tmp_path / "stale-result.json").exists()

    def test_finalize_missing_spawn_outputs_becomes_worker_failure(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """真实 CLI Finalizer 不得把 spawn 空交接误报为输入错误。"""
        dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")
        from auto_engineering.host.spawn_contract import WorkerInvocationSpec
        from auto_engineering.loop import event_store as event_store_module

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
            outcome_path=".ae-state/host-runtime/worker-outcomes/architect-0.json",
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

        class FakeEvents:
            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs

            def unfinished_threads(self) -> list[str]:
                return ["thread-1"]

            def load_action_snapshot(self, thread_id: str):
                assert thread_id == "thread-1"
                return action

            def close(self) -> None:
                pass

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

    def test_finalize_private_outcome_enters_host_attestation_repair(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """私有 outcome 存在时不得推进 Worker 失败代际或重新 spawn。"""
        dev_loop_module = importlib.import_module("auto_engineering.cli.dev_loop")
        from auto_engineering.host.spawn_contract import WorkerInvocationSpec
        from auto_engineering.loop import event_store as event_store_module

        invocation = WorkerInvocationSpec(
            worker_id="architect-0",
            role="architect",
            prompt_ref=".ae-state/effects/prompt/worker.txt",
            prompt_sha256="a" * 64,
            requested_effort="xhigh",
            isolation="fresh_context",
            capabilities={
                "may_drive_loop": False,
                "may_spawn_workers": False,
            },
            receipt_path=".ae-state/spawn-proofs/architect-0.json",
            outcome_path=".ae-state/host-runtime/worker-outcomes/architect-0.json",
        )
        action = {
            "schema_version": "1.1",
            "message_id": "architect-action-attestation-repair",
            "thread_id": "thread-attestation-repair",
            "stage": "architect",
            "action": "architect",
            "spawn": {
                "contract_version": "1.0",
                "count": 1,
                "parallel": False,
                "effort": "xhigh",
                "invocations": [invocation.to_dict()],
            },
            "host_execution": {
                "platform": "codex",
                "workers": [{
                    "worker_id": "architect-0",
                    "prompt_ref": invocation.prompt_ref,
                    "outcome_path": invocation.outcome_path,
                    "record_worker_outcome": {
                        "argv_template": ["runner", "--record-worker-outcome"],
                    },
                }],
                "work_files": {
                    "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                    "coordinator_result": (
                        ".ae-state/host-runtime/work/a/coordinator-result.json"
                    ),
                    "result": ".ae-state/host-runtime/work/a/result.json",
                },
            },
        }

        class FakeEvents:
            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs

            def unfinished_threads(self) -> list[str]:
                return [action["thread_id"]]

            def load_action_snapshot(self, thread_id: str):
                assert thread_id == action["thread_id"]
                return action

            def close(self) -> None:
                pass

        monkeypatch.setattr(event_store_module, "SQLiteEventStore", FakeEvents)
        monkeypatch.setattr(
            dev_loop_module, "_active_thread", lambda store: action["thread_id"]
        )
        monkeypatch.setattr(
            dev_loop_module, "_map_bound_action_for_host",
            lambda value, root, **kwargs: value,
        )
        monkeypatch.setattr(dev_loop_module, "_map_action_for_host", lambda value: value)

        private_path = tmp_path / invocation.outcome_path
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_text(json.dumps({
            "worker_id": invocation.worker_id,
            "status": "completed",
            "payload": {"plan": "按设计实现"},
            "summary": "Architect 完成规划",
        }), encoding="utf-8")
        coordinator = tmp_path / "empty-coordinator.json"
        coordinator.write_text("{}", encoding="utf-8")

        from auto_engineering.cli.dev_loop import run_tick_finalize

        run_tick_finalize(
            tmp_path / "missing-outcomes.json",
            coordinator,
            tmp_path,
            output_result_file=tmp_path / "result.json",
        )

        result = _last_json_line(capsys.readouterr().out)
        assert result["action"] == "architect"
        assert "spawn" not in result
        assert result["host_execution"]["recovery"]["status"] == (
            "worker_attestation_pending"
        )
        assert result["host_execution"]["recovery"]["spawn_permitted"] is False
        assert result["host_execution"]["recovery"]["required_operation"] == (
            "record_worker_outcome_then_finalize"
        )
        assert result["result_rejection"]["error_code"] == (
            "HOST_WORKER_ATTESTATION_MISSING"
        )

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
        work_dir.mkdir(parents=True, exist_ok=True)
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
        design.write_text(
            "## B1 设计\n### B1.1 函数\n实现一个函数。\n",
            encoding="utf-8",
        )
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
        first_payload.parent.mkdir(parents=True, exist_ok=True)
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
        current_payload.parent.mkdir(parents=True, exist_ok=True)
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
