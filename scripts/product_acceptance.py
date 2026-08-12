"""校验真实 Claude Code/Codex 产品验收证据，不执行或伪造宿主运行。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class ProductAcceptanceError(ValueError):
    """产品证据不完整或不满足发布门禁。"""


def evaluate_product_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("host") not in {"claude-code", "codex"}:
        raise ProductAcceptanceError("HOST_INVALID")
    build_id = evidence.get("build_id")
    if not isinstance(build_id, str) or "+sha256." not in build_id:
        raise ProductAcceptanceError("BUILD_ID_INVALID")
    if evidence.get("project_state") != "fresh":
        raise ProductAcceptanceError("PROJECT_STATE_NOT_FRESH")
    if evidence.get("semantic_enforcement") != "full":
        raise ProductAcceptanceError("SEMANTIC_ENFORCEMENT_PARTIAL")
    if evidence.get("usage_status") != "complete":
        raise ProductAcceptanceError("USAGE_INCOMPLETE")
    if evidence.get("unexpected_stops") != 0:
        raise ProductAcceptanceError("UNEXPECTED_STOP")
    if evidence.get("unapproved_changes") != 0:
        raise ProductAcceptanceError("UNAPPROVED_DESIGN_CHANGE")
    installation = evidence.get("installation")
    if (
        not isinstance(installation, dict)
        or installation.get("status") != "pass"
        or installation.get("discovered") is not True
    ):
        raise ProductAcceptanceError("PRODUCT_INSTALL_NOT_VERIFIED")

    canary = evidence.get("canary")
    if not isinstance(canary, dict) or canary.get("status") != "pass":
        raise ProductAcceptanceError("CANARY_NOT_PASSED")
    required_stages = {"architect", "developer", "critic"}
    if not required_stages.issubset(set(canary.get("stages", []))):
        raise ProductAcceptanceError("CANARY_STAGES_INCOMPLETE")
    if canary.get("recovery_verified") is not True:
        raise ProductAcceptanceError("CANARY_RECOVERY_NOT_VERIFIED")

    golden = evidence.get("golden_project")
    if not isinstance(golden, dict) or golden.get("status") != "pass":
        raise ProductAcceptanceError("GOLDEN_PROJECT_NOT_PASSED")
    gates = {"typecheck", "unit_test", "build"}
    if not gates.issubset(set(golden.get("business_gates", []))):
        raise ProductAcceptanceError("BUSINESS_GATES_INCOMPLETE")
    if golden.get("final_verdict") != "pass":
        raise ProductAcceptanceError("FINAL_VERDICT_NOT_PASSED")
    return {
        "status": "pass",
        "host": evidence["host"],
        "build_id": build_id,
        "levels": {"canary": "pass", "golden_project": "pass"},
    }


def evaluate_release_evidence(
    evidences: list[dict[str, Any]],
    *,
    evidence_root: Path,
) -> dict[str, Any]:
    """验证同一候选制品的双宿主证据和内容寻址 artifact。"""

    if (
        len(evidences) != 2
        or {item.get("host") for item in evidences} != {"claude-code", "codex"}
    ):
        raise ProductAcceptanceError("BOTH_HOSTS_REQUIRED")
    build_ids = {item.get("build_id") for item in evidences}
    if len(build_ids) != 1:
        raise ProductAcceptanceError("BUILD_ID_MISMATCH")
    results = []
    root = evidence_root.resolve()
    for evidence in evidences:
        artifact = evidence.get("evidence_artifact")
        if not isinstance(artifact, dict):
            raise ProductAcceptanceError("EVIDENCE_ARTIFACT_MISSING")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ProductAcceptanceError("EVIDENCE_ARTIFACT_INVALID")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ProductAcceptanceError("EVIDENCE_ARTIFACT_INVALID")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ProductAcceptanceError("EVIDENCE_ARTIFACT_MISMATCH")
        results.append(evaluate_product_evidence(evidence))
    return {
        "status": "pass",
        "build_id": next(iter(build_ids)),
        "hosts": sorted(item["host"] for item in results),
        "levels": {"L3": "pass", "L4": "pass"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True, action="append")
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.evidence]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise ProductAcceptanceError("EVIDENCE_INVALID")
    verdict = (
        evaluate_product_evidence(payloads[0])
        if len(payloads) == 1
        else evaluate_release_evidence(payloads, evidence_root=args.evidence_root)
    )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
