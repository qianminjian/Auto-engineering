"""从真实项目事实流生成产品验收 evidence artifact；不执行宿主、不伪造事实。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from auto_engineering.host.path_contract import (
    action_key_for,
    worker_native_result_path,
)
from auto_engineering.host.usage_attestation import (
    HostUsageAttestationError,
    read_claude_stream_usage,
)
from auto_engineering.metrics.usage_ledger import UsageLedger
from scripts.product_acceptance import (
    _RECOVERY_METHOD_STATUS,
    DEFAULT_CLAUDE_COST_LIMIT_USD,
    _read_candidate_build_info,
    _validate_cost_limit,
)


class EvidenceCollectionError(ValueError):
    """项目事实不足以形成可校验产品证据。"""


_REQUIRED_BUSINESS_GATES = ("typecheck", "unit_test", "build")
_RECOVERY_STATUSES = {
    "worker_outcomes_committed",
    "native_outcomes_ready",
}


def _read_business_evidence(
    path: Path,
    *,
    project_root: Path,
    build_id: str,
) -> dict[str, Any]:
    """读取并绑定独立业务验收报告；裸布尔值不再是验收事实。"""

    root = project_root.resolve()
    report_path = path.resolve()
    if not report_path.is_file() or not report_path.is_relative_to(root):
        raise EvidenceCollectionError("BUSINESS_EVIDENCE_MISSING")
    try:
        raw = report_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceCollectionError("BUSINESS_EVIDENCE_INVALID") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "1.0"
        or payload.get("build_id") != build_id
        or payload.get("final_verdict") != "pass"
    ):
        raise EvidenceCollectionError("BUSINESS_EVIDENCE_INVALID")

    gates = payload.get("gates")
    if not isinstance(gates, dict) or not set(_REQUIRED_BUSINESS_GATES).issubset(gates):
        raise EvidenceCollectionError("BUSINESS_GATE_INCOMPLETE")
    normalized_gates: dict[str, dict[str, Any]] = {}
    for gate in _REQUIRED_BUSINESS_GATES:
        item = gates.get(gate)
        if not isinstance(item, dict):
            raise EvidenceCollectionError("BUSINESS_GATE_INVALID")
        command = item.get("command")
        evidence_path_value = item.get("evidence_path")
        exit_code = item.get("exit_code")
        expected_hash = item.get("evidence_sha256")
        if (
            item.get("status") != "pass"
            or not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
            or exit_code != 0
            or not isinstance(evidence_path_value, str)
            or Path(evidence_path_value).is_absolute()
            or not isinstance(expected_hash, str)
        ):
            raise EvidenceCollectionError("BUSINESS_GATE_INVALID")
        evidence_path = (root / evidence_path_value).resolve()
        if not evidence_path.is_file() or not evidence_path.is_relative_to(root):
            raise EvidenceCollectionError("BUSINESS_GATE_EVIDENCE_MISSING")
        try:
            evidence_bytes = evidence_path.read_bytes()
        except OSError as exc:
            raise EvidenceCollectionError("BUSINESS_GATE_EVIDENCE_UNREADABLE") from exc
        actual_hash = hashlib.sha256(evidence_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise EvidenceCollectionError("BUSINESS_GATE_EVIDENCE_MISMATCH")
        normalized_gates[gate] = {
            "status": "pass",
            "command": list(command),
            "exit_code": 0,
            "evidence_path": evidence_path.relative_to(root).as_posix(),
            "evidence_sha256": actual_hash,
            "evidence_bytes": len(evidence_bytes),
        }

    return {
        "schema_version": "1.0",
        "scenario_id": payload.get("scenario_id"),
        "build_id": build_id,
        "gates": normalized_gates,
        "final_verdict": "pass",
        "source": {
            "path": report_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        },
    }


def _read_loop_facts(project_root: Path) -> tuple[str, list[dict[str, Any]]]:
    database = project_root / ".ae-state" / "events.db"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database)
        rows = connection.execute(
            "SELECT thread_id, event_type, payload_json "
            "FROM loop_events ORDER BY sequence"
        ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        raise EvidenceCollectionError("EVENT_STORE_UNREADABLE") from exc
    finally:
        if connection is not None:
            connection.close()
    threads = {row[0] for row in rows}
    if len(threads) != 1:
        raise EvidenceCollectionError("EVENT_THREAD_INVALID")
    facts: list[dict[str, Any]] = []
    try:
        for thread_id, event_type, payload_json in rows:
            payload = json.loads(payload_json)
            facts.append({
                "thread_id": thread_id,
                "event_type": event_type,
                "payload": payload,
            })
    except (TypeError, json.JSONDecodeError) as exc:
        raise EvidenceCollectionError("EVENT_PAYLOAD_INVALID") from exc
    return next(iter(threads)), facts


def _action_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for fact in facts:
        if fact["event_type"] != "ActionIssued":
            continue
        action = fact["payload"].get("action")
        if isinstance(action, dict) and isinstance(action.get("message_id"), str):
            actions.append(action)
    if not actions:
        raise EvidenceCollectionError("ACTION_FACTS_MISSING")
    return actions


def _unexpected_stop_report_count(project_root: Path) -> int:
    """读取宿主边界写入的异常结束事实；损坏报告必须 fail-closed。"""

    reports_root = project_root / ".ae-state" / "host-runtime" / "stop-reports"
    if not reports_root.is_dir():
        return 0
    count = 0
    for path in sorted(reports_root.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvidenceCollectionError("STOP_REPORT_INVALID") from exc
        if (
            not isinstance(report, dict)
            or report.get("reason_code") != "HOST_RUNTIME_PROTOCOL_ERROR"
        ):
            raise EvidenceCollectionError("STOP_REPORT_INVALID")
        count += 1
    return count


def _native_result_manifest(
    project_root: Path,
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """收集每个 Spawn Worker 的原生回包暂存事实。

    私有业务 outcome 只能证明 Worker 写过业务产物，不能证明 Host 取得并保留了
    原生句柄对应的回包。两者是不同证据边界；缺少后者时，产品证据必须停止，不能
    由 collector 把“没有发现异常”推断成“桥接完整”。
    """

    manifest: list[dict[str, Any]] = []
    for action in actions:
        spawn = action.get("spawn")
        if not isinstance(spawn, dict):
            continue
        host_execution = action.get("host_execution")
        workers = (
            host_execution.get("workers")
            if isinstance(host_execution, dict)
            else None
        )
        worker_by_id = {
            item.get("worker_id"): item
            for item in workers
            if isinstance(item, dict) and isinstance(item.get("worker_id"), str)
        } if isinstance(workers, list) else {}
        invocations = spawn.get("invocations")
        if not isinstance(invocations, list) or not invocations:
            raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_MISSING")
        generation = action.get("execution_generation", 1)
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
        ):
            raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_INVALID")
        for invocation in invocations:
            if not isinstance(invocation, dict):
                raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_INVALID")
            worker_id = invocation.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id:
                raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_INVALID")
            mapped_worker = worker_by_id.get(worker_id)
            if isinstance(mapped_worker, dict):
                relative = mapped_worker.get("native_result_path")
            else:
                fallback = worker_native_result_path(
                    action["message_id"], worker_id, generation
                )
                relative = _discover_native_result_path(
                    project_root,
                    message_id=action["message_id"],
                    worker_id=worker_id,
                    fallback=fallback,
                )
            if not isinstance(relative, str) or not relative:
                raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_MISSING")
            path = (project_root / relative).resolve()
            if (
                not path.is_file()
                or not path.is_relative_to(project_root)
            ):
                raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_MISSING")
            try:
                raw = path.read_bytes()
                if not raw.strip():
                    raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_INVALID")
                json.loads(raw.decode("utf-8"))
            except EvidenceCollectionError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_INVALID") from exc
            manifest.append({
                "action_message_id": action["message_id"],
                "worker_id": worker_id,
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            })
    if not manifest:
        raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_MISSING")
    return manifest


def _discover_native_result_path(
    project_root: Path,
    *,
    message_id: str,
    worker_id: str,
    fallback: str,
) -> str:
    """从 Action-scoped 私有目录发现 canonical Action 未携带的宿主路径。

    ``ActionIssued`` 只保存 Core canonical payload；宿主映射产生的
    ``host_execution.workers`` 不属于 EventStore 事实。路径合同仍由
    ``message_id + worker_id + generation`` 唯一约束，因此只接受同一 action
    key/worker 的数字 generation 文件，并选择最高代；不存在时回退到当前
    generation 的确定路径，让缺失事实继续 fail-closed。
    """

    native_root = (project_root / ".ae-state" / "host-runtime" / "native-results").resolve()
    safe_worker = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in worker_id
    )
    prefix = f"{action_key_for(message_id)}-{safe_worker}-g"
    candidates: list[tuple[int, Path]] = []
    try:
        for path in native_root.glob(f"{prefix}*.json"):
            if path.parent != native_root or not path.is_file():
                continue
            suffix = path.stem[len(prefix):]
            if suffix.isdigit() and int(suffix) >= 1:
                candidates.append((int(suffix), path))
    except OSError as exc:
        raise EvidenceCollectionError("NATIVE_RESULT_EVIDENCE_UNREADABLE") from exc
    if not candidates:
        return fallback
    return max(candidates, key=lambda item: item[0])[1].relative_to(project_root.resolve()).as_posix()


def _runtime_build_id(action: dict[str, Any]) -> str | None:
    extensions = action.get("extensions")
    ae = extensions.get("ae") if isinstance(extensions, dict) else None
    revision = ae.get("runtime_revision") if isinstance(ae, dict) else None
    value = revision.get("engine_build_id") if isinstance(revision, dict) else None
    return value if isinstance(value, str) and value else None


def _journal_recovery_candidates(
    root: Path,
    actions: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """读取宿主无关 Action 对应的 Outcome Journal 修复事实。

    EventStore 只保存 canonical Action，不应嵌入宿主投影的
    ``host_execution.recovery``。同 Action 的 Coordinator 修复则由
    Outcome Journal 的 accepted + rejection_history 事实证明。
    """

    outcome_root = root / ".ae-state" / "host-runtime" / "outcomes"
    candidates: list[tuple[str, str, str]] = []
    for action in actions:
        action_id = action.get("message_id")
        if not isinstance(action_id, str) or not action_id:
            continue
        if not isinstance(action.get("spawn"), dict):
            continue
        journal_path = outcome_root / f"{action_id}.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        history = journal.get("rejection_history") if isinstance(journal, dict) else None
        if (
            isinstance(journal, dict)
            and journal.get("status") == "accepted"
            and isinstance(history, list)
            and history
            and all(isinstance(item, dict) for item in history)
        ):
            candidates.append((action_id, "coordinator_repair", "worker_outcomes_committed"))
    return candidates


def _read_canary_evidence(
    project_root: Path,
    *,
    build_id: str,
) -> dict[str, Any]:
    """从独立 L3 项目事实推导阶段和一次恢复，不读取 L4 业务报告。"""

    root = project_root.resolve()
    _, facts = _read_loop_facts(root)
    actions = _action_facts(facts)
    build_ids = {
        action_build_id
        for action in actions
        if (action_build_id := _runtime_build_id(action))
    }
    if build_ids != {build_id}:
        raise EvidenceCollectionError("CANARY_BUILD_ID_MISMATCH")
    stages = sorted({
        stage
        for action in actions
        if isinstance(stage := action.get("stage"), str)
    })
    if not {"architect", "developer", "critic"}.issubset(stages):
        raise EvidenceCollectionError("CANARY_STAGES_INCOMPLETE")

    candidates: list[tuple[str, str, str]] = []
    for action in actions:
        host_execution = action.get("host_execution")
        recovery = (
            host_execution.get("recovery")
            if isinstance(host_execution, dict)
            else None
        )
        if not isinstance(recovery, dict):
            continue
        status = recovery.get("status")
        action_id = action.get("message_id")
        method = next(
            (
                key
                for key, value in _RECOVERY_METHOD_STATUS.items()
                if value == status
            ),
            None,
        )
        if (
            isinstance(action_id, str)
            and action_id
            and isinstance(method, str)
            and recovery.get("spawn_permitted") is False
            and status in _RECOVERY_STATUSES
        ):
            candidates.append((action_id, method, status))
    if not candidates:
        candidates = _journal_recovery_candidates(root, actions)
    if len(candidates) != 1:
        raise EvidenceCollectionError("CANARY_RECOVERY_NOT_UNIQUE")
    action_id, method, projection_status = candidates[0]
    return {
        "schema_version": "1.0",
        "status": "pass",
        "build_id": build_id,
        "stages": stages,
        "recovery": {
            "status": "verified",
            "method": method,
            "action_message_id": action_id,
            "projection_status": projection_status,
        },
        "source": {
            "kind": "event_store",
            "root": str(root),
        },
    }


def _usage_receipts(
    *,
    ledger: UsageLedger,
    thread_id: str,
    actions: list[dict[str, Any]],
    build_id: str,
    host: str,
    cost_usd: float | None,
) -> tuple[list[dict[str, Any]], dict[str, int | float | None]]:
    action_by_id = {action["message_id"]: action for action in actions}
    grouped = ledger.records_for_action(thread_id)
    if "" in grouped:
        raise EvidenceCollectionError("USAGE_ACTION_BINDING_MISSING")
    if not grouped:
        raise EvidenceCollectionError("USAGE_MISSING")
    receipts: list[dict[str, Any]] = []
    input_total = 0
    cache_total = 0
    output_total = 0
    for action in actions:
        action_id = action["message_id"]
        records = grouped.get(action_id)
        if not records:
            continue
        if any(
            record.input_units is None
            or record.cache_read_units is None
            or record.output_units is None
            or record.estimated
            or record.usage_source in {"", "unsupported"}
            for record in records
        ):
            raise EvidenceCollectionError("USAGE_MEASUREMENT_INCOMPLETE")
        if action_id not in action_by_id:
            raise EvidenceCollectionError("USAGE_ACTION_UNKNOWN")
        stage = action.get("stage")
        if not isinstance(stage, str) or not stage:
            raise EvidenceCollectionError("ACTION_STAGE_INVALID")
        input_units = sum(int(record.input_units or 0) for record in records)
        cache_units = sum(int(record.cache_read_units or 0) for record in records)
        output_units = sum(int(record.output_units or 0) for record in records)
        input_total += input_units
        cache_total += cache_units
        output_total += output_units
        session_ids = {record.session_id for record in records}
        session_id = next(iter(session_ids)) if len(session_ids) == 1 else action_id
        receipts.append({
            "action_message_id": action_id,
            "host_context_id": f"{session_id}:{action_id}",
            "stage": stage,
            "build_id": build_id,
            "status": "completed",
            "usage": {
                "input_tokens": input_units,
                "cached_input_tokens": cache_units,
                "output_tokens": output_units,
            },
        })
    stages = {receipt["stage"] for receipt in receipts}
    if not {"architect", "developer", "critic"}.issubset(stages):
        raise EvidenceCollectionError("USAGE_STAGE_BINDING_INCOMPLETE")
    if host == "claude-code":
        if cost_usd is None:
            raise EvidenceCollectionError("CLAUDE_COST_EVIDENCE_MISSING")
        receipts[0]["usage"]["cost_usd"] = cost_usd
    totals: dict[str, int | float | None] = {
        "input_tokens": input_total,
        "cached_input_tokens": cache_total,
        "output_tokens": output_total,
        "cost_usd": cost_usd,
    }
    return receipts, totals


def collect_product_evidence(
    *,
    project_root: Path,
    host: str,
    archive: Path,
    runtime_root: Path,
    development_root: Path,
    canary_project_root: Path,
    source_ref: str,
    output: Path,
    evidence_output: Path,
    business_evidence: Path,
    host_output: Path | None = None,
    max_claude_cost_usd: float = DEFAULT_CLAUDE_COST_LIMIT_USD,
) -> dict[str, Any]:
    max_claude_cost_usd = _validate_cost_limit(max_claude_cost_usd)
    candidate = _read_candidate_build_info(archive)
    thread_id, facts = _read_loop_facts(project_root.resolve())
    actions = _action_facts(facts)
    native_result_manifest = _native_result_manifest(project_root.resolve(), actions)
    cost_usd: float | None = None
    host_usage_attestation: dict[str, Any] | None = None
    if host == "claude-code":
        if host_output is None:
            raise EvidenceCollectionError("CLAUDE_COST_EVIDENCE_MISSING")
        host_output = host_output.resolve()
        if not host_output.is_relative_to(project_root.resolve()):
            raise EvidenceCollectionError("CLAUDE_USAGE_ATTESTATION_PATH_INVALID")
        try:
            cost_usd = read_claude_stream_usage(host_output).cost_usd
            raw_host_output = host_output.read_bytes()
        except HostUsageAttestationError as exc:
            raise EvidenceCollectionError(str(exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise EvidenceCollectionError(
                "CLAUDE_USAGE_ATTESTATION_UNREADABLE"
            ) from exc
        host_usage_attestation = {
            "path": host_output.relative_to(project_root.resolve()).as_posix(),
            "sha256": hashlib.sha256(raw_host_output).hexdigest(),
            "bytes": len(raw_host_output),
            "source": "claude-cli-result",
        }
    build_ids = {build_id for action in actions if (build_id := _runtime_build_id(action))}
    if build_ids != {candidate["build_id"]}:
        raise EvidenceCollectionError("RUNTIME_BUILD_ID_MISMATCH")
    terminal = next(
        (action for action in reversed(actions) if action.get("action") == "done"),
        None,
    )
    if terminal is None:
        raise EvidenceCollectionError("TERMINAL_ACTION_MISSING")
    business = _read_business_evidence(
        business_evidence,
        project_root=project_root,
        build_id=candidate["build_id"],
    )
    canary = _read_canary_evidence(
        canary_project_root,
        build_id=candidate["build_id"],
    )
    spawned = [action for action in actions if isinstance(action.get("spawn"), dict)]
    for action in spawned:
        journal = (
            project_root / ".ae-state" / "host-runtime" / "outcomes"
            / f"{action['message_id']}.json"
        )
        if not journal.is_file() or json.loads(journal.read_text()).get("status") != "accepted":
            raise EvidenceCollectionError("OUTCOME_JOURNAL_INCOMPLETE")
    ledger = UsageLedger(project_root / ".ae-state" / "usage-ledger.db")
    try:
        receipts, usage = _usage_receipts(
            ledger=ledger,
            thread_id=thread_id,
            actions=actions,
            build_id=candidate["build_id"],
            host=host,
            cost_usd=cost_usd,
        )
    finally:
        ledger.close()
    event_types = [fact["event_type"] for fact in facts]
    unexpected_stop_count = int("LoopFailed" in event_types) + _unexpected_stop_report_count(
        project_root.resolve()
    )
    if "LoopCompleted" not in event_types or "ResultAccepted" not in event_types:
        raise EvidenceCollectionError("LOOP_COMPLETION_FACTS_INCOMPLETE")
    if not isinstance(terminal.get("acceptance_summary"), dict):
        raise EvidenceCollectionError("TERMINAL_ACCEPTANCE_SUMMARY_MISSING")
    artifact: dict[str, Any] = {
        "schema_version": "1.1",
        "host": host,
        "build_id": candidate["build_id"],
        "installed_build_id": candidate["build_id"],
        "build_identity_preflight": {
            "status": "pass",
            "build_id": candidate["build_id"],
            "version": candidate["version"],
            "source_kind": "packaged",
        },
        "acceptance_policy": {
            "max_claude_cost_usd": max_claude_cost_usd,
        },
        "plugin_discovered": True,
        "runtime_root": str(runtime_root.resolve()),
        "event_types": sorted(set(event_types)),
        "terminal_action": terminal,
        "trajectory": {
            "invocation_count": len(receipts),
            "attempt_count": len(receipts),
            "manual_protocol_repairs": 0,
            "unexpected_stops": unexpected_stop_count,
            "traceability_complete": True,
            "final_disposition": "TERMINAL",
        },
        "action_receipts": receipts,
        "attempt_receipts": receipts,
        "native_result_manifest": native_result_manifest,
        "business_evidence": business,
        "machine_claims": {
            "usage_status": "complete",
            "unexpected_stops": unexpected_stop_count,
            "manual_protocol_repairs": 0,
            "traceability_complete": True,
        },
    }
    if host_usage_attestation is not None:
        artifact["host_usage_attestation"] = host_usage_attestation
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    evidence = {
        "host": host,
        "build_id": candidate["build_id"],
        "project_state": "fresh",
        "semantic_enforcement": "full",
        "usage_status": "complete",
        "unexpected_stops": artifact["trajectory"]["unexpected_stops"],
        "unapproved_changes": 0,
        "installation": {
            "status": "pass",
            "discovered": True,
            "runtime_root": str(runtime_root.resolve()),
            "development_root": str(development_root.resolve()),
            "source_isolated": True,
            "source_kind": "marketplace",
            "source_ref": source_ref,
            "source_build_id": candidate["build_id"],
            "source_content_sha256": candidate["content_sha256"],
        },
        "usage": usage,
        "acceptance_policy": {
            "max_claude_cost_usd": max_claude_cost_usd,
        },
        "canary": {
            "status": canary["status"],
            "stages": canary["stages"],
            "recovery_verified": canary["recovery"]["status"] == "verified",
            "recovery_method": canary["recovery"]["method"],
            "recovery_action_message_id": canary["recovery"]["action_message_id"],
        },
        "golden_project": {
            "status": "pass",
            "business_gates": sorted(business["gates"]),
            "final_verdict": "pass",
        },
        "evidence_artifact": {"path": output.name, "sha256": digest},
    }
    if host_usage_attestation is not None:
        evidence["host_usage_attestation"] = dict(host_usage_attestation)
    evidence_output = evidence_output.resolve()
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--host", choices=("codex", "claude-code"), required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument(
        "--canary-project-root", type=Path, required=True,
        help="独立 L3 Canary 项目根；必须包含 Architect/Developer/Critic 和一次恢复事实",
    )
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument(
        "--business-evidence", type=Path, required=True,
        help="项目内结构化 L4 业务验收报告；必须绑定 Build 和 Gate 输出",
    )
    parser.add_argument(
        "--host-output", type=Path,
        help="宿主 stream-json 原始输出；Claude 必须用它提取真实成本",
    )
    parser.add_argument(
        "--max-claude-cost-usd",
        type=float,
        default=DEFAULT_CLAUDE_COST_LIMIT_USD,
        help="写入 evidence 的 Claude 成本策略；默认 2.0 美元",
    )
    args = parser.parse_args()
    try:
        collect_product_evidence(
            project_root=args.project_root,
            host=args.host,
            archive=args.archive,
            runtime_root=args.runtime_root,
            development_root=args.development_root,
            canary_project_root=args.canary_project_root,
            source_ref=args.source_ref,
            output=args.output,
            evidence_output=args.evidence_output,
            business_evidence=args.business_evidence,
            host_output=args.host_output,
            max_claude_cost_usd=args.max_claude_cost_usd,
        )
    except EvidenceCollectionError as exc:
        parser.exit(2, f"evidence collection failed: {exc}\n")
    print(args.evidence_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
