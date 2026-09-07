"""真实产品证据采集器的事实绑定回归。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

import pytest

from auto_engineering.metrics.usage_ledger import UsageLedger, UsageRecord
from scripts.collect_product_evidence import (
    EvidenceCollectionError,
    _native_result_manifest,
    _usage_receipts,
    collect_product_evidence,
)
from scripts.generate_business_evidence import generate_business_evidence
from scripts.product_acceptance import ProductAcceptanceError, evaluate_host_evidence


def _record(action_id: str, stage: str) -> UsageRecord:
    return UsageRecord(
        thread_id="thread-1",
        session_id="session-1",
        tick=2,
        stage=stage,
        worker="main",
        input_units=10,
        cache_read_units=5,
        cache_write_units=0,
        output_units=2,
        provider="openai",
        model="test-model",
        usage_source="codex-rollout",
        estimated=False,
        action_message_id=action_id,
    )


def test_usage_receipts_reject_unbound_usage() -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory:
        ledger = UsageLedger(Path(directory) / "usage.db")
        record = replace(_record("action-1", "architect"), action_message_id=None)
        ledger.append(record)
        action = {
            "message_id": "action-1",
            "stage": "architect",
        }
        with pytest.raises(EvidenceCollectionError, match="USAGE_ACTION_BINDING_MISSING"):
            _usage_receipts(
                ledger=ledger,
                thread_id="thread-1",
                actions=[action],
                build_id="5.8.0-rc.5+sha256." + "a" * 16,
                host="codex",
                cost_usd=None,
            )
        ledger.close()


def test_native_manifest_discovers_private_result_when_event_action_is_canonical(
    tmp_path: Path,
) -> None:
    """宿主私有 worker path 不会被误要求出现在 Core canonical Action。"""

    from auto_engineering.host.path_contract import worker_native_result_path

    action = {
        "message_id": "architect-action",
        "stage": "architect",
        "spawn": {"invocations": [{"worker_id": "architect-0"}]},
    }
    native_path = tmp_path / worker_native_result_path(
        "architect-action", "architect-0", 2
    )
    native_path.parent.mkdir(parents=True, exist_ok=True)
    native_path.write_text(
        '{"worker_id":"architect-0","status":"completed",'
        '"payload":{}}\n',
        encoding="utf-8",
    )

    manifest = _native_result_manifest(tmp_path, [action])

    assert manifest == [{
        "action_message_id": "architect-action",
        "worker_id": "architect-0",
        "path": native_path.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(native_path.read_bytes()).hexdigest(),
        "bytes": native_path.stat().st_size,
    }]


def _create_candidate(path: Path) -> tuple[str, str]:
    content_sha256 = "a" * 64
    build_id = "5.8.0-rc.5+sha256." + content_sha256[:16]
    info = {
        "schema_version": "1.0",
        "version": "5.8.0-rc.5",
        "content_sha256": content_sha256,
        "build_id": build_id,
    }
    source = path / "build-info.json"
    source.write_text(json.dumps(info), encoding="utf-8")
    archive = path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(source, arcname="build-info.json")
    return str(archive), build_id


def _create_project(root: Path, build_id: str) -> None:
    state = root / ".ae-state"
    (state / "host-runtime" / "outcomes").mkdir(parents=True)
    connection = sqlite3.connect(state / "events.db")
    connection.execute(
        "CREATE TABLE loop_events (thread_id TEXT, event_type TEXT, payload_json TEXT, sequence INTEGER)"
    )
    actions = []
    sequence = 0
    for stage, action_id in (
        ("architect", "architect-action"),
        ("developer", "developer-action"),
        ("critic", "critic-action"),
    ):
        action = {
            "action": stage,
            "message_id": action_id,
            "stage": stage,
            "thread_id": "thread-1",
            "extensions": {"ae": {"runtime_revision": {"engine_build_id": build_id}}},
            "spawn": {"invocations": [{"worker_id": f"{stage}-0"}]},
            "host_execution": {
                "workers": [{
                    "worker_id": f"{stage}-0",
                    "native_result_path": (
                        f".ae-state/host-runtime/native-results/{stage}.json"
                    ),
                }],
            },
        }
        if stage == "architect":
            action["host_execution"]["recovery"] = {
                "status": "worker_outcomes_committed",
                "spawn_permitted": False,
                "required_operation": "repair_coordinator_then_finalize",
            }
        actions.append(action)
        connection.execute(
            "INSERT INTO loop_events VALUES (?, ?, ?, ?)",
            ("thread-1", "ActionIssued", json.dumps({"action": action}), sequence),
        )
        sequence += 1
        connection.execute(
            "INSERT INTO loop_events VALUES (?, ?, ?, ?)",
            ("thread-1", "ResultAccepted", json.dumps({}), sequence),
        )
        sequence += 1
        (state / "host-runtime" / "outcomes" / f"{action_id}.json").write_text(
            json.dumps({"status": "accepted"}), encoding="utf-8"
        )
        native_path = (
            state / "host-runtime" / "native-results" / f"{stage}.json"
        )
        native_path.parent.mkdir(parents=True, exist_ok=True)
        native_path.write_bytes(b'{"content": [{"type": "text", "text": "{}"}]}\n')
    terminal = {
        "action": "done",
        "message_id": "done-action",
        "stage": "system_deep_audit",
        "acceptance_summary": {
            "scope": "core",
            "status": "core_verified_product_unverified",
            "release_eligible": False,
            "verified_checks": ["design_coverage"],
            "unverified_items": ["product_business_acceptance"],
            "coverage": {"verified": 1, "total": 2},
        },
    }
    connection.execute(
        "INSERT INTO loop_events VALUES (?, ?, ?, ?)",
        ("thread-1", "ActionIssued", json.dumps({"action": terminal}), sequence),
    )
    sequence += 1
    connection.execute(
        "INSERT INTO loop_events VALUES (?, ?, ?, ?)",
        ("thread-1", "LoopCompleted", json.dumps({}), sequence),
    )
    connection.commit()
    connection.close()
    ledger = UsageLedger(state / "usage-ledger.db")
    for stage, action_id in (
        ("architect", "architect-action"),
        ("developer", "developer-action"),
        ("critic", "critic-action"),
    ):
        ledger.append(_record(action_id, stage))
    ledger.close()


def _create_business_evidence(root: Path, build_id: str) -> Path:
    evidence_root = root / ".ae-state" / "product-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    gates: dict[str, dict[str, object]] = {}
    for gate in ("typecheck", "unit_test", "build"):
        output = evidence_root / f"{gate}.log"
        output.write_text(f"{gate}: pass\n", encoding="utf-8")
        gates[gate] = {
            "status": "pass",
            "command": ["fixture", gate],
            "exit_code": 0,
            "evidence_path": output.relative_to(root).as_posix(),
            "evidence_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    report = evidence_root / "business-evidence.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "scenario_id": "voice-clone-v1",
                "build_id": build_id,
                "gates": gates,
                "final_verdict": "pass",
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return report


def test_collector_requires_structured_business_evidence(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="codex",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=_create_business_evidence(project, build_id),
    )
    assert evidence["golden_project"]["final_verdict"] == "pass"


def test_collector_separates_l4_business_project_from_l3_canary_project(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "golden-project"
    canary = tmp_path / "canary-project"
    project.mkdir()
    canary.mkdir()
    _create_project(project, build_id)
    _create_project(canary, build_id)
    events = sqlite3.connect(project / ".ae-state" / "events.db")
    row = events.execute(
        "SELECT payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' AND sequence = 0"
    ).fetchone()
    assert row is not None
    action_payload = json.loads(row[0])
    action_payload["action"]["host_execution"].pop("recovery")
    events.execute(
        "UPDATE loop_events SET payload_json = ? "
        "WHERE event_type = 'ActionIssued' AND sequence = 0",
        (json.dumps(action_payload),),
    )
    events.commit()
    events.close()
    report = _create_business_evidence(project, build_id)

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=canary,
        host="codex",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=report,
    )

    assert evidence["golden_project"]["status"] == "pass"
    assert evidence["canary"]["recovery_method"] == "coordinator_repair"


def test_collector_rejects_tampered_business_gate_output(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = _create_business_evidence(project, build_id)
    (project / ".ae-state" / "product-evidence" / "build.log").write_text(
        "build: failed\n", encoding="utf-8"
    )

    with pytest.raises(
        EvidenceCollectionError,
        match="BUSINESS_GATE_EVIDENCE_MISMATCH",
    ):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="codex",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime",
            development_root=tmp_path / "development",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "artifact.json",
            evidence_output=tmp_path / "evidence.json",
            business_evidence=report,
        )


def test_collector_rejects_canary_without_bound_recovery_action(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = _create_business_evidence(project, build_id)
    events = sqlite3.connect(project / ".ae-state" / "events.db")
    row = events.execute(
        "SELECT payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' AND sequence = 0"
    ).fetchone()
    assert row is not None
    action_payload = json.loads(row[0])
    action_payload["action"]["host_execution"].pop("recovery")
    events.execute(
        "UPDATE loop_events SET payload_json = ? "
        "WHERE event_type = 'ActionIssued' AND sequence = 0",
        (json.dumps(action_payload),),
    )
    events.commit()
    events.close()

    with pytest.raises(EvidenceCollectionError, match="CANARY_RECOVERY_NOT_UNIQUE"):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="codex",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime",
            development_root=tmp_path / "development",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "artifact.json",
            evidence_output=tmp_path / "evidence.json",
            business_evidence=report,
        )


def test_collector_accepts_coordinator_repair_from_outcome_journal(
    tmp_path: Path,
) -> None:
    """Canonical EventStore 不含宿主投影时仍能验证同 Action 修复。"""
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = _create_business_evidence(project, build_id)

    events = sqlite3.connect(project / ".ae-state" / "events.db")
    row = events.execute(
        "SELECT payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' AND sequence = 0"
    ).fetchone()
    assert row is not None
    action_payload = json.loads(row[0])
    action_payload["action"]["host_execution"].pop("recovery")
    events.execute(
        "UPDATE loop_events SET payload_json = ? "
        "WHERE event_type = 'ActionIssued' AND sequence = 0",
        (json.dumps(action_payload),),
    )
    events.commit()
    events.close()

    journal = project / ".ae-state/host-runtime/outcomes/architect-action.json"
    journal.write_text(
        json.dumps({
            "status": "accepted",
            "attempt": 2,
            "rejection_history": [{"error_code": "RESULT_REJECTED"}],
        }),
        encoding="utf-8",
    )

    collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="codex",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=report,
    )

    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["canary"]["recovery_verified"] is True
    assert evidence["canary"]["recovery_method"] == "coordinator_repair"


def test_collector_rejects_multiple_canary_recovery_actions(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = _create_business_evidence(project, build_id)
    events = sqlite3.connect(project / ".ae-state" / "events.db")
    row = events.execute(
        "SELECT payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' AND sequence = 0"
    ).fetchone()
    assert row is not None
    action_payload = json.loads(row[0])
    duplicate = json.loads(json.dumps(action_payload))
    duplicate["action"]["message_id"] = "duplicate-recovery-action"
    events.execute(
        "INSERT INTO loop_events VALUES (?, ?, ?, ?)",
        ("thread-1", "ActionIssued", json.dumps(duplicate), 99),
    )
    events.commit()
    events.close()

    with pytest.raises(EvidenceCollectionError, match="CANARY_RECOVERY_NOT_UNIQUE"):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="codex",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime",
            development_root=tmp_path / "development",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "artifact.json",
            evidence_output=tmp_path / "evidence.json",
            business_evidence=report,
        )


def test_collector_accepts_native_outcome_resume_when_projection_matches(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    events = sqlite3.connect(project / ".ae-state" / "events.db")
    row = events.execute(
        "SELECT payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' AND sequence = 0"
    ).fetchone()
    assert row is not None
    action_payload = json.loads(row[0])
    action_payload["action"]["host_execution"]["recovery"]["status"] = (
        "native_outcomes_ready"
    )
    events.execute(
        "UPDATE loop_events SET payload_json = ? WHERE event_type = 'ActionIssued' "
        "AND sequence = 0",
        (json.dumps(action_payload),),
    )
    events.commit()
    events.close()
    report = _create_business_evidence(project, build_id)

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="codex",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=report,
    )
    assert evidence["canary"]["recovery_method"] == "native_outcome_resume"


def test_business_evidence_generator_executes_l4_business_gates(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = project / ".ae-state" / "product-evidence" / "generated.json"

    generated = generate_business_evidence(
        project_root=project,
        archive=Path(archive),
        output=report,
        gate_commands={
            gate: [sys.executable, "-c", f"print('{gate}: pass')"]
            for gate in ("typecheck", "unit_test", "build")
        },
    )

    assert generated["final_verdict"] == "pass"
    assert "recovery" not in generated
    assert all(item["exit_code"] == 0 for item in generated["gates"].values())
    assert all(
        hashlib.sha256(
            (project / item["evidence_path"]).read_bytes()
        ).hexdigest() == item["evidence_sha256"]
        for item in generated["gates"].values()
    )


def test_business_evidence_generator_keeps_l4_business_report_independent_of_recovery(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    database = project / ".ae-state" / "events.db"
    connection = sqlite3.connect(database)
    row = connection.execute(
        "SELECT sequence, payload_json FROM loop_events "
        "WHERE event_type = 'ActionIssued' ORDER BY sequence LIMIT 1"
    ).fetchone()
    assert row is not None
    sequence, payload_json = row
    payload = json.loads(payload_json)
    payload["action"]["host_execution"].pop("recovery")
    connection.execute(
        "UPDATE loop_events SET payload_json = ? WHERE sequence = ?",
        (json.dumps(payload), sequence),
    )
    connection.commit()
    connection.close()

    report = generate_business_evidence(
        project_root=project,
        archive=Path(archive),
        output=project / ".ae-state" / "product-evidence" / "generated.json",
        gate_commands={
            "typecheck": [sys.executable, "-c", "print('typecheck: pass')"],
            "unit_test": [sys.executable, "-c", "print('unit_test: pass')"],
            "build": [sys.executable, "-c", "print('build: pass')"],
        },
    )

    assert report["final_verdict"] == "pass"
    assert "recovery" not in report


def test_business_evidence_generator_records_gate_failure_without_claiming_pass(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report = project / ".ae-state" / "product-evidence" / "generated.json"
    commands = {
        gate: [sys.executable, "-c", f"print('{gate}: pass')"]
        for gate in ("typecheck", "unit_test", "build")
    }
    commands["build"] = [
        sys.executable,
        "-c",
        "print('build: failed'); raise SystemExit(7)",
    ]

    generated = generate_business_evidence(
        project_root=project,
        archive=Path(archive),
        output=report,
        gate_commands=commands,
    )

    assert generated["final_verdict"] == "fail"
    assert generated["gates"]["build"]["status"] == "fail"
    assert generated["gates"]["build"]["exit_code"] == 7
    assert "build: failed" in (
        project / generated["gates"]["build"]["evidence_path"]
    ).read_text(encoding="utf-8")


def test_business_evidence_cli_chain_runs_from_outside_repository(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    runtime = tmp_path / "runtime"
    development = tmp_path / "development"
    runtime.mkdir()
    development.mkdir()
    report = project / ".ae-state" / "product-evidence" / "business.json"
    artifact = tmp_path / "artifact.json"
    evidence = tmp_path / "evidence.json"
    repo_root = Path(__file__).parents[1]
    commands = [
        f"typecheck={json.dumps([sys.executable, '-c', 'print(1)'])}",
        f"unit_test={json.dumps([sys.executable, '-c', 'print(2)'])}",
        f"build={json.dumps([sys.executable, '-c', 'print(3)'])}",
    ]
    generator = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/generate_business_evidence.py"),
            "--project-root",
            str(project),
            "--archive",
            str(archive),
            "--output",
            str(report),
            "--gate-command",
            commands[0],
            "--gate-command",
            commands[1],
            "--gate-command",
            commands[2],
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generator.returncode == 0, generator.stderr

    collector = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/collect_product_evidence.py"),
            "--project-root",
            str(project),
            "--host",
            "codex",
            "--archive",
            str(archive),
            "--runtime-root",
            str(runtime),
                "--development-root",
                str(development),
                "--canary-project-root",
                str(project),
                "--source-ref",
            "local-marketplace-fixture",
            "--output",
            str(artifact),
            "--evidence-output",
            str(evidence),
            "--business-evidence",
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collector.returncode == 0, collector.stderr

    validator = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/product_acceptance.py"),
            "--archive",
            str(archive),
            "--evidence",
            str(evidence),
            "--evidence-root",
            str(tmp_path),
            "--project-root",
            f"codex={project}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validator.returncode == 0, validator.stderr
    assert json.loads(validator.stdout)["status"] == "pass"


def test_collector_derives_hashable_host_evidence_from_facts(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    runtime = tmp_path / "runtime"
    development = tmp_path / "development"
    runtime.mkdir()
    development.mkdir()
    artifact = tmp_path / "codex-artifact.json"
    evidence_path = tmp_path / "codex.json"

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="codex",
        archive=Path(archive),
        runtime_root=runtime,
        development_root=development,
        source_ref="local-marketplace-fixture",
        output=artifact,
        evidence_output=evidence_path,
        business_evidence=_create_business_evidence(project, build_id),
    )

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert evidence["evidence_artifact"] == {
        "path": artifact.name,
        "sha256": digest,
    }
    assert json.loads(artifact.read_text())["acceptance_policy"] == {
        "max_claude_cost_usd": 2.0,
    }
    assert evaluate_host_evidence(evidence, evidence_root=tmp_path)["status"] == "pass"


def test_claude_collector_reads_cost_from_native_stream_output(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    host_output = project / ".ae-state" / "claude.stream.jsonl"
    host_output.write_text(
        json.dumps({
            "type": "result",
            "total_cost_usd": 0.75,
            "usage": {
                "input_tokens": 12,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 4,
                "output_tokens": 5,
            },
        }) + "\n",
        encoding="utf-8",
    )

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="claude-code",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=_create_business_evidence(project, build_id),
        host_output=host_output,
        max_claude_cost_usd=3.0,
    )

    assert evidence["usage"]["cost_usd"] == 0.75
    assert evidence["acceptance_policy"] == {"max_claude_cost_usd": 3.0}
    (tmp_path / "runtime").mkdir()
    (tmp_path / "development").mkdir()
    assert json.loads((tmp_path / "artifact.json").read_text())["acceptance_policy"] == {
        "max_claude_cost_usd": 3.0,
    }
    assert evidence["host_usage_attestation"]["sha256"] == hashlib.sha256(
        host_output.read_bytes()
    ).hexdigest()
    assert evaluate_host_evidence(
        evidence,
        evidence_root=tmp_path,
        source_root=project,
        max_claude_cost_usd=3.0,
    )["status"] == "pass"
    with pytest.raises(ProductAcceptanceError, match="ACCEPTANCE_POLICY_MISMATCH"):
        evaluate_host_evidence(
            evidence,
            evidence_root=tmp_path,
            max_claude_cost_usd=2.0,
        )
    with pytest.raises(ProductAcceptanceError, match="CLAUDE_COST_POLICY_INVALID"):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="claude-code",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime-invalid",
            development_root=tmp_path / "development-invalid",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "invalid-artifact.json",
            evidence_output=tmp_path / "invalid-evidence.json",
            business_evidence=_create_business_evidence(project, build_id),
            host_output=host_output,
            max_claude_cost_usd=-1.0,
        )


def test_collector_rejects_spawn_without_native_result_evidence(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    missing = project / ".ae-state/host-runtime/native-results/architect.json"
    missing.unlink()

    with pytest.raises(
        EvidenceCollectionError,
        match="NATIVE_RESULT_EVIDENCE_MISSING",
    ):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="codex",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime",
            development_root=tmp_path / "development",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "artifact.json",
            evidence_output=tmp_path / "evidence.json",
            business_evidence=_create_business_evidence(project, build_id),
        )


def test_collector_counts_host_stop_report_as_unexpected_stop(tmp_path: Path) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    report_root = project / ".ae-state/host-runtime/stop-reports"
    report_root.mkdir(parents=True)
    (report_root / "unexpected.json").write_text(
        json.dumps({"reason_code": "HOST_RUNTIME_PROTOCOL_ERROR"}),
        encoding="utf-8",
    )
    host_output = project / "claude.stream.jsonl"
    host_output.write_text(
        json.dumps({
            "type": "result",
            "total_cost_usd": 0.75,
            "usage": {
                "input_tokens": 12,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 4,
                "output_tokens": 5,
            },
        }) + "\n",
        encoding="utf-8",
    )

    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="claude-code",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=tmp_path / "artifact.json",
        evidence_output=tmp_path / "evidence.json",
        business_evidence=_create_business_evidence(project, build_id),
        host_output=host_output,
    )

    assert evidence["unexpected_stops"] == 1


def test_validator_rechecks_content_addressed_project_sources(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "development").mkdir()
    artifact = tmp_path / "codex-artifact.json"
    evidence_path = tmp_path / "codex.json"
    evidence = collect_product_evidence(
        project_root=project,
        canary_project_root=project,
        host="codex",
        archive=Path(archive),
        runtime_root=tmp_path / "runtime",
        development_root=tmp_path / "development",
        source_ref="local-marketplace-fixture",
        output=artifact,
        evidence_output=evidence_path,
        business_evidence=_create_business_evidence(project, build_id),
    )

    assert evaluate_host_evidence(
        evidence,
        evidence_root=tmp_path,
        source_root=project,
    )["status"] == "pass"

    native = project / ".ae-state/host-runtime/native-results/architect.json"
    native.write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(
        ProductAcceptanceError,
        match="NATIVE_RESULT_EVIDENCE_MISMATCH",
    ):
        evaluate_host_evidence(
            evidence,
            evidence_root=tmp_path,
            source_root=project,
        )


def test_dual_host_validator_cli_uses_separate_project_roots(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    repo_root = Path(__file__).parents[1]
    evidence_paths: dict[str, Path] = {}
    project_roots: dict[str, Path] = {}
    for host in ("codex", "claude-code"):
        project = tmp_path / host
        project.mkdir()
        _create_project(project, build_id)
        project_roots[host] = project
        runtime = tmp_path / f"{host}-runtime"
        development = tmp_path / f"{host}-development"
        runtime.mkdir()
        development.mkdir()
        host_output = None
        if host == "claude-code":
            host_output = project / ".ae-state" / "claude.stream.jsonl"
            host_output.write_text(
                json.dumps({
                    "type": "result",
                    "total_cost_usd": 0.5,
                    "usage": {
                        "input_tokens": 12,
                        "cache_read_input_tokens": 30,
                        "cache_creation_input_tokens": 4,
                        "output_tokens": 5,
                    },
                }) + "\n",
                encoding="utf-8",
            )
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host=host,
            archive=Path(archive),
            runtime_root=runtime,
            development_root=development,
            source_ref=f"local-{host}-marketplace-fixture",
            output=tmp_path / f"{host}-artifact.json",
            evidence_output=tmp_path / f"{host}-evidence.json",
            business_evidence=_create_business_evidence(project, build_id),
            host_output=host_output,
        )
        evidence_paths[host] = tmp_path / f"{host}-evidence.json"

    validator = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/product_acceptance.py"),
            "--archive",
            str(archive),
            "--evidence",
            str(evidence_paths["codex"]),
            "--evidence",
            str(evidence_paths["claude-code"]),
            "--evidence-root",
            str(tmp_path),
            "--project-root",
            f"codex={project_roots['codex']}",
            "--project-root",
            f"claude-code={project_roots['claude-code']}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert validator.returncode == 0, validator.stderr
    verdict = json.loads(validator.stdout)
    assert verdict["levels"] == {"L3": "pass", "L4": "pass"}


def test_claude_collector_rejects_host_output_outside_project_root(
    tmp_path: Path,
) -> None:
    archive, build_id = _create_candidate(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _create_project(project, build_id)
    host_output = tmp_path / "claude.stream.jsonl"
    host_output.write_text(
        json.dumps({
            "type": "result",
            "total_cost_usd": 0.5,
            "usage": {
                "input_tokens": 1,
                "cache_read_input_tokens": 1,
                "output_tokens": 1,
            },
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        EvidenceCollectionError,
        match="CLAUDE_USAGE_ATTESTATION_PATH_INVALID",
    ):
        collect_product_evidence(
            project_root=project,
            canary_project_root=project,
            host="claude-code",
            archive=Path(archive),
            runtime_root=tmp_path / "runtime",
            development_root=tmp_path / "development",
            source_ref="local-marketplace-fixture",
            output=tmp_path / "artifact.json",
            evidence_output=tmp_path / "evidence.json",
            business_evidence=_create_business_evidence(project, build_id),
            host_output=host_output,
        )
