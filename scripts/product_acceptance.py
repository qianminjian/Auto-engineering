"""校验真实 Claude Code/Codex 产品验收证据，不执行或伪造宿主运行。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

# The validator is documented as a standalone command from an extracted
# Release tree.  Make that entrypoint independent of editable installs and
# the caller's current working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auto_engineering.build_identity import validate_build_info  # noqa: E402


class ProductAcceptanceError(ValueError):
    """产品证据不完整或不满足发布门禁。"""


class UsageEvidence(TypedDict):
    input_tokens: int | float
    cached_input_tokens: int | float
    output_tokens: int | float
    cost_usd: int | float | None


DEFAULT_CLAUDE_COST_LIMIT_USD = 2.0
_RECOVERY_METHOD_STATUS = {
    "coordinator_repair": "worker_outcomes_committed",
    "native_outcome_resume": "native_outcomes_ready",
}


def _validate_cost_limit(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ProductAcceptanceError("CLAUDE_COST_POLICY_INVALID")
    return float(value)


def _validate_declared_cost_policy(
    payload: dict[str, Any],
    *,
    max_claude_cost_usd: float,
) -> None:
    declared = payload.get("acceptance_policy")
    if declared is None:
        return  # v1.1 旧 evidence 兼容；新 collector 始终写入。
    if (
        not isinstance(declared, dict)
        or declared.get("max_claude_cost_usd")
        != max_claude_cost_usd
    ):
        raise ProductAcceptanceError("ACCEPTANCE_POLICY_MISMATCH")


def _read_candidate_build_info(archive: Path) -> dict[str, str]:
    """从候选 archive 读取身份，避免验收证据自带 Build 声明。"""

    try:
        with tarfile.open(archive, "r:gz") as package:
            member = package.getmember("build-info.json")
            if not member.isfile():
                raise ProductAcceptanceError("CANDIDATE_BUILD_INFO_INVALID")
            stream = package.extractfile(member)
            if stream is None:
                raise ProductAcceptanceError("CANDIDATE_BUILD_INFO_INVALID")
            payload = json.loads(stream.read().decode("utf-8"))
    except ProductAcceptanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tarfile.TarError) as exc:
        raise ProductAcceptanceError("CANDIDATE_BUILD_INFO_INVALID") from exc
    try:
        return validate_build_info(payload)
    except ValueError as exc:
        raise ProductAcceptanceError("CANDIDATE_BUILD_INFO_INVALID") from exc


def _number(value: Any, code: str) -> int | float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ProductAcceptanceError(code)
    return value


def _validate_source_file(
    source_root: Path,
    *,
    relative_path: str,
    expected_sha256: str,
    expected_bytes: Any,
    missing_code: str,
    mismatch_code: str,
) -> None:
    """重新读取内容寻址证据，不能只相信 artifact 中的 hash 声明。"""

    if (
        not relative_path
        or Path(relative_path).is_absolute()
        or isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
    ):
        raise ProductAcceptanceError(missing_code)
    root = source_root.resolve()
    path = (root / relative_path).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise ProductAcceptanceError(missing_code)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProductAcceptanceError(missing_code) from exc
    if len(raw) != expected_bytes or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ProductAcceptanceError(mismatch_code)


def _validate_usage(
    evidence: dict[str, Any],
    *,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
) -> UsageEvidence:
    max_claude_cost_usd = _validate_cost_limit(max_claude_cost_usd)
    _validate_declared_cost_policy(
        evidence,
        max_claude_cost_usd=max_claude_cost_usd,
    )
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
    elif normalized["cost_usd"] > max_claude_cost_usd:
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


def _validate_installation_source(
    installation: dict[str, Any],
    *,
    build_id: str,
) -> None:
    """把真实产品安装来源绑定到完整候选制品摘要。"""

    source_kind = installation.get("source_kind")
    source_ref = installation.get("source_ref")
    source_build_id = installation.get("source_build_id")
    content_sha256 = installation.get("source_content_sha256")
    if (
        source_kind != "marketplace"
        or not isinstance(source_ref, str)
        or not source_ref.strip()
        or not isinstance(source_build_id, str)
        or not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(char not in "0123456789abcdef" for char in content_sha256)
    ):
        raise ProductAcceptanceError("INSTALLATION_SOURCE_EVIDENCE_MISSING")
    if (
        source_build_id != build_id
        or not build_id.endswith(content_sha256[:16])
    ):
        raise ProductAcceptanceError("INSTALLATION_BUILD_ID_MISMATCH")


def _validate_build_identity_preflight(
    artifact: dict[str, Any],
    candidate_build_info: dict[str, str],
) -> None:
    """要求真实产品 artifact 证明首个 Loop Action 前执行了身份预检。"""

    preflight = artifact.get("build_identity_preflight")
    if not isinstance(preflight, dict):
        raise ProductAcceptanceError("PRODUCT_BUILD_IDENTITY_PREFLIGHT_MISSING")
    if (
        preflight.get("status") != "pass"
        or preflight.get("build_id") != candidate_build_info["build_id"]
        or preflight.get("version") != candidate_build_info["version"]
        or preflight.get("source_kind") != "packaged"
    ):
        raise ProductAcceptanceError("PRODUCT_BUILD_IDENTITY_PREFLIGHT_MISMATCH")


def evaluate_product_evidence(
    evidence: dict[str, Any],
    *,
    evidence_root: Path | None = None,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
) -> dict[str, Any]:
    max_claude_cost_usd = _validate_cost_limit(max_claude_cost_usd)
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
    _validate_installation_source(installation, build_id=build_id)
    _validate_runtime_source(installation, evidence_root=evidence_root)
    _validate_usage(evidence, max_claude_cost_usd=max_claude_cost_usd)

    canary = evidence.get("canary")
    if not isinstance(canary, dict) or canary.get("status") != "pass":
        raise ProductAcceptanceError("CANARY_NOT_PASSED")
    required_stages = {"architect", "developer", "critic"}
    if not required_stages.issubset(set(canary.get("stages", []))):
        raise ProductAcceptanceError("CANARY_STAGES_INCOMPLETE")
    if (
        canary.get("recovery_verified") is not True
        or canary.get("recovery_method") not in _RECOVERY_METHOD_STATUS
        or not isinstance(canary.get("recovery_action_message_id"), str)
        or not canary["recovery_action_message_id"]
    ):
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
        "policy": {"max_claude_cost_usd": max_claude_cost_usd},
        "levels": {"canary": "pass", "golden_project": "pass"},
    }


def _validate_receipts(
    artifact: dict[str, Any],
    evidence: dict[str, Any],
    *,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
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
    expected = _validate_usage(
        evidence,
        max_claude_cost_usd=max_claude_cost_usd,
    )
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


def _validate_attempt_receipts(
    artifact: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    """校验完整尝试流，不能只保留成功回执来隐藏失败历史。"""
    attempts = artifact.get("attempt_receipts")
    if attempts is None:
        raise ProductAcceptanceError("ACTION_ATTEMPTS_INVALID")
    if not isinstance(attempts, list) or not attempts:
        raise ProductAcceptanceError("ACTION_ATTEMPTS_INVALID")
    contexts: set[str] = set()
    for receipt in attempts:
        if not isinstance(receipt, dict):
            raise ProductAcceptanceError("ACTION_ATTEMPTS_INVALID")
        context_id = receipt.get("host_context_id")
        if (
            not isinstance(context_id, str)
            or context_id in contexts
            or receipt.get("build_id") != evidence.get("build_id")
            or receipt.get("status") not in {"completed", "failed", "cancelled", "timed_out"}
        ):
            raise ProductAcceptanceError("ACTION_ATTEMPTS_INVALID")
        contexts.add(context_id)


def _validate_machine_claims(
    artifact: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    """校验 Journal 从事件/回执推导的事实，防止外层声明自相矛盾。

    当前 Journal 始终写入该字段；真实验收报告不能只修改调用者提供的摘要字段
    来伪造通过。
    """

    claims = artifact.get("machine_claims")
    if claims is None:
        raise ProductAcceptanceError("EVIDENCE_MACHINE_CLAIMS_INVALID")
    if not isinstance(claims, dict):
        raise ProductAcceptanceError("EVIDENCE_MACHINE_CLAIMS_INVALID")
    trajectory = artifact.get("trajectory")
    if not isinstance(trajectory, dict):
        raise ProductAcceptanceError("EVIDENCE_MACHINE_CLAIMS_INVALID")
    if (
        claims.get("usage_status") != evidence.get("usage_status")
        or claims.get("unexpected_stops") != evidence.get("unexpected_stops")
        or claims.get("manual_protocol_repairs")
        != trajectory.get("manual_protocol_repairs")
        or claims.get("traceability_complete")
        != trajectory.get("traceability_complete")
    ):
        raise ProductAcceptanceError("EVIDENCE_MACHINE_CLAIMS_MISMATCH")


def _validate_native_result_manifest(
    artifact: dict[str, Any],
    *,
    source_root: Path | None = None,
) -> None:
    """校验采集器写入的原生 Worker 回包清单结构。

    清单不是重新信任宿主声明；它是 collector 已从项目绑定路径读取的摘要。
    这里仍拒绝空项、绝对路径、重复 Action/Worker 和伪造的空字节证据，避免
    artifact 在后续复制或审查时悄悄丢失原生回包边界。
    """

    manifest = artifact.get("native_result_manifest")
    if manifest is None:
        raise ProductAcceptanceError("NATIVE_RESULT_MANIFEST_INVALID")
    if not isinstance(manifest, list) or not manifest:
        raise ProductAcceptanceError("NATIVE_RESULT_MANIFEST_INVALID")
    identities: set[tuple[str, str]] = set()
    for item in manifest:
        if not isinstance(item, dict):
            raise ProductAcceptanceError("NATIVE_RESULT_MANIFEST_INVALID")
        action_id = item.get("action_message_id")
        worker_id = item.get("worker_id")
        relative = item.get("path")
        digest = item.get("sha256")
        size = item.get("bytes")
        if (
            not isinstance(action_id, str)
            or not isinstance(worker_id, str)
            or not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise ProductAcceptanceError("NATIVE_RESULT_MANIFEST_INVALID")
        identity = (action_id, worker_id)
        if identity in identities:
            raise ProductAcceptanceError("NATIVE_RESULT_MANIFEST_INVALID")
        identities.add(identity)
        if source_root is not None:
            _validate_source_file(
                source_root,
                relative_path=relative,
                expected_sha256=digest,
                expected_bytes=size,
                missing_code="NATIVE_RESULT_EVIDENCE_MISSING",
                mismatch_code="NATIVE_RESULT_EVIDENCE_MISMATCH",
            )


def _validate_business_evidence(
    artifact: dict[str, Any],
    *,
    source_root: Path | None = None,
) -> None:
    """校验当前采集器生成的结构化业务证明。"""

    business = artifact.get("business_evidence")
    if business is None:
        raise ProductAcceptanceError("BUSINESS_EVIDENCE_MISSING")
    if not isinstance(business, dict):
        raise ProductAcceptanceError("BUSINESS_EVIDENCE_INVALID")
    if (
        business.get("schema_version") != "1.0"
        or not isinstance(business.get("build_id"), str)
        or business.get("final_verdict") != "pass"
    ):
        raise ProductAcceptanceError("BUSINESS_EVIDENCE_INVALID")
    gates = business.get("gates")
    required = {"typecheck", "unit_test", "build"}
    if not isinstance(gates, dict) or not required.issubset(gates):
        raise ProductAcceptanceError("BUSINESS_GATE_INCOMPLETE")
    for name in required:
        gate = gates.get(name)
        if (
            not isinstance(gate, dict)
            or gate.get("status") != "pass"
            or not isinstance(gate.get("command"), list)
            or not gate["command"]
            or not all(isinstance(part, str) and part for part in gate["command"])
            or gate.get("exit_code") != 0
            or not isinstance(gate.get("evidence_path"), str)
            or Path(gate["evidence_path"]).is_absolute()
            or not isinstance(gate.get("evidence_sha256"), str)
            or len(gate["evidence_sha256"]) != 64
        ):
            raise ProductAcceptanceError("BUSINESS_GATE_INVALID")
        if source_root is not None:
            _validate_source_file(
                source_root,
                relative_path=gate["evidence_path"],
                expected_sha256=gate["evidence_sha256"],
                expected_bytes=gate.get("evidence_bytes"),
                missing_code="BUSINESS_GATE_EVIDENCE_MISSING",
                mismatch_code="BUSINESS_GATE_EVIDENCE_MISMATCH",
            )
    source = business.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("path"), str)
        or Path(source["path"]).is_absolute()
        or not isinstance(source.get("sha256"), str)
        or len(source["sha256"]) != 64
        or isinstance(source.get("bytes"), bool)
        or not isinstance(source.get("bytes"), int)
        or source["bytes"] <= 0
    ):
        raise ProductAcceptanceError("BUSINESS_EVIDENCE_INVALID")
    if source_root is not None:
        _validate_source_file(
            source_root,
            relative_path=source["path"],
            expected_sha256=source["sha256"],
            expected_bytes=source.get("bytes"),
            missing_code="BUSINESS_EVIDENCE_SOURCE_MISSING",
            mismatch_code="BUSINESS_EVIDENCE_SOURCE_MISMATCH",
        )


def _validate_host_usage_attestation(
    artifact: dict[str, Any],
    *,
    source_root: Path | None = None,
) -> None:
    """校验 Claude 成本来自原始宿主输出，而不是人工输入数字。"""

    attestation = artifact.get("host_usage_attestation")
    if attestation is None:
        return  # 兼容旧版 artifact；新 Claude collector 始终写入
    if not isinstance(attestation, dict):
        raise ProductAcceptanceError("HOST_USAGE_ATTESTATION_INVALID")
    path = attestation.get("path")
    digest = attestation.get("sha256")
    size = attestation.get("bytes")
    if (
        not isinstance(path, str)
        or not path
        or Path(path).is_absolute()
        or "\\" in path
        or ".." in Path(path).parts
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size <= 0
        or attestation.get("source") != "claude-cli-result"
    ):
        raise ProductAcceptanceError("HOST_USAGE_ATTESTATION_INVALID")
    if source_root is not None:
        _validate_source_file(
            source_root,
            relative_path=path,
            expected_sha256=digest,
            expected_bytes=size,
            missing_code="HOST_USAGE_ATTESTATION_MISSING",
            mismatch_code="HOST_USAGE_ATTESTATION_MISMATCH",
        )


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
    source_root: Path | None = None,
    candidate_build_info: dict[str, str] | None = None,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
) -> dict[str, Any]:
    """验证单宿主声明与同一内容寻址 artifact，禁止绕过事实证据。"""
    max_claude_cost_usd = _validate_cost_limit(max_claude_cost_usd)
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
        or (
            "attempt_receipts" in artifact_payload
            and trajectory.get("attempt_count")
            != len(artifact_payload.get("attempt_receipts", []))
        )
    ):
        raise ProductAcceptanceError("EVIDENCE_ARTIFACT_CLAIMS_INVALID")
    if candidate_build_info is not None and (
        evidence.get("build_id") != candidate_build_info["build_id"]
        or artifact_payload.get("build_id") != candidate_build_info["build_id"]
        or installation.get("source_content_sha256")
        != candidate_build_info["content_sha256"]
    ):
        raise ProductAcceptanceError("CANDIDATE_BUILD_MISMATCH")
    if candidate_build_info is not None:
        _validate_build_identity_preflight(artifact_payload, candidate_build_info)
    _validate_business_evidence(artifact_payload, source_root=source_root)
    business_evidence = artifact_payload.get("business_evidence")
    if isinstance(business_evidence, dict) and business_evidence.get("build_id") != evidence.get("build_id"):
        raise ProductAcceptanceError("BUSINESS_EVIDENCE_BUILD_MISMATCH")
    _validate_declared_cost_policy(
        artifact_payload,
        max_claude_cost_usd=max_claude_cost_usd,
    )
    _validate_terminal_acceptance_summary(terminal_action)
    _validate_machine_claims(artifact_payload, evidence)
    _validate_native_result_manifest(artifact_payload, source_root=source_root)
    _validate_host_usage_attestation(artifact_payload, source_root=source_root)
    _validate_attempt_receipts(artifact_payload, evidence)
    _validate_receipts(
        artifact_payload,
        evidence,
        max_claude_cost_usd=max_claude_cost_usd,
    )
    return evaluate_product_evidence(
        evidence,
        evidence_root=root,
        max_claude_cost_usd=max_claude_cost_usd,
    )


def evaluate_release_evidence(
    evidences: list[dict[str, Any]],
    *,
    evidence_root: Path,
    source_root: Path | None = None,
    source_roots: Mapping[str, Path] | None = None,
    candidate_build_info: dict[str, str] | None = None,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
) -> dict[str, Any]:
    """验证同一候选制品的双宿主证据和内容寻址 artifact。"""
    max_claude_cost_usd = _validate_cost_limit(max_claude_cost_usd)

    if (
        len(evidences) != 2
        or {item.get("host") for item in evidences} != {"claude-code", "codex"}
    ):
        raise ProductAcceptanceError("BOTH_HOSTS_REQUIRED")
    build_ids = {item.get("build_id") for item in evidences}
    if len(build_ids) != 1:
        raise ProductAcceptanceError("BUILD_ID_MISMATCH")
    if source_roots is not None:
        expected_hosts = {"claude-code", "codex"}
        if set(source_roots) != expected_hosts:
            raise ProductAcceptanceError("PROJECT_ROOTS_INCOMPLETE")
    else:
        source_roots = {
            host: source_root
            for host in {"claude-code", "codex"}
            if source_root is not None
        }
    results = [
        evaluate_host_evidence(
            evidence,
            evidence_root=evidence_root,
            source_root=source_roots.get(evidence.get("host")),
            candidate_build_info=candidate_build_info,
            max_claude_cost_usd=max_claude_cost_usd,
        )
        for evidence in evidences
    ]
    return {
        "status": "pass",
        "build_id": next(iter(build_ids)),
        "hosts": sorted(item["host"] for item in results),
        "policy": {"max_claude_cost_usd": max_claude_cost_usd},
        "levels": {"L3": "pass", "L4": "pass"},
    }


def _parse_project_roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        host, separator, raw_path = value.partition("=")
        if (
            not separator
            or host not in {"claude-code", "codex"}
            or not raw_path
            or host in roots
        ):
            raise ProductAcceptanceError("PROJECT_ROOT_INVALID")
        roots[host] = Path(raw_path)
    return roots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True, action="append")
    parser.add_argument(
        "--archive", type=Path, required=True,
        help="本次验收使用的候选 Release archive",
    )
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--project-root", action="append", required=True, metavar="HOST=PATH",
        help="真实宿主项目根映射，例如 codex=/tmp/project；双宿主各传一次",
    )
    parser.add_argument(
        "--max-claude-cost-usd",
        type=float,
        default=DEFAULT_CLAUDE_COST_LIMIT_USD,
        help="本次验收声明的 Claude 成本上限；默认保持 2.0 美元兼容策略",
    )
    args = parser.parse_args()
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.evidence]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise ProductAcceptanceError("EVIDENCE_INVALID")
    project_roots = _parse_project_roots(args.project_root)
    if len(payloads) == 1:
        source_root = project_roots.get(payloads[0].get("host"))
        if source_root is None:
            raise ProductAcceptanceError("PROJECT_ROOT_INVALID")
    else:
        source_root = None
    verdict = (
        evaluate_host_evidence(
            payloads[0],
            evidence_root=args.evidence_root,
            source_root=source_root,
            candidate_build_info=_read_candidate_build_info(args.archive),
            max_claude_cost_usd=args.max_claude_cost_usd,
        )
        if len(payloads) == 1
        else evaluate_release_evidence(
            payloads,
            evidence_root=args.evidence_root,
            source_roots=project_roots,
            candidate_build_info=_read_candidate_build_info(args.archive),
            max_claude_cost_usd=args.max_claude_cost_usd,
        )
    )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
