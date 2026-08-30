"""Phase 82 T445：分层真实产品证据门禁。"""

from __future__ import annotations

import json

import pytest

from scripts.product_acceptance import (
    ProductAcceptanceError,
    _validate_machine_claims,
    evaluate_host_evidence,
    evaluate_product_evidence,
    evaluate_release_evidence,
)


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
        "build_id": "5.8.0-rc.5+sha256.abc",
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


def test_complete_product_evidence_passes(tmp_path) -> None:
    assert evaluate_product_evidence(
        _evidence(tmp_path), evidence_root=tmp_path
    )["status"] == "pass"


def test_product_evidence_rejects_claim_only_usage(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence.pop("usage")
    with pytest.raises(ProductAcceptanceError, match="USAGE_NUMERIC_EVIDENCE_MISSING"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_product_evidence_enforces_host_budget(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["usage"]["input_tokens"] = 1_000_001
    with pytest.raises(ProductAcceptanceError, match="CODEX_INPUT_BUDGET_EXCEEDED"):
        evaluate_product_evidence(evidence, evidence_root=tmp_path)


def test_product_evidence_resolves_runtime_source_isolation(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    evidence["installation"]["development_root"] = evidence["installation"]["runtime_root"]
    with pytest.raises(ProductAcceptanceError, match="RUNTIME_SOURCE_NOT_ISOLATED"):
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
        artifact.write_text(json.dumps({
            "schema_version": "1.1", "host": host,
            "build_id": evidence["build_id"],
            "installed_build_id": evidence["build_id"],
            "plugin_discovered": True,
            "runtime_root": evidence["installation"]["runtime_root"],
            "event_types": ["ActionIssued", "ResultAccepted", "LoopCompleted"],
            "terminal_action": {
                "action": "done", "reason_code": "GOAL_ACHIEVED",
                "acceptance_summary": _TERMINAL_ACCEPTANCE_SUMMARY,
            },
            "trajectory": {
                "invocation_count": 3, "manual_protocol_repairs": 0,
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
        }), encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        evidences.append({**evidence, "evidence_artifact": {
            "path": artifact.name, "sha256": digest,
        }})

    verdict = evaluate_release_evidence(evidences, evidence_root=tmp_path)

    assert verdict["status"] == "pass"
    assert verdict["hosts"] == ["claude-code", "codex"]


def test_release_rejects_reused_action_context(tmp_path) -> None:
    evidence = _evidence(tmp_path)
    artifact = tmp_path / "codex.json"
    artifact.write_text(json.dumps({
        "schema_version": "1.1",
        "host": "codex",
        "build_id": evidence["build_id"],
        "installed_build_id": evidence["build_id"],
        "plugin_discovered": True,
        "runtime_root": evidence["installation"]["runtime_root"],
        "event_types": ["ActionIssued", "ResultAccepted", "LoopCompleted"],
        "terminal_action": {
            "action": "done",
            "acceptance_summary": _TERMINAL_ACCEPTANCE_SUMMARY,
        },
        "trajectory": {
            "invocation_count": 3, "manual_protocol_repairs": 0,
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
    }), encoding="utf-8")
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
