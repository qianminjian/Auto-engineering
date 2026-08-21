"""Phase 82 T445：分层真实产品证据门禁。"""

from __future__ import annotations

import pytest

from scripts.product_acceptance import (
    ProductAcceptanceError,
    evaluate_product_evidence,
    evaluate_release_evidence,
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


def _evidence() -> dict[str, object]:
    return {
        "host": "codex",
        "build_id": "5.8.0-rc.5+sha256.abc",
        "project_state": "fresh",
        "semantic_enforcement": "full",
        "usage_status": "complete",
        "unexpected_stops": 0,
        "unapproved_changes": 0,
        "installation": {"status": "pass", "discovered": True},
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


def test_complete_product_evidence_passes() -> None:
    assert evaluate_product_evidence(_evidence())["status"] == "pass"


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
        artifact = tmp_path / f"{host}.json"
        artifact.write_text(json.dumps({
            "schema_version": "1.0", "host": host,
            "build_id": _evidence()["build_id"],
            "installed_build_id": _evidence()["build_id"],
            "plugin_discovered": True,
            "event_types": ["ActionIssued", "ResultAccepted"],
        }), encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        evidences.append({**_evidence(), "host": host, "evidence_artifact": {
            "path": artifact.name, "sha256": digest,
        }})

    verdict = evaluate_release_evidence(evidences, evidence_root=tmp_path)

    assert verdict["status"] == "pass"
    assert verdict["hosts"] == ["claude-code", "codex"]


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
