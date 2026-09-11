"""P0-E2E：真实 Gap Scan 宿主边界的第一条纵向回归轨迹。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.cli.dev_loop import _compact_host_action
from auto_engineering.host import HostPlatform
from auto_engineering.host.adapters import adapter_for
from auto_engineering.host.execution_assembler import (
    HostEvidenceValidationError,
    HostExecutionAssembler,
    NativeWorkerOutcome,
)
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.loop.architect_plan_coverage import architect_plan_manifest
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _core(project_root: Path, event_store: SQLiteEventStore) -> TickOrchestrator:
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        project_root,
        event_store=event_store,
        guardrail=guardrail,
        gate_runner=lambda names, root: {
            name: MagicMock(passed=True, message="ok") for name in names
        },
    )


def _design_doc(project_root: Path) -> Path:
    path = project_root / "design.md"
    path.write_text(
        "## B1 音色克隆\n\n### C1 上传\n明确上传契约。\n",
        encoding="utf-8",
    )
    return path


def test_single_invocation_gap_scan_accepts_semantic_output_without_machine_echo(
    tmp_path: Path,
) -> None:
    """宿主只提交语义结果时，生产链应自动绑定机器事实并继续。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='p0-e2e-fixture'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init(
            "按设计实现音色克隆页面",
            design_doc_path=str(_design_doc(tmp_path)),
        )
        assert action["stage"] == "gap_scan"

        adapter = adapter_for(HostPlatform.CODEX)
        profile = adapter.profile(
            detected=adapter.capabilities,
            authorized=adapter.capabilities,
        )
        mapped_action = adapter.map_action(action, profile=profile).payload
        compact_action = _compact_host_action(mapped_action, tmp_path)
        prompt_ref = compact_action["coordinator_prompt_ref"]
        prompt_text = (tmp_path / prompt_ref["path"]).read_text(encoding="utf-8")
        # 语义输入来自 Host Execution Package 的 Prompt Artifact，而不是
        # Canonical Action 私有 context；测试本身必须遵守真实宿主边界。
        assert "host_design_sections" in prompt_text
        assert "section_id" not in prompt_text
        semantic_output = {
            "gaps": [],
            "section_findings": [
                {
                    "section_ref": "§C1",
                    "verdict": "clear",
                    "evidence": ["设计章节已给出可核验的上传契约。"],
                }
            ],
        }

        assembler = HostExecutionAssembler(tmp_path)
        try:
            result = assembler.finalize(
                action=mapped_action,
                outcomes=[],
                coordinator_payload=semantic_output,
            )
        except HostEvidenceValidationError as exc:
            pytest.fail(
                "生产宿主仍要求 Agent 复制 Core-owned 字段，"
                f"而不是自动组装 canonical Result: {exc.violations}"
            )

        next_action = core.tick_dict(result)
        OutcomeJournal(tmp_path).complete_from_core(result, next_action)

    assert next_action["stage"] in {"architect", "gap_review"}
    assert next_action["action"] != "error"
    journal = tmp_path / ".ae-state/host-runtime/outcomes" / f"{action['message_id']}.json"
    persisted = json.loads(journal.read_text(encoding="utf-8"))
    assert persisted["status"] == "accepted"


def test_public_cli_gap_scan_finalize_validate_tick_roundtrip(tmp_path: Path) -> None:
    """公开 CLI 必须完成 init→finalize→validate→tick 的单 Action 轨迹。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()

    initialized = runner.invoke(
        main,
        [
            "dev-loop", "--init", "按设计实现音色克隆页面",
            "--design-doc", str(design), "--project-root", str(tmp_path),
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    action = json.loads(initialized.output.strip().splitlines()[-1])
    assert action["stage"] == "gap_scan"

    work_files = action["host_execution"]["work_files"]
    coordinator = tmp_path / work_files["coordinator_result"]
    result_file = tmp_path / work_files["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["设计章节已给出可核验的上传契约。"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    finalized = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(coordinator),
            "--output-result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    assert result_file.is_file()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["causation_id"] == action["message_id"]

    validated = runner.invoke(
        main,
        [
            "dev-loop", "--validate-result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert validated.exit_code == 0, validated.output

    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert ticked.exit_code == 0, ticked.output
    next_action = json.loads(ticked.output.strip().splitlines()[-1])
    assert next_action["action"] != "error"

    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        event_types = [
            event.event_type.value
            for event in events.load_stream(action["thread_id"])
        ]
    assert "ResultAccepted" in event_types
    assert "ActionIssued" in event_types

    # 正常运行只创建 EventStore，不创建旧快照数据库。
    assert not (tmp_path / ".ae-state" / "checkpoints.db").exists()


def test_public_cli_duplicate_result_replays_same_next_action(
    tmp_path: Path,
) -> None:
    """公开 CLI 重复提交同一 Result 时必须幂等，不得二次推进。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-idempotency-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()

    initialized = runner.invoke(
        main,
        [
            "dev-loop", "--init", "按设计实现音色克隆页面",
            "--design-doc", str(design), "--project-root", str(tmp_path),
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    initial_action = json.loads(initialized.output.strip().splitlines()[-1])
    coordinator = tmp_path / initial_action["host_execution"]["work_files"][
        "coordinator_result"
    ]
    result_file = tmp_path / initial_action["host_execution"]["work_files"]["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["已核对完整设计文档"],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    finalized = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(coordinator),
            "--output-result", str(result_file), "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    accepted_result = json.loads(result_file.read_text(encoding="utf-8"))

    first = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert first.exit_code == 0, first.output
    first_next_action = json.loads(first.output.strip().splitlines()[-1])

    replay_file = tmp_path / "replay-result.json"
    replay_file.write_text(json.dumps(accepted_result), encoding="utf-8")
    second = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(replay_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert second.exit_code == 0, second.output
    second_next_action = json.loads(second.output.strip().splitlines()[-1])

    assert second_next_action == first_next_action
    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        stream = events.load_stream(initial_action["thread_id"])
    assert sum(event.event_type.value == "ResultAccepted" for event in stream) == 1
    assert sum(event.event_type.value == "ActionIssued" for event in stream) == 2


def test_public_cli_resume_after_worker_outcome_does_not_respawn_worker(
    tmp_path: Path,
) -> None:
    """Worker 回写后宿主进程中断时，恢复必须复用 outcome 而非重复 spawn。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-crash-recovery-e2e'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    source_root = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment["AE_HOST_PLATFORM"] = "codex"
    environment["CODEX_THREAD_ID"] = "public-cli-crash-recovery"
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(source_root), environment.get("PYTHONPATH")) if item
    )

    def invoke_process(*arguments: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from auto_engineering.cli import main; main()",
                "dev-loop",
                *arguments,
                "--project-root",
                str(tmp_path),
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1])

    action = invoke_process("--init", "验证 Worker 中断恢复")
    assert action["stage"] == "architect"
    workers = action["host_execution"]["workers"]  # type: ignore[index]
    worker = workers[0]
    outcome_path = tmp_path / worker["outcome_path"]
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(json.dumps({
        "worker_id": worker["worker_id"],
        "status": "completed",
        "payload": {
            "plan": "按设计完成实现",
            "batch_plan": [{
                "batch_id": "B1",
                "component": "core",
                "tasks": [{
                    "id": "B1-T1",
                    "description": "实现核心",
                    "file_targets": ["src/core.py"],
                }],
            }],
            "file_list": ["src/core.py"],
            "contracts": {},
        },
        "summary": "architect completed before host interruption",
    }, ensure_ascii=False), encoding="utf-8")

    recorded = invoke_process(
        "--record-worker-outcome",
        "--worker-id", worker["worker_id"],
        "--worker-status", "completed",
        "--native-worker-handle", "native-before-crash",
        "--actual-model", "gpt-5.6-sol",
        "--isolation-evidence", "fork_turns=none",
    )
    assert recorded["status"] == "worker_outcome_recorded"

    # 进程在 Coordinator 写入前退出；新进程只能恢复当前 Action，不能重新启动已完成 Worker。
    resumed = invoke_process("--resume", action["thread_id"])
    recovery = resumed["host_execution"]["recovery"]  # type: ignore[index]
    assert recovery["status"] == "native_outcomes_ready"
    assert recovery["spawn_permitted"] is False
    assert "workers" not in resumed["host_execution"]  # type: ignore[operator]
    assert recovery["coordinator_result_ready"] is False
    assert recovery["required_operation"] == "produce_coordinator_then_finalize"


def test_public_cli_worker_failure_preserves_action_for_resource_wait(
    tmp_path: Path,
) -> None:
    """Worker 明确失败时，公开 CLI 必须保留原 active Action 并有界重试。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-failure-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    runner = CliRunner()
    initialized = runner.invoke(
        main,
        ["dev-loop", "--init", "实现失败重试边界", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    action = json.loads(initialized.output.strip().splitlines()[-1])
    assert isinstance(action.get("spawn"), dict)

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    host_execution = mapped["host_execution"]
    worker = host_execution["workers"][0]
    work_files = host_execution["work_files"]
    outcomes_path = tmp_path / work_files["outcomes"]
    coordinator_path = tmp_path / work_files["coordinator_result"]
    result_path = tmp_path / work_files["result"]
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    coordinator_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text(json.dumps({
        "outcomes": [NativeWorkerOutcome(
            worker_id=worker["worker_id"],
            native_worker_handle="codex-native-timeout",
            status="timeout",
            payload={},
            summary="native worker timed out",
            actual_model="fake-codex-model",
            isolation_evidence="fork_turns=none",
            execution_generation=worker.get("execution_generation"),
            fencing_token=worker.get("fencing_token"),
        ).to_dict()],
    }), encoding="utf-8")
    coordinator_path.write_text("{}", encoding="utf-8")

    finalized = runner.invoke(
        main,
        [
            # 故意传 Worker 私有 outcome_path；Finalizer 必须重绑到当前
            # Action 的共享 outcomes，而不能把私有业务文件当宿主证据。
            "dev-loop", "--finalize-result", str(tmp_path / worker["outcome_path"]),
            "--coordinator-result", str(coordinator_path),
            "--output-result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    failure_result = json.loads(result_path.read_text(encoding="utf-8"))

    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert ticked.exit_code == 0, ticked.output
    next_action = json.loads(ticked.output.strip().splitlines()[-1])
    assert next_action["action"] == "resource_wait", next_action
    assert next_action["reason_code"] == "HOST_WORKER_TIMEOUT"
    assert next_action.get("active_action_message_id") == action["message_id"], next_action
    compact = _compact_host_action(next_action, tmp_path)
    assert compact["active_action_message_id"] == action["message_id"]
    assert failure_result["causation_id"] == action["message_id"]

    exhausted_result = dict(failure_result)
    exhausted_result["message_id"] = "worker-timeout-exhausted-result"
    exhausted_result["spawn_retry_attempt"] = 2
    exhausted_path = tmp_path / "worker-timeout-exhausted.json"
    exhausted_path.write_text(
        json.dumps(exhausted_result, ensure_ascii=False), encoding="utf-8"
    )
    exhausted = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(exhausted_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert exhausted.exit_code == 0, exhausted.output
    exhausted_response = json.loads(exhausted.output.strip().splitlines()[-1])
    assert exhausted_response["action"] == "error"
    assert exhausted_response["error_code"] == "HOST_WORKER_TIMEOUT_EXHAUSTED"
    status = runner.invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.output.strip().splitlines()[-1])["active_action"][
        "message_id"
    ] == action["message_id"]


def test_public_cli_business_test_failure_uses_same_action_failure_path(
    tmp_path: Path,
) -> None:
    """Worker 测试失败由宿主确定性导流，不改 outcome 且不伪装成功。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-business-failure-e2e'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    runner = CliRunner()
    initialized = runner.invoke(
        main,
        ["dev-loop", "--init", "实现失败事实回写", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    action = json.loads(initialized.output.strip().splitlines()[-1])

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(action, profile=profile).payload
    worker = mapped["host_execution"]["workers"][0]
    private_path = tmp_path / worker["outcome_path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_business = {
        "worker_id": worker["worker_id"],
        "status": "completed",
        "payload": {
            "batch_id": "B1",
            "files_changed": ["src/VoiceResult.tsx"],
            "test_results": {"passed": 14, "failed": 1, "errors": 0, "total": 15},
            "red_evidence": ["VoiceResult 使用了错误的 API 字段"],
        },
        "summary": "Developer 发现真实业务测试失败",
    }
    private_path.write_text(
        json.dumps(private_business, ensure_ascii=False), encoding="utf-8"
    )

    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", worker["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "native-business-failure",
            "--actual-model", "gpt-5.6-sol",
            "--isolation-evidence", "fork_turns=none",
            "--project-root", str(tmp_path),
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    assert json.loads(private_path.read_text(encoding="utf-8")) == private_business
    outcomes_path = tmp_path / mapped["host_execution"]["work_files"]["outcomes"]
    recorded_outcome = json.loads(outcomes_path.read_text(encoding="utf-8"))["outcomes"][0]
    assert recorded_outcome["status"] == "failed"
    assert recorded_outcome["payload"] == private_business["payload"]

    coordinator_path = tmp_path / mapped["host_execution"]["work_files"]["coordinator_result"]
    result_path = tmp_path / mapped["host_execution"]["work_files"]["result"]
    coordinator_path.parent.mkdir(parents=True, exist_ok=True)
    coordinator_path.write_text("{}", encoding="utf-8")
    finalized = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(outcomes_path),
            "--coordinator-result", str(coordinator_path),
            "--output-result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    failure_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert failure_result["spawned"] is False
    assert failure_result["spawn_error_code"] == "HOST_WORKER_FAILED"
    assert "test_results" not in failure_result

    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert ticked.exit_code == 0, ticked.output
    next_action = json.loads(ticked.output.strip().splitlines()[-1])
    assert next_action["action"] == "resource_wait", next_action
    assert next_action["reason_code"] == "HOST_WORKER_FAILED"
    assert next_action["active_action_message_id"] == action["message_id"]


@pytest.mark.parametrize(
    ("error_code", "resource"),
    [
        ("HOST_AGENT_CAPACITY", "agent_slot"),
        ("HOST_WORKER_OWNER_LOST", "worker_ownership"),
    ],
)
def test_public_cli_host_resource_failure_keeps_same_action_without_worker_result(
    tmp_path: Path,
    error_code: str,
    resource: str,
) -> None:
    """宿主资源/所有权异常时，公开 CLI 只能等待，不能伪造 Worker 结果。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-resource-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    runner = CliRunner()
    initialized = runner.invoke(
        main,
        ["dev-loop", "--init", "验证容量耗尽处置", "--project-root", str(tmp_path)],
    )
    assert initialized.exit_code == 0, initialized.output
    action = json.loads(initialized.output.strip().splitlines()[-1])
    assert isinstance(action.get("spawn"), dict)

    result_file = tmp_path / "capacity-result.json"
    result_file.write_text(json.dumps({
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": f"{error_code.lower()}-result-1",
        "thread_id": action["thread_id"],
        "tick": action["tick"],
        "stage": action["stage"],
        "causation_id": action["message_id"],
        "correlation_id": action["correlation_id"],
        "extensions": {},
        "spawned": False,
        "spawn_error_code": error_code,
        "spawn_error": "宿主 Worker 资源或所有权暂时不可用",
    }, ensure_ascii=False), encoding="utf-8")

    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )

    assert ticked.exit_code == 0, ticked.output
    waiting = json.loads(ticked.output.strip().splitlines()[-1])
    assert waiting["action"] == "resource_wait"
    assert waiting["reason_code"] == error_code
    assert waiting["resource"] == resource
    assert waiting["active_action_message_id"] == action["message_id"]
    assert "worker_attestations" not in waiting

    status = runner.invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )
    assert status.exit_code == 0, status.output
    summary = json.loads(status.output.strip().splitlines()[-1])
    assert summary["active_action"]["message_id"] == action["message_id"]


def test_public_cli_repair_reuses_active_action_until_tick(
    tmp_path: Path,
) -> None:
    """公开 CLI 的 repair 必须修复同一 Action，再由 tick 推进。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-repair-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()

    initialized = runner.invoke(
        main,
        [
            "dev-loop", "--init", "按设计实现音色克隆页面",
            "--design-doc", str(design), "--project-root", str(tmp_path),
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    initial_action = json.loads(initialized.output.strip().splitlines()[-1])
    assert initial_action["stage"] == "gap_scan"

    work_files = initial_action["host_execution"]["work_files"]
    coordinator = tmp_path / work_files["coordinator_result"]
    result_file = tmp_path / work_files["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§unknown",
            "verdict": "clear",
            "evidence": ["错误引用，必须由 Core 要求修复"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    rejected = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(coordinator),
            "--output-result", str(result_file), "--project-root", str(tmp_path),
        ],
    )
    assert rejected.exit_code == 0, rejected.output
    repair = json.loads(rejected.output.strip().splitlines()[-1])
    assert repair["message_id"] == initial_action["message_id"]
    assert repair["result_rejection"]["repair_required"] is True
    assert not result_file.exists()

    coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["已修复为当前设计章节的规范引用"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    repaired = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(coordinator),
            "--output-result", str(result_file), "--project-root", str(tmp_path),
        ],
    )
    assert repaired.exit_code == 0, repaired.output
    assert result_file.is_file()
    canonical_result = json.loads(result_file.read_text(encoding="utf-8"))
    assert canonical_result["causation_id"] == initial_action["message_id"]

    validated = runner.invoke(
        main,
        [
            "dev-loop", "--validate-result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert validated.exit_code == 0, validated.output

    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert ticked.exit_code == 0, ticked.output
    next_action = json.loads(ticked.output.strip().splitlines()[-1])
    assert next_action["action"] != "error"
    assert next_action["message_id"] != initial_action["message_id"]
    assert not result_file.exists()

    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        event_types = [
            event.event_type.value
            for event in events.load_stream(initial_action["thread_id"])
        ]
    assert "ResultAccepted" in event_types
    assert "ActionIssued" in event_types
    journal = OutcomeJournal(tmp_path).load(initial_action["message_id"])
    assert journal is not None
    assert journal["status"] == "accepted"
    assert journal["rejection_history"]


def test_public_cli_architect_result_repair_keeps_worker_outcomes_and_hides_spawn(
    tmp_path: Path,
) -> None:
    """Architect 结果校验失败时，公开 CLI 必须原地修复且禁止重启 Worker。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-architect-repair-e2e'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()
    host_env = {
        "AE_HOST_PLATFORM": "codex",
        "CODEX_THREAD_ID": "public-cli-architect-repair",
    }

    def invoke(*arguments: str) -> dict:
        completed = runner.invoke(
            main,
            ["dev-loop", *arguments, "--project-root", str(tmp_path)],
            env=host_env,
        )
        assert completed.exit_code == 0, completed.output
        return json.loads(completed.output.strip().splitlines()[-1])

    action = invoke(
        "--init", "按设计实现音色克隆页面", "--design-doc", str(design),
    )
    assert action["stage"] == "gap_scan"
    gap_work = action["host_execution"]["work_files"]
    gap_coordinator = tmp_path / gap_work["coordinator_result"]
    gap_result = tmp_path / gap_work["result"]
    gap_coordinator.parent.mkdir(parents=True, exist_ok=True)
    gap_coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["上传契约明确且可验证。"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    invoke(
        "--finalize-result", str(gap_coordinator),
        "--output-result", str(gap_result),
    )
    invoke("--validate-result", str(gap_result))
    action = invoke("--tick", "--result", str(gap_result))
    assert action["stage"] == "architect"
    action_message_id = action["message_id"]
    worker = action["host_execution"]["workers"][0]
    work_files = action["host_execution"]["work_files"]

    # 该计划故意使用不存在的 plate key，触发确定性 Architect 校验失败；
    # Worker outcome 本身合法，修复只应改 Coordinator payload。
    invalid_payload = {
        "plan": (
            "按原设计完成全部组件的实现、测试、审查、契约验证、"
            "类型检查和最终构建验收，并保留完整可重放的审计证据。"
        ),
        "batch_plan": [{
            "batch_id": "B1",
            "batch_title": "错误 plate key 计划",
            "component": "上传",
            "plate_keys": ["不存在的 plate"],
            "design_sections": ["B1", "C1"],
            "tasks": [{
                "id": "B1-T1",
                "description": "实现上传组件",
                "file_targets": ["src/upload.py"],
            }],
        }],
        "file_list": ["src/upload.py"],
        "contracts": {},
    }
    private_outcome = tmp_path / worker["outcome_path"]
    private_outcome.parent.mkdir(parents=True, exist_ok=True)
    private_outcome.write_text(json.dumps({
        "worker_id": worker["worker_id"],
        "status": "completed",
        "payload": invalid_payload,
        "summary": "Architect 产出待修复计划",
    }, ensure_ascii=False), encoding="utf-8")
    invoke(
        "--record-worker-outcome",
        "--worker-id", worker["worker_id"],
        "--worker-status", "completed",
        "--native-worker-handle", "architect-repair-native",
        "--actual-model", "gpt-5.6-sol",
        "--isolation-evidence", "fork_turns=none",
    )

    outcomes = tmp_path / work_files["outcomes"]
    coordinator = tmp_path / work_files["coordinator_result"]
    result = tmp_path / work_files["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps(invalid_payload, ensure_ascii=False), encoding="utf-8")
    invoke(
        "--finalize-result", str(outcomes),
        "--coordinator-result", str(coordinator),
        "--output-result", str(result),
    )
    invoke("--validate-result", str(result))

    repaired = invoke("--tick", "--result", str(result))
    assert repaired["action"] == "architect"
    assert repaired["message_id"] == action_message_id
    assert repaired["result_rejection"]["error_code"] == "ARCHITECT_PLAN_INVALID"
    assert repaired["host_execution"]["recovery"]["status"] == (
        "worker_outcomes_committed"
    )
    assert repaired["host_execution"]["recovery"]["spawn_permitted"] is False
    assert "spawn" not in repaired

    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        stream = events.load_stream(action["thread_id"])
    assert sum(event.event_type.value == "ActionIssued" for event in stream) == 2
    assert sum(event.event_type.value == "ResultAccepted" for event in stream) == 1


def test_public_cli_architect_subset_plan_is_rejected_before_result_commit(
    tmp_path: Path,
) -> None:
    """公开 CLI 不得把完整 Worker 计划静默缩成 Coordinator 子集。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-architect-coverage-e2e'\n",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()
    host_env = {
        "AE_HOST_PLATFORM": "codex",
        "CODEX_THREAD_ID": "public-cli-architect-coverage",
    }

    design.write_text(
        "## B1 音色克隆\n\n"
        "### C1 上传\n明确上传契约。\n\n"
        "### C2 播放\n明确播放契约。\n",
        encoding="utf-8",
    )

    def invoke(*arguments: str) -> dict:
        completed = runner.invoke(
            main,
            ["dev-loop", *arguments, "--project-root", str(tmp_path)],
            env=host_env,
        )
        assert completed.exit_code == 0, completed.output
        return json.loads(completed.output.strip().splitlines()[-1])

    action = invoke(
        "--init", "按设计实现音色克隆页面", "--design-doc", str(design),
    )
    gap_work = action["host_execution"]["work_files"]
    gap_coordinator = tmp_path / gap_work["coordinator_result"]
    gap_result = tmp_path / gap_work["result"]
    gap_coordinator.parent.mkdir(parents=True, exist_ok=True)
    gap_coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["上传契约明确且可验证。"],
        }, {
            "section_ref": "§C2",
            "verdict": "clear",
            "evidence": ["播放契约明确且可验证。"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    invoke(
        "--finalize-result", str(gap_coordinator), "--output-result", str(gap_result),
    )
    invoke("--validate-result", str(gap_result))
    architect_action = invoke("--tick", "--result", str(gap_result))
    worker = architect_action["host_execution"]["workers"][0]
    work_files = architect_action["host_execution"]["work_files"]

    full_plan = {
        "plan": (
            "按原设计完成全部组件的实现、测试、审查、契约验证、类型检查、"
            "最终构建验收，并保留完整可重放的 Worker 与 Coordinator 审计证据。"
        ),
        "batch_plan": [
            {
                "batch_id": "B1",
                "component": "上传",
                "design_item_refs": ["C1-1"],
                "tasks": [{
                    "id": "B1-T1",
                    "description": "实现上传组件",
                    "kind": "implementation",
                    "module_ref": "上传",
                    "file_targets": ["src/upload.py"],
                    "depends_on": [],
                }],
            },
            {
                "batch_id": "B2",
                "component": "播放",
                "design_item_refs": ["C2-1"],
                "tasks": [{
                    "id": "B2-T1",
                    "description": "实现播放组件",
                    "kind": "implementation",
                    "module_ref": "播放",
                    "file_targets": ["src/player.py"],
                    "depends_on": [],
                }],
            },
        ],
        "file_list": ["src/upload.py", "src/player.py"],
        "contracts": {},
    }
    outcome_path = tmp_path / worker["outcome_path"]
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_path.write_text(json.dumps({
        "worker_id": worker["worker_id"],
        "status": "completed",
        "payload": full_plan,
        "summary": "Worker 完成完整 Architect 计划",
    }, ensure_ascii=False), encoding="utf-8")
    invoke(
        "--record-worker-outcome",
        "--worker-id", worker["worker_id"],
        "--worker-status", "completed",
        "--native-worker-handle", "architect-coverage-native",
        "--actual-model", "gpt-5.6-sol",
        "--isolation-evidence", "fork_turns=none",
    )

    coordinator = tmp_path / work_files["coordinator_result"]
    result = tmp_path / work_files["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        **full_plan,
        "batch_plan": [full_plan["batch_plan"][0]],
        "file_list": ["src/upload.py"],
    }, ensure_ascii=False), encoding="utf-8")
    rejected = invoke(
        "--finalize-result", str(tmp_path / work_files["outcomes"]),
        "--coordinator-result", str(coordinator), "--output-result", str(result),
    )

    assert not result.exists()
    assert rejected["result_rejection"]["error_code"] == "HOST_EVIDENCE_INVALID"
    assert "ARCHITECT_RESULT_COVERAGE_LOSS" in (
        rejected["result_rejection"]["violations"]
    )
    assert rejected["message_id"] == architect_action["message_id"]
    assert "workers" not in rejected["host_execution"]
    assert rejected["host_execution"]["recovery"]["spawn_permitted"] is False

    coordinator.write_text(
        json.dumps({
            "plan": full_plan["plan"],
            "file_list": full_plan["file_list"],
            "contracts": {},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    missing_plan = invoke(
        "--finalize-result", str(tmp_path / work_files["outcomes"]),
        "--coordinator-result", str(coordinator), "--output-result", str(result),
    )
    assert missing_plan["result_rejection"]["error_code"] == (
        "HOST_EVIDENCE_INVALID"
    )
    assert "ARCHITECT_RESULT_COVERAGE_LOSS" in (
        missing_plan["result_rejection"]["violations"]
    )

    resumed = runner.invoke(
        main,
        [
            "dev-loop", "--resume", architect_action["thread_id"],
            "--project-root", str(tmp_path),
        ],
        env=host_env,
    )
    assert resumed.exit_code == 0, resumed.output
    resumed_action = json.loads(resumed.output.strip().splitlines()[-1])
    assert resumed_action["message_id"] == architect_action["message_id"]
    assert "workers" not in resumed_action["host_execution"]
    assert resumed_action["host_execution"]["recovery"]["spawn_permitted"] is False

    submitted_outcomes = json.loads(
        (tmp_path / work_files["outcomes"]).read_text(encoding="utf-8")
    )
    submitted_outcomes["outcomes"][0]["payload"]["batch_plan"][0]["tasks"][0][
        "description"
    ] = "Coordinator repair 不能替换已提交 Worker outcome"
    (tmp_path / work_files["outcomes"]).write_text(
        json.dumps(submitted_outcomes, ensure_ascii=False), encoding="utf-8"
    )
    coordinator.write_text(json.dumps(full_plan, ensure_ascii=False), encoding="utf-8")
    repaired_result = invoke(
        "--finalize-result", str(tmp_path / work_files["outcomes"]),
        "--coordinator-result", str(coordinator), "--output-result", str(result),
    )
    assert repaired_result["causation_id"] == architect_action["message_id"]
    coverage = repaired_result["extensions"]["architect_plan_coverage"]
    assert coverage["batch_ids"] == ["B1", "B2"]
    assert coverage["task_ids"] == ["B1-T1", "B2-T1"]
    assert coverage == architect_plan_manifest(full_plan["batch_plan"])
    committed = OutcomeJournal(tmp_path).load(architect_action["message_id"])
    assert committed is not None
    assert committed["outcomes"][0]["native_worker_handle"] == (
        "architect-coverage-native"
    )

    validation = invoke("--validate-result", str(result))
    assert validation["action"] == "validation_passed"
    assert validation["causation_id"] == architect_action["message_id"]
    next_action = invoke("--tick", "--result", str(result))
    assert next_action["stage"] == "developer"
    assert next_action["message_id"] != architect_action["message_id"]
    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        stream = events.load_stream(architect_action["thread_id"])
        accepted = [
            event for event in stream
            if event.event_type.value == "ResultAccepted"
            and event.causation_id == architect_action["message_id"]
        ]
        projection = events.load_projection(architect_action["thread_id"])
    assert len(accepted) == 1
    assert projection is not None
    assert projection.architecture_baseline is not None
    assert projection.architecture_baseline["batch_plan"] == (
        full_plan["batch_plan"]
    )
    assert projection.architecture_baseline["architect_plan_coverage"] == coverage


def test_public_cli_multi_worker_partial_completion_requires_all_outcomes(
    tmp_path: Path,
) -> None:
    """三 Worker Action 必须逐项回写，部分完成不得提交或推进。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-multi-worker-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    from tests.host_runtime.trajectory_runner import HostTrajectoryRunner

    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    with SQLiteEventStore(state_dir / "events.db") as events:
        guardrail = MagicMock()
        guardrail.check.return_value = MagicMock(action="pass")
        core = TickOrchestrator(
            tmp_path,
            event_store=events,
            guardrail=guardrail,
            gate_runner=lambda names, root: {
                name: MagicMock(passed=True, message="ok") for name in names
            },
        )
        action = core.init("验证多 Worker 公开交接")
        trajectory = HostTrajectoryRunner(
            tmp_path,
            HostPlatform.CODEX,
            core=core,
            event_store=events,
        )

        action = trajectory.run(action, workers=[lambda invocation: {
            "plan": (
                "按原设计完成两个组件的实现、测试、审查、契约验证、"
                "类型检查和最终构建验收，并保留完整可重放的审计证据。"
            ),
            "batch_plan": [
                {
                    "batch_id": "B1", "component": "Foo",
                    "tasks": [{
                        "id": "B1-T1", "description": "实现 Foo",
                        "file_targets": ["src/foo.py"],
                    }],
                },
                {
                    "batch_id": "B2", "component": "Bar",
                    "tasks": [{
                        "id": "B2-T1", "description": "实现 Bar",
                        "file_targets": ["src/bar.py"],
                    }],
                },
            ],
            "file_list": ["src/foo.py", "src/bar.py"], "contracts": {},
        }]).next_action
        architect_events = {
            event.event_type.value
            for event in events.load_stream(action["thread_id"])
        }
        assert {
            "ResultEvidenceRecorded",
            "ArchitectureBaselineAccepted",
            "ArchitecturePlanActivated",
        } <= architect_events
        for batch_id, component in (("B1", "Foo"), ("B2", "Bar")):
            action = trajectory.run(action, workers=[lambda invocation, batch=batch_id, name=component: {
                "batch_id": batch,
                "task_ids": [f"{batch}-T1"],
                "files_changed": [f"src/{name.lower()}.py"],
                "commit_hash": "",
                "test_results": {"passed": 1, "failed": 0, "total": 1},
                "red_evidence": [],
            }]).next_action
            action = trajectory.run(action, workers=[lambda invocation: {
                "verdict": "APPROVE",
                "findings": [],
                "critic_feedback": "验证通过",
            }]).next_action
            action = trajectory.run(action, workers=[lambda invocation, name=component: {
                "component": name,
                "coverage_map": [{
                    "design_item": f"{name}-1", "status": "IMPLEMENTED",
                    "file": f"src/{name.lower()}.py", "line": 1, "note": "",
                }],
                "missing_count": 0,
                "diverged_count": 0,
            }]).next_action

        assert action["stage"] == "plate_deep_audit"
        assert action["spawn"]["count"] == 3

    runner = CliRunner()
    resumed = runner.invoke(
        main,
        [
            "dev-loop", "--resume", action["thread_id"],
            "--project-root", str(tmp_path),
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    mapped_action = json.loads(resumed.output.strip().splitlines()[-1])
    workers = mapped_action["host_execution"]["workers"]
    work_files = mapped_action["host_execution"]["work_files"]
    assert len(workers) == 3

    def write_business_artifact(worker: dict) -> None:
        path = tmp_path / worker["outcome_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "worker_id": worker["worker_id"],
            "status": "completed",
            "payload": {
                "plate": "(single)",
                "findings": [],
                "p0_count": 0,
                "p1_count": 0,
                "p2_count": 0,
                "cross_component_issues": [],
                "total_audited_files": 2,
            },
            "summary": f"{worker['worker_id']} completed",
        }, ensure_ascii=False), encoding="utf-8")

    write_business_artifact(workers[0])
    recorded = runner.invoke(
        main,
        [
            "dev-loop", "--record-worker-outcome",
            "--worker-id", workers[0]["worker_id"],
            "--worker-status", "completed",
            "--native-worker-handle", "native-plate-0",
            "--isolation-evidence", "fork_turns=none",
            "--project-root", str(tmp_path),
        ],
    )
    assert recorded.exit_code == 0, recorded.output

    outcomes_path = tmp_path / work_files["outcomes"]
    coordinator_path = tmp_path / work_files["coordinator_result"]
    result_path = tmp_path / work_files["result"]
    coordinator_path.parent.mkdir(parents=True, exist_ok=True)
    coordinator_path.write_text(json.dumps({
        "plate": "(single)", "findings": [],
        "p0_count": 0, "p1_count": 0, "p2_count": 0,
        "cross_component_issues": [], "total_audited_files": 2,
    }), encoding="utf-8")

    partial = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(outcomes_path),
            "--coordinator-result", str(coordinator_path),
            "--output-result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert partial.exit_code == 0, partial.output
    partial_action = json.loads(partial.output.strip().splitlines()[-1])
    assert partial_action["message_id"] == action["message_id"]
    assert partial_action["result_rejection"]["repair_required"] is True
    assert not result_path.exists()

    for index, worker in enumerate(workers[1:], start=1):
        write_business_artifact(worker)
        recorded = runner.invoke(
            main,
            [
                "dev-loop", "--record-worker-outcome",
                "--worker-id", worker["worker_id"],
                "--worker-status", "completed",
                "--native-worker-handle", f"native-plate-{index}",
                "--isolation-evidence", "fork_turns=none",
                "--project-root", str(tmp_path),
            ],
        )
        assert recorded.exit_code == 0, recorded.output

    finalized = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(outcomes_path),
            "--coordinator-result", str(coordinator_path),
            "--output-result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    assert result_path.is_file()

    validated = runner.invoke(
        main,
        [
            "dev-loop", "--validate-result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert validated.exit_code == 0, validated.output
    ticked = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert ticked.exit_code == 0, ticked.output
    next_action = json.loads(ticked.output.strip().splitlines()[-1])
    assert next_action["stage"] == "system_deep_audit"
    assert next_action["message_id"] != action["message_id"]


def test_public_cli_single_component_reaches_terminal_across_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公开入口必须能跨进程完成单组件黄金轨迹并进入 TERMINAL。"""

    (tmp_path / "package.json").write_text(json.dumps({
        "name": "public-cli-terminal-e2e",
        "scripts": {
            "test": "true",
            "lint": "true",
            "typecheck": "true",
            "build": "true",
        },
    }), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()
    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.setenv("CODEX_THREAD_ID", "public-terminal-e2e")

    def invoke(*arguments: str) -> dict:
        completed = runner.invoke(
            main,
            ["dev-loop", *arguments, "--project-root", str(tmp_path)],
        )
        assert completed.exit_code == 0, completed.output
        lines = [line for line in completed.output.splitlines() if line.strip()]
        return json.loads(lines[-1])

    gap_action = invoke(
        "--init", "按设计完成单组件实现", "--design-doc", str(design),
    )
    gap_work_files = gap_action["host_execution"]["work_files"]
    gap_coordinator = tmp_path / gap_work_files["coordinator_result"]
    gap_coordinator.parent.mkdir(parents=True, exist_ok=True)
    gap_coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["设计章节已给出可核验的上传契约。"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    gap_result = tmp_path / gap_work_files["result"]
    invoke(
        "--finalize-result", str(gap_coordinator),
        "--output-result", str(gap_result),
    )
    action = invoke("--tick", "--result", str(gap_result))
    lease_path = tmp_path / ".ae-state" / "host-runtime" / "active-lease.json"
    assert lease_path.is_file()

    # 这一步必须是新的 Python 进程，验证恢复来自持久化 EventStore，而不是
    # CliRunner 中残留的内存状态；scripts/ae-run 的启动器另有专门回归。
    source_root = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(source_root), environment.get("PYTHONPATH")) if item
    )
    resumed = subprocess.run(
        [
            sys.executable, "-c",
            "from auto_engineering.cli import main; main()",
            "dev-loop", "--resume", action["thread_id"],
            "--project-root", str(tmp_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert resumed.returncode == 0, resumed.stderr or resumed.stdout
    action = json.loads(
        [line for line in resumed.stdout.splitlines() if line.strip()][-1]
    )
    assert action["stage"] == "architect"

    stages: list[str] = []
    component_repair_seen = False
    valid_component_payload: dict | None = None
    for attempt in range(12):
        if action.get("action") == "done":
            break
        stage = action["stage"]
        stages.append(stage)
        result_repair = isinstance(action.get("result_rejection"), dict)
        if result_repair:
            assert stage == "component_verifier"
            assert component_repair_seen is False
            assert "spawn" not in action
            assert action["host_execution"]["recovery"]["spawn_permitted"] is False
            component_repair_seen = True
            worker = None
            context = None
        else:
            workers = action["host_execution"]["workers"]
            assert len(workers) == 1, action
            worker = workers[0]
            prompt = (tmp_path / worker["prompt_ref"]).read_text(encoding="utf-8")
            context = json.loads(
                prompt.split(
                    "## 本次任务上下文（编排器注入，禁止自行虚构）", 1,
                )[1].split("```json", 1)[1].split("```", 1)[0]
            )

        if stage == "architect":
            payload = {
                "plan": (
                    "按原设计完成全部组件的实现、测试、审查、契约验证、"
                    "类型检查和最终构建验收，并保留完整可重放的审计证据。"
                ),
                "batch_plan": [{
                    "batch_id": "B1",
                    "component": "上传",
                    "design_item_refs": ["C1-1"],
                    "tasks": [{
                        "id": "B1-T1", "description": "实现上传",
                        "kind": "implementation", "module_ref": "§C1",
                        "file_targets": ["src/upload.py"], "depends_on": [],
                    }],
                }],
                "file_list": ["src/upload.py"],
                "contracts": {},
            }
        elif stage == "developer":
            # Guardrail 校验的是实际工作树快照，不能只在 JSON 中声称 files_changed。
            (tmp_path / "src" / "upload.py").write_text(
                "def upload() -> str:\n    return 'ok'\n", encoding="utf-8",
            )
            payload = {
                "batch_id": context["batch_id"],
                "task_ids": [task["id"] for task in context["tasks"]],
                "files_changed": ["src/upload.py"],
                "commit_hash": "",
                "test_results": {"passed": 1, "failed": 0, "total": 1},
                "red_evidence": [],
            }
        elif stage == "critic":
            payload = {
                "verdict": "APPROVE", "findings": [],
                "critic_feedback": "实现与设计契约一致。",
            }
        elif stage == "component_verifier":
            if result_repair:
                assert valid_component_payload is not None
                payload = deepcopy(valid_component_payload)
            else:
                payload = {
                    "component": context["component"],
                    "coverage_map": [{
                        "design_item": item["design_item"],
                        "status": "IMPLEMENTED",
                        "file": "src/upload.py",
                        "line": 1,
                        "note": "",
                    } for item in context["allowed_design_items"]],
                    "missing_count": 0,
                    "diverged_count": 0,
                }
                valid_component_payload = deepcopy(payload)
            if not result_repair and not component_repair_seen:
                payload["coverage_map"][0]["design_item"] = "not-in-current-batch"
        elif stage == "system_deep_audit":
            payload = {
                "findings": [], "p0_count": 0, "p1_count": 0,
                "p2_count": 0, "total_audited_files": 1,
                "design_docs_stale": False, "design_doc_suggestions": "",
                "missing_count": 0, "diverged_count": 0,
            }
        else:
            raise AssertionError(f"unexpected public golden stage: {stage}")

        if not result_repair:
            assert worker is not None
            outcome_path = tmp_path / worker["outcome_path"]
            outcome_path.parent.mkdir(parents=True, exist_ok=True)
            outcome_path.write_text(json.dumps({
                "worker_id": worker["worker_id"],
                "status": "completed",
                "payload": payload,
                "summary": f"{stage} completed",
            }, ensure_ascii=False), encoding="utf-8")
            invoke(
                "--record-worker-outcome", "--worker-id", worker["worker_id"],
                "--worker-status", "completed", "--native-worker-handle",
                f"native-{attempt}", "--isolation-evidence", "fork_turns=none",
            )

        work_files = action["host_execution"]["work_files"]
        outcomes = tmp_path / work_files["outcomes"]
        coordinator = tmp_path / work_files["coordinator_result"]
        result = tmp_path / work_files["result"]
        coordinator.parent.mkdir(parents=True, exist_ok=True)
        coordinator.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        invoke(
            "--finalize-result", str(outcomes), "--coordinator-result", str(coordinator),
            "--output-result", str(result),
        )
        invoke("--validate-result", str(result))
        action = invoke("--tick", "--result", str(result))

    assert action["action"] == "done"
    assert action["verdict"] == "GOAL_ACHIEVED"
    assert stages == [
        "architect", "developer", "critic", "component_verifier",
        "component_verifier",
        "system_deep_audit",
    ]
    status = invoke("--status", "--format", "json")
    assert status["current_stage"] == "done"
    assert status["expected_stage"] == "done"
    terminal_lease = json.loads(lease_path.read_text(encoding="utf-8"))
    assert terminal_lease["disposition"] == "TERMINAL"
    assert terminal_lease["continuation_required"] is False
    # EventStore 是终态事实源；即使宿主租约被清理，查询也不能丢失完成状态。
    lease_path.unlink()
    status_without_lease = invoke("--status", "--format", "json")
    assert status_without_lease["current_stage"] == "done"
    generic_status = runner.invoke(
        main,
        [
            "status", "--format", "json", "--project-root", str(tmp_path),
        ],
    )
    assert generic_status.exit_code == 0, generic_status.output
    assert json.loads(generic_status.output)["stage"] == "done"


def test_public_cli_late_result_is_audited_without_advancing_current_action(
    tmp_path: Path,
) -> None:
    """公开 CLI 收到未知旧 Result 时只审计，不推进当前 Action。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='public-cli-late-result-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    design = _design_doc(tmp_path)
    runner = CliRunner()

    initialized = runner.invoke(
        main,
        [
            "dev-loop", "--init", "按设计实现音色克隆页面",
            "--design-doc", str(design), "--project-root", str(tmp_path),
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    initial_action = json.loads(initialized.output.strip().splitlines()[-1])
    work_files = initial_action["host_execution"]["work_files"]
    coordinator = tmp_path / work_files["coordinator_result"]
    result_file = tmp_path / work_files["result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        "gaps": [],
        "section_findings": [{
            "section_ref": "§C1",
            "verdict": "clear",
            "evidence": ["已核对完整设计文档"],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    finalized = runner.invoke(
        main,
        [
            "dev-loop", "--finalize-result", str(coordinator),
            "--output-result", str(result_file), "--project-root", str(tmp_path),
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    accepted_result = json.loads(result_file.read_text(encoding="utf-8"))

    advanced = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(result_file),
            "--project-root", str(tmp_path),
        ],
    )
    assert advanced.exit_code == 0, advanced.output
    current_action = json.loads(advanced.output.strip().splitlines()[-1])
    assert current_action["message_id"] != initial_action["message_id"]

    late_result = dict(accepted_result)
    late_result["message_id"] = "late-result-message"
    late_result["causation_id"] = "late-action-message"
    late_path = tmp_path / "late-result.json"
    late_path.write_text(json.dumps(late_result), encoding="utf-8")
    late = runner.invoke(
        main,
        [
            "dev-loop", "--tick", "--result", str(late_path),
            "--project-root", str(tmp_path),
        ],
    )
    assert late.exit_code == 0, late.output
    error = json.loads(late.output.strip().splitlines()[-1])
    assert error["action"] == "error"
    assert error["error_code"] == "ACTION_NOT_ACTIVE"

    status = runner.invoke(
        main,
        ["dev-loop", "--status", "--project-root", str(tmp_path)],
    )
    assert status.exit_code == 0, status.output
    summary = json.loads(status.output.strip().splitlines()[-1])
    assert summary["active_action"]["message_id"] == current_action["message_id"]
    stale_files = list(
        (tmp_path / ".ae-state" / "host-runtime" / "stale-results").glob("*.json")
    )
    assert len(stale_files) == 1
    stale = json.loads(stale_files[0].read_text(encoding="utf-8"))
    assert stale["reason"] == "ACTION_NOT_ACTIVE"
    assert stale["causation_id"] == "late-action-message"


def test_codex_and_claude_adapters_preserve_core_action_semantics(
    tmp_path: Path,
) -> None:
    """两个宿主只替换边界映射，不改变 Core Action/Worker 语义。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='dual-host-semantic-e2e'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".ae-state").mkdir()
    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db") as events:
        action = _core(tmp_path, events).init("验证双宿主边界等价")

    mapped: dict[HostPlatform, dict] = {}
    for platform in (HostPlatform.CODEX, HostPlatform.CLAUDE_CODE):
        adapter = adapter_for(platform)
        profile = adapter.profile(
            detected=adapter.capabilities,
            authorized=adapter.capabilities,
        )
        mapped[platform] = adapter.map_action(action, profile=profile).payload

    semantic_keys = (
        "message_id", "thread_id", "tick", "stage", "action", "spawn",
        "expected_format", "result_contract",
    )
    for key in semantic_keys:
        assert mapped[HostPlatform.CODEX].get(key) == mapped[HostPlatform.CLAUDE_CODE].get(key)

    codex_execution = mapped[HostPlatform.CODEX]["host_execution"]
    claude_execution = mapped[HostPlatform.CLAUDE_CODE]["host_execution"]
    assert codex_execution["platform"] == HostPlatform.CODEX.value
    assert claude_execution["platform"] == HostPlatform.CLAUDE_CODE.value
    assert codex_execution["workers"][0]["worker_id"] == claude_execution["workers"][0]["worker_id"]
    assert codex_execution["workers"][0]["prompt_ref"] == claude_execution["workers"][0]["prompt_ref"]
    assert codex_execution["workers"][0]["expected_isolation_evidence"] == "fork_turns=none"
    assert claude_execution["workers"][0]["expected_isolation_evidence"] == "fresh_context"
