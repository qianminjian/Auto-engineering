"""校验真实 Claude Code/Codex 产品验收证据，不执行或伪造宿主运行。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, TypedDict


class ProductAcceptanceError(ValueError):
    """产品证据不完整或不满足发布门禁。"""


class UsageEvidence(TypedDict):
    input_tokens: int | float
    cached_input_tokens: int | float
    output_tokens: int | float
    cost_usd: int | float | None


def _number(value: Any, code: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ProductAcceptanceError(code)
    return value


def _validate_usage(evidence: dict[str, Any]) -> UsageEvidence:
    usage = evidence.get("usage")
    if not isinstance(usage, dict):
        raise ProductAcceptanceError("USAGE_NUMERIC_EVIDENCE_MISSING")
    normalized: UsageEvidence = {
        "input_tokens": _number(
            usage.get("input_tokens"), "USAGE_NUMERIC_EVIDENCE_MISSING"
        ),
        "cached_input_tokens": _number(
            usage.get("cached_input_tokens"), "USAGE_NUMERIC_EVIDENCE_MISSING"
        ),
        "output_tokens": _number(
            usage.get("output_tokens"), "USAGE_NUMERIC_EVIDENCE_MISSING"
        ),
        "cost_usd": None,
    }
    cost = usage.get("cost_usd")
    normalized["cost_usd"] = (
        None if cost is None else _number(cost, "USAGE_NUMERIC_EVIDENCE_MISSING")
    )
    if evidence["host"] == "codex":
        if normalized["input_tokens"] > 1_000_000:
            raise ProductAcceptanceError("CODEX_INPUT_BUDGET_EXCEEDED")
        if normalized["cached_input_tokens"] > 1_500_000:
            raise ProductAcceptanceError("CODEX_CACHE_BUDGET_EXCEEDED")
    elif normalized["cost_usd"] is None:
        raise ProductAcceptanceError("USAGE_NUMERIC_EVIDENCE_MISSING")
    elif normalized["cost_usd"] > 2.0:
        raise ProductAcceptanceError("CLAUDE_COST_BUDGET_EXCEEDED")
    return normalized


def _validate_runtime_source(
    installation: dict[str, Any],
    *,
    evidence_root: Path | None,
) -> tuple[Path, Path]:
    runtime_value = installation.get("runtime_root")
    development_value = installation.get("development_root")
    if (
        installation.get("source_isolated") is not True
        or not isinstance(runtime_value, str)
        or not isinstance(development_value, str)
    ):
        raise ProductAcceptanceError("RUNTIME_SOURCE_EVIDENCE_MISSING")
    runtime_root = Path(runtime_value).resolve()
    development_root = Path(development_value).resolve()
    if evidence_root is not None and (
        not runtime_root.is_dir() or not development_root.is_dir()
    ):
        raise ProductAcceptanceError("RUNTIME_SOURCE_EVIDENCE_MISSING")
    if (
        runtime_root == development_root
        or runtime_root.is_relative_to(development_root)
        or development_root.is_relative_to(runtime_root)
    ):
        raise ProductAcceptanceError("RUNTIME_SOURCE_NOT_ISOLATED")
    return runtime_root, development_root


def evaluate_product_evidence(
    evidence: dict[str, Any],
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
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
    _validate_runtime_source(installation, evidence_root=evidence_root)
    _validate_usage(evidence)

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


def _validate_receipts(
    artifact: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    receipts = artifact.get("action_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ProductAcceptanceError("ACTION_RECEIPTS_MISSING")
    action_ids: set[str] = set()
    context_ids: set[str] = set()
    stages: set[str] = set()
    totals = {
        "input_tokens": 0.0,
        "cached_input_tokens": 0.0,
        "output_tokens": 0.0,
        "cost_usd": 0.0,
    }
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ProductAcceptanceError("ACTION_RECEIPTS_INVALID")
        action_id = receipt.get("action_message_id")
        context_id = receipt.get("host_context_id")
        stage = receipt.get("stage")
        if (
            not isinstance(action_id, str)
            or not isinstance(context_id, str)
            or not isinstance(stage, str)
            or receipt.get("build_id") != evidence.get("build_id")
            or receipt.get("status") != "completed"
        ):
            raise ProductAcceptanceError("ACTION_RECEIPTS_INVALID")
        if context_id in context_ids:
            raise ProductAcceptanceError("ACTION_CONTEXT_REUSED")
        action_ids.add(action_id)
        context_ids.add(context_id)
        stages.add(stage)
        receipt_usage = receipt.get("usage")
        if not isinstance(receipt_usage, dict):
            raise ProductAcceptanceError("ACTION_RECEIPTS_INVALID")
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            totals[key] += float(
                _number(receipt_usage.get(key), "ACTION_RECEIPTS_INVALID")
            )
        if "cost_usd" in receipt_usage:
            totals["cost_usd"] += float(
                _number(receipt_usage["cost_usd"], "ACTION_RECEIPTS_INVALID")
            )
    if not {"architect", "developer", "critic"}.issubset(stages):
        raise ProductAcceptanceError("ACTION_RECEIPT_STAGES_INCOMPLETE")
    expected = _validate_usage(evidence)
    expected_totals = {
        "input_tokens": float(expected["input_tokens"]),
        "cached_input_tokens": float(expected["cached_input_tokens"]),
        "output_tokens": float(expected["output_tokens"]),
    }
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        if not math.isclose(totals[key], expected_totals[key], abs_tol=0.001):
            raise ProductAcceptanceError("ACTION_USAGE_TOTAL_MISMATCH")
    if expected["cost_usd"] is not None and not math.isclose(
        totals["cost_usd"], float(expected["cost_usd"]), abs_tol=0.001
    ):
        raise ProductAcceptanceError("ACTION_USAGE_TOTAL_MISMATCH")


def _validate_terminal_acceptance_summary(terminal_action: dict[str, Any]) -> None:
    """终态必须携带 Core/产品验收边界，防止 done 被冒充发布完成。"""
    summary = terminal_action.get("acceptance_summary")
    if not isinstance(summary, dict):
        raise ProductAcceptanceError("TERMINAL_ACCEPTANCE_SUMMARY_MISSING")
    if (
        summary.get("scope") != "core"
        or summary.get("release_eligible") is not False
        or summary.get("status") not in {
            "core_verified_product_unverified", "core_incomplete",
        }
        or not isinstance(summary.get("verified_checks"), list)
        or not isinstance(summary.get("unverified_items"), list)
        or not summary["unverified_items"]
        or not isinstance(summary.get("coverage"), dict)
    ):
        raise ProductAcceptanceError("TERMINAL_ACCEPTANCE_SUMMARY_INVALID")
    coverage = summary["coverage"]
    verified = summary["verified_checks"]
    unverified = summary["unverified_items"]
    if coverage.get("verified") != len(verified) or coverage.get("total") != (
        len(verified) + len(unverified)
    ):
        raise ProductAcceptanceError("TERMINAL_ACCEPTANCE_SUMMARY_INVALID")


def evaluate_host_evidence(
    evidence: dict[str, Any],
    *,
    evidence_root: Path,
) -> dict[str, Any]:
    """验证单宿主声明与同一内容寻址 artifact，禁止绕过事实证据。"""
    root = evidence_root.resolve()
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
    try:
        artifact_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductAcceptanceError("EVIDENCE_ARTIFACT_INVALID") from exc
    if not isinstance(artifact_payload, dict):
        raise ProductAcceptanceError("EVIDENCE_ARTIFACT_INVALID")
    required_events = {"ActionIssued", "ResultAccepted", "LoopCompleted"}
    terminal_action = artifact_payload.get("terminal_action")
    trajectory = artifact_payload.get("trajectory")
    installation = evidence.get("installation")
    if (
        artifact_payload.get("schema_version") != "1.1"
        or artifact_payload.get("host") != evidence.get("host")
        or artifact_payload.get("build_id") != evidence.get("build_id")
        or artifact_payload.get("installed_build_id") != evidence.get("build_id")
        or artifact_payload.get("plugin_discovered") is not True
        or not isinstance(installation, dict)
        or Path(str(artifact_payload.get("runtime_root"))).resolve()
        != Path(str(installation.get("runtime_root"))).resolve()
        or not isinstance(terminal_action, dict)
        or terminal_action.get("action") != "done"
        or not required_events.issubset(set(artifact_payload.get("event_types", [])))
        or not isinstance(trajectory, dict)
        or trajectory.get("final_disposition") != "TERMINAL"
        or trajectory.get("unexpected_stops") != 0
        or trajectory.get("manual_protocol_repairs") != 0
        or trajectory.get("traceability_complete") is not True
        or trajectory.get("invocation_count")
        != len(artifact_payload.get("action_receipts", []))
    ):
        raise ProductAcceptanceError("EVIDENCE_ARTIFACT_CLAIMS_INVALID")
    _validate_terminal_acceptance_summary(terminal_action)
    _validate_receipts(artifact_payload, evidence)
    return evaluate_product_evidence(evidence, evidence_root=root)


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
    results = [
        evaluate_host_evidence(evidence, evidence_root=evidence_root)
        for evidence in evidences
    ]
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
        evaluate_host_evidence(payloads[0], evidence_root=args.evidence_root)
        if len(payloads) == 1
        else evaluate_release_evidence(payloads, evidence_root=args.evidence_root)
    )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
