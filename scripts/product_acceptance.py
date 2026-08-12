"""校验真实 Claude Code/Codex 产品验收证据，不执行或伪造宿主运行。"""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProductAcceptanceError("EVIDENCE_INVALID")
    print(json.dumps(evaluate_product_evidence(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
