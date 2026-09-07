"""Phase 82 T445：分层真实产品证据门禁。"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts.product_acceptance import (
    ProductAcceptanceError,
    _number,
    _parse_project_roots,
    _validate_attempt_receipts,
    _validate_build_identity_preflight,
    _validate_business_evidence,
    _validate_host_usage_attestation,
    _validate_machine_claims,
    _validate_native_result_manifest,
    evaluate_host_evidence,
    evaluate_product_evidence,
    evaluate_release_evidence,
)


def test_product_acceptance_script_entrypoint_loads_without_repository_pythonpath(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(Path(__file__).parents[1] / "scripts/product_acceptance.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--archive" in result.stdout
    assert "--max-claude-cost-usd" in result.stdout
    assert "--project-root" in result.stdout


@pytest.mark.parametrize(
    "value",
    [
        ["codex=/tmp/codex", "codex=/tmp/duplicate"],
        ["unknown=/tmp/project"],
        ["codex="],
        ["/tmp/project"],
    ],
)
def test_project_root_mapping_rejects_ambiguous_values(value: list[str]) -> None:
    with pytest.raises(ProductAcceptanceError, match="PROJECT_ROOT_INVALID"):
        _parse_project_roots(value)


def test_project_root_mapping_keeps_host_projects_separate() -> None:
    assert _parse_project_roots([
        "codex=/tmp/codex-project",
        "claude-code=/tmp/claude-project",
    ]) == {
        "codex": Path("/tmp/codex-project"),
        "claude-code": Path("/tmp/claude-project"),
    }


def test_machine_claims_reject_outer_usage_declaration_drift() -> None:
    artifact = {
        "trajectory": {
            "manual_protocol_repairs": 0,
            "traceability_complete": True,
        },
        "machine_claims": {
            "usage_status": "complete",
            "unexpected_stops": 0,
            "manual_protocol_repairs": 0,
            "traceability_complete": True,
        },
    }
    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_MACHINE_CLAIMS_MISMATCH"):
        _validate_machine_claims(
            artifact,
            {"usage_status": "incomplete", "unexpected_stops": 0},
        )


def test_machine_claims_reject_manual_repair_drift() -> None:
    artifact = {
        "trajectory": {
            "manual_protocol_repairs": 1,
            "traceability_complete": True,
        },
        "machine_claims": {
            "usage_status": "complete",
            "unexpected_stops": 0,
            "manual_protocol_repairs": 0,
            "traceability_complete": True,
        },
    }

    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_MACHINE_CLAIMS_MISMATCH"):
        _validate_machine_claims(
            artifact,
            {"usage_status": "complete", "unexpected_stops": 0},
        )


def test_native_result_manifest_rejects_duplicate_worker_identity() -> None:
    item = {
        "action_message_id": "action-1",
        "worker_id": "worker-1",
        "path": ".ae-state/host-runtime/native-results/worker.json",
        "sha256": "a" * 64,
        "bytes": 10,
    }
    with pytest.raises(
        ProductAcceptanceError,
        match="NATIVE_RESULT_MANIFEST_INVALID",
    ):
        _validate_native_result_manifest({
            "native_result_manifest": [item, dict(item)],
        })


def test_host_usage_attestation_rejects_absolute_or_unhashed_source() -> None:
    artifact = {
        "host_usage_attestation": {
            "path": "/tmp/claude.jsonl",
            "sha256": "0" * 64,
            "bytes": 1,
            "source": "claude-cli-result",
        }
    }

    with pytest.raises(
        ProductAcceptanceError,
        match="HOST_USAGE_ATTESTATION_INVALID",
    ):
        _validate_host_usage_attestation(artifact)


def test_business_evidence_rejects_unbound_gate_claims() -> None:
    with pytest.raises(ProductAcceptanceError, match="BUSINESS_GATE_INCOMPLETE"):
        _validate_business_evidence({"business_evidence": {
            "schema_version": "1.0",
            "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
            "final_verdict": "pass",
            "gates": {"typecheck": {"status": "pass"}},
        }})


def test_current_artifact_requires_business_evidence() -> None:
    with pytest.raises(ProductAcceptanceError, match="BUSINESS_EVIDENCE_MISSING"):
        _validate_business_evidence({})


def test_current_artifact_requires_machine_derived_evidence() -> None:
    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_MACHINE_CLAIMS_INVALID"):
        _validate_machine_claims({}, {"usage_status": "complete", "unexpected_stops": 0})
    with pytest.raises(ProductAcceptanceError, match="NATIVE_RESULT_MANIFEST_INVALID"):
        _validate_native_result_manifest({})
    with pytest.raises(ProductAcceptanceError, match="ACTION_ATTEMPTS_INVALID"):
        _validate_attempt_receipts({}, {"build_id": "build-1"})


def test_product_build_identity_preflight_is_required_and_bound() -> None:
    candidate = {
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "content_sha256": "a" * 64,
    }

    with pytest.raises(
        ProductAcceptanceError,
        match="PRODUCT_BUILD_IDENTITY_PREFLIGHT_MISSING",
    ):
        _validate_build_identity_preflight({}, candidate)

    _validate_build_identity_preflight(
        {
            "build_identity_preflight": {
                "status": "pass",
                "build_id": candidate["build_id"],
                "version": candidate["version"],
                "source_kind": "packaged",
            }
        },
        candidate,
    )


def test_l3_canary_engineering_baseline_is_explicit_and_versioned() -> None:
    import tomllib
    from pathlib import Path

    fixture_root = Path(__file__).parent / "fixtures" / "golden"
    design = (fixture_root / "l3_canary_design.md").read_text(encoding="utf-8")
    project = tomllib.loads(
        (fixture_root / "l3_canary_pyproject.toml").read_text(encoding="utf-8")
    )
    config = tomllib.loads(
        (fixture_root / "l3_canary_ae.toml").read_text(encoding="utf-8")
    )

    assert "hatchling.build" in design
    assert project["build-system"] == {
        "requires": ["hatchling>=1.27,<2"],
        "build-backend": "hatchling.build",
    }
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/canary_math"
    ]
    assert project["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"] == [
        "/.ae-state",
        "/_scratch",
        "/.venv",
        "/dist",
        "/**/__pycache__",
    ]
    assert "source distribution" in design
    assert config["project"]["type"] == "library"
    assert config["project"]["commands"] == {
        "lint": ["uv", "run", "ruff", "check", "src", "tests"],
        "type_check": ["uv", "run", "mypy", "src", "tests"],
        "test": ["uv", "run", "pytest", "-q"],
        "build": ["uv", "build"],
    }


def _evidence(tmp_path=None) -> dict[str, object]:
    runtime_root = (tmp_path / "installed") if tmp_path else "/opt/ae-release"
    development_root = (tmp_path / "development") if tmp_path else "/src/auto-engineering"
    if tmp_path:
        runtime_root.mkdir(parents=True, exist_ok=True)
        development_root.mkdir(parents=True, exist_ok=True)
    return {
        "host": "codex",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "project_state": "fresh",
        "semantic_enforcement": "full",
        "usage_status": "complete",
        "unexpected_stops": 0,
        "unapproved_changes": 0,
        "installation": {
            "status": "pass",
            "discovered": True,
            "runtime_root": str(runtime_root),
            "development_root": str(development_root),
            "source_isolated": True,
            "source_kind": "marketplace",
            "source_ref": "qianminjian/Auto-engineering",
            "source_build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
            "source_content_sha256": "a" * 64,
        },
        "usage": {
            "input_tokens": 900_000,
            "cached_input_tokens": 800_001,
            "output_tokens": 9_999,
            "cost_usd": None,
        },
        "canary": {
            "status": "pass",
            "stages": ["architect", "developer", "critic"],
            "recovery_verified": True,
            "recovery_method": "coordinator_repair",
            "recovery_action_message_id": "architect-action",
        },
        "golden_project": {
            "status": "pass",
            "business_gates": ["typecheck", "unit_test", "build"],
            "final_verdict": "pass",
        },
    }


_TERMINAL_ACCEPTANCE_SUMMARY = {
    "scope": "core",
    "status": "core_verified_product_unverified",
    "verified_checks": ["design_coverage", "system_deep_audit"],
    "unverified_items": ["product_business_acceptance"],
    "coverage": {"verified": 2, "total": 3},
    "release_eligible": False,
}


def _business_evidence_payload(build_id: str) -> dict[str, object]:
    gate_output = "a" * 64
    gates = {
        name: {
            "status": "pass",
            "command": ["fixture", name],
            "exit_code": 0,
            "evidence_path": f".ae-state/product-evidence/{name}.log",
            "evidence_sha256": gate_output,
        }
        for name in ("typecheck", "unit_test", "build")
    }
    return {
        "schema_version": "1.0",
        "scenario_id": "voice-clone-v1",
        "build_id": build_id,
        "gates": gates,
        "final_verdict": "pass",
        "source": {
            "path": ".ae-state/product-evidence/business-evidence.json",
            "sha256": "b" * 64,
            "bytes": 128,
        },
    }


def test_complete_product_evidence_passes(tmp_path) -> None:
    assert evaluate_product_evidence(
        _evidence(tmp_path), evidence_root=tmp_path
    )["status"] == "pass"


def test_product_evidence_rejects_claim_only_usage(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence.pop("usage")
    with pytest.raises(ProductAcceptanceError, match="USAGE_NUMERIC_EVIDENCE_MISSING"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_product_evidence_enforces_input_budget(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["usage"]["input_tokens"] = 1_000_001
    with pytest.raises(ProductAcceptanceError, match="CODEX_INPUT_BUDGET_EXCEEDED"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_claude_cost_policy_is_explicit_without_changing_default(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["host"] = "claude-code"
    evidence["usage"]["cost_usd"] = 2.5

    with pytest.raises(ProductAcceptanceError, match="CLAUDE_COST_BUDGET_EXCEEDED"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)

    verdict = evaluate_product_evidence(
        evidence,
        evidence_root=tmp_path,
        max_claude_cost_usd=3.0,
    )
    assert verdict["policy"] == {"max_claude_cost_usd": 3.0}


@pytest.mark.parametrize("value", [math.nan, math.inf, -1.0])
def test_claude_cost_policy_rejects_invalid_limit(value: float) -> None:
    with pytest.raises(ProductAcceptanceError, match="CLAUDE_COST_POLICY_INVALID"):
        evaluate_product_evidence(
            {"host": "codex"},
            max_claude_cost_usd=value,
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_product_acceptance_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ProductAcceptanceError, match="USAGE_NUMERIC_EVIDENCE_MISSING"):
        _number(value, "USAGE_NUMERIC_EVIDENCE_MISSING")


def test_product_evidence_resolves_runtime_source_isolation(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["installation"]["development_root"] = evidence["installation"]["runtime_root"]
    with pytest.raises(ProductAcceptanceError, match="RUNTIME_SOURCE_NOT_ISOLATED"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_product_evidence_requires_marketplace_build_binding(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["installation"] = {
        **evidence["installation"],
        "source_kind": "archive_smoke",
        "source_ref": "release.tar.gz",
        "source_build_id": evidence["build_id"],
        "source_content_sha256": "abc" * 21 + "a",
    }
    with pytest.raises(
        ProductAcceptanceError,
        match="INSTALLATION_SOURCE_EVIDENCE_MISSING",
    ):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_single_host_release_gate_cannot_bypass_artifact(tmp_path) -> None:
    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_ARTIFACT_MISSING"):
        evaluate_host_evidence(_evidence(tmp_path), evidence_root=tmp_path)


@pytest.mark.parametrize(("field", "value", "code"), [
    ("usage_status", "measurement_incomplete", "USAGE_INCOMPLETE"),
    ("project_state", "reused", "PROJECT_STATE_NOT_FRESH"),
    ("semantic_enforcement", "partial", "SEMANTIC_ENFORCEMENT_PARTIAL"),
    ("unexpected_stops", 1, "UNEXPECTED_STOP"),
    ("unapproved_changes", 1, "UNAPPROVED_DESIGN_CHANGE"),
])
def test_incomplete_product_evidence_blocks_release(
    field: str, value: object, code: str,
) -> None:
    evidence = _evidence()
    evidence[field] = value

    with pytest.raises(ProductAcceptanceError, match=code):
        evaluate_product_evidence(evidence)


def test_not_run_canary_cannot_be_reported_as_product_pass() -> None:
    evidence = _evidence()
    evidence["canary"] = {"status": "not_run"}

    with pytest.raises(ProductAcceptanceError, match="CANARY_NOT_PASSED"):
        evaluate_product_evidence(evidence)


def test_release_requires_both_hosts_on_same_build(tmp_path) -> None:
    import hashlib
    import json
    evidences = []
    for host in ("codex", "claude-code"):
        evidence = {**_evidence(tmp_path / host), "host": host}
        if host == "claude-code":
            evidence["usage"] = {
                "input_tokens": 99_999,
                "cached_input_tokens": 80_001,
                "output_tokens": 5_001,
                "cost_usd": 1.5,
            }
        usage = evidence["usage"]
        artifact = tmp_path / f"{host}.json"
        payload = {
            "schema_version": "1.1", "host": host,
            "build_id": evidence["build_id"],
            "installed_build_id": evidence["build_id"],
            "build_identity_preflight": {
                "status": "pass",
                "build_id": evidence["build_id"],
                "version": "5.8.0-rc.5",
                "source_kind": "packaged",
            },
            "plugin_discovered": True,
            "business_evidence": _business_evidence_payload(evidence["build_id"]),
            "runtime_root": evidence["installation"]["runtime_root"],
            "event_types": ["ActionIssued", "ResultAccepted", "LoopCompleted"],
            "terminal_action": {
                "action": "done", "reason_code": "GOAL_ACHIEVED",
                "acceptance_summary": _TERMINAL_ACCEPTANCE_SUMMARY,
            },
            "trajectory": {
                "invocation_count": 3, "attempt_count": 3,
                "manual_protocol_repairs": 0,
                "unexpected_stops": 0, "traceability_complete": True,
                "final_disposition": "TERMINAL",
            },
            "action_receipts": [
                {
                    "action_message_id": f"action-{index}",
                    "host_context_id": f"context-{index}",
                    "stage": ("architect", "developer", "critic")[index],
                    "build_id": evidence["build_id"],
                    "status": "completed",
                    "usage": {
                        key: (value // 3 if isinstance(value, int) else value / 3)
                        for key, value in usage.items() if value is not None
                    },
                }
                for index in range(3)
            ],
        }
        payload["attempt_receipts"] = list(payload["action_receipts"])
        payload["machine_claims"] = {
            "usage_status": "complete",
            "unexpected_stops": 0,
            "manual_protocol_repairs": 0,
            "traceability_complete": True,
        }
        payload["native_result_manifest"] = [
            {
                "action_message_id": f"action-{index}",
                "worker_id": f"worker-{index}",
                "path": f".ae-state/host-runtime/native-results/{index}.json",
                "sha256": "a" * 64,
                "bytes": 1,
            }
            for index in range(3)
        ]
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        evidences.append({**evidence, "evidence_artifact": {
            "path": artifact.name, "sha256": digest,
        }})

    verdict = evaluate_release_evidence(
        evidences,
        evidence_root=tmp_path,
        candidate_build_info={
            "version": "5.8.0-rc.5",
            "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
            "content_sha256": "a" * 64,
        },
    )

    assert verdict["status"] == "pass"
    assert verdict["policy"] == {"max_claude_cost_usd": 2.0}
    assert verdict["hosts"] == ["claude-code", "codex"]


def test_candidate_archive_build_identity_is_read_from_package(tmp_path) -> None:
    from scripts import product_acceptance

    archive = tmp_path / "candidate.tar.gz"
    build_info = tmp_path / "build-info.json"
    build_info.write_text(json.dumps({
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "content_sha256": "a" * 64,
    }), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as package:
        package.add(build_info, arcname="build-info.json")

    reader = getattr(product_acceptance, "_read_candidate_build_info", None)
    assert callable(reader)
    assert reader(archive) == {
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        "content_sha256": "a" * 64,
    }


def test_release_rejects_reused_action_context(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    artifact = tmp_path / "codex.json"
    payload = {
        "schema_version": "1.1",
        "host": "codex",
        "build_id": evidence["build_id"],
        "installed_build_id": evidence["build_id"],
        "plugin_discovered": True,
        "business_evidence": _business_evidence_payload(evidence["build_id"]),
        "runtime_root": evidence["installation"]["runtime_root"],
        "event_types": ["ActionIssued", "ResultAccepted", "LoopCompleted"],
        "terminal_action": {
            "action": "done",
            "acceptance_summary": _TERMINAL_ACCEPTANCE_SUMMARY,
        },
        "trajectory": {
            "invocation_count": 3, "attempt_count": 3,
            "manual_protocol_repairs": 0,
            "unexpected_stops": 0, "traceability_complete": True,
            "final_disposition": "TERMINAL",
        },
        "action_receipts": [
            {"action_message_id": f"a-{i}", "host_context_id": "reused",
             "stage": ("architect", "developer", "critic")[i],
             "build_id": evidence["build_id"], "status": "completed", "usage": {
                 "input_tokens": 300_000,
                 "cached_input_tokens": 266_667,
                 "output_tokens": 3_333,
             }}
            for i in range(3)
        ],
    }
    payload["attempt_receipts"] = [
        {**receipt, "host_context_id": f"context-{index}"}
        for index, receipt in enumerate(payload["action_receipts"])
    ]
    payload["machine_claims"] = {
        "usage_status": "complete",
        "unexpected_stops": 0,
        "manual_protocol_repairs": 0,
        "traceability_complete": True,
    }
    payload["native_result_manifest"] = [
        {
            "action_message_id": f"a-{index}",
            "worker_id": f"worker-{index}",
            "path": f".ae-state/host-runtime/native-results/{index}.json",
            "sha256": "a" * 64,
            "bytes": 1,
        }
        for index in range(3)
    ]
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    evidence["evidence_artifact"] = {"path": artifact.name, "sha256": digest}
    with pytest.raises(ProductAcceptanceError, match="ACTION_CONTEXT_REUSED"):
        evaluate_release_evidence(
            [evidence, {**evidence, "host": "claude-code"}],
            evidence_root=tmp_path,
        )


def test_release_rejects_duplicate_host_evidence(tmp_path) -> None:
    artifact = tmp_path / "evidence.jsonl"
    artifact.write_text("evidence", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    codex = {**_evidence(), "evidence_artifact": {
        "path": artifact.name, "sha256": digest,
    }}
    claude = {**codex, "host": "claude-code"}

    with pytest.raises(ProductAcceptanceError, match="BOTH_HOSTS_REQUIRED"):
        evaluate_release_evidence([codex, claude, codex], evidence_root=tmp_path)


def test_release_rejects_artifact_that_does_not_prove_its_claims(tmp_path) -> None:
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{}', encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    base = {**_evidence(), "evidence_artifact": {
        "path": artifact.name, "sha256": digest,
    }}

    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_ARTIFACT_CLAIMS_INVALID"):
        evaluate_release_evidence(
            [base, {**base, "host": "claude-code"}], evidence_root=tmp_path,
        )


def test_release_rejects_terminal_without_acceptance_boundary(tmp_path) -> None:
    import hashlib

    evidence = _evidence(tmp_path)
    artifact = tmp_path / "codex.json"
    payload = {
        "schema_version": "1.1",
        "host": "codex",
        "build_id": evidence["build_id"],
        "installed_build_id": evidence["build_id"],
        "plugin_discovered": True,
        "runtime_root": evidence["installation"]["runtime_root"],
        "event_types": ["ActionIssued", "ResultAccepted", "LoopCompleted"],
        "terminal_action": {"action": "done"},
        "trajectory": {
            "invocation_count": 3, "manual_protocol_repairs": 0,
            "unexpected_stops": 0, "traceability_complete": True,
            "final_disposition": "TERMINAL",
        },
        "action_receipts": [],
    }
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    evidence["evidence_artifact"] = {
        "path": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_ARTIFACT_CLAIMS_INVALID"):
        evaluate_host_evidence(evidence, evidence_root=tmp_path)


def test_release_rejects_artifact_hash_or_build_mismatch(tmp_path) -> None:
    artifact = tmp_path / "evidence.jsonl"
    artifact.write_text("evidence", encoding="utf-8")
    base = {**_evidence(), "evidence_artifact": {
        "path": artifact.name, "sha256": "0" * 64,
    }}
    with pytest.raises(ProductAcceptanceError, match="EVIDENCE_ARTIFACT_MISMATCH"):
        evaluate_release_evidence(
            [base, {**base, "host": "claude-code"}], evidence_root=tmp_path,
        )
