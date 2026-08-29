"""把宿主真实 Worker outcome 原子终结为 Core 可验证证据。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.config.runtime_config import get_default_config
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_attestation import (
    WorkerAttestationError,
    validate_attestations,
)
from auto_engineering.loop.actions import validate_result_format
from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    compact_worker_receipt,
    validate_worker_receipt,
)


class HostEvidenceValidationError(ValueError):
    """一次报告全部证据问题，避免宿主逐轮修补 JSON。"""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(dict.fromkeys(violations))
        super().__init__("HOST_EVIDENCE_INVALID: " + ",".join(self.violations))


@dataclass(frozen=True, slots=True)
class NativeWorkerOutcome:
    worker_id: str
    native_worker_handle: str
    status: str
    payload: dict[str, Any]
    summary: str
    actual_model: str
    isolation_evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class HostExecutionAssembler:
    """以 outcome journal 为恢复点，幂等完成一整个 spawn Action。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def restore_committed_result_to_file(
        self,
        *,
        action: Mapping[str, Any],
        result_path: Path,
        outcomes_path: Path | None = None,
    ) -> dict[str, Any] | None:
        """从 Core-owned journal 恢复与 active Action 绑定的 Result。

        无 committed journal 表示应执行正常 Worker 路径；已有 journal 但
        身份不一致则 fail-closed，不得回退为重新 spawn。
        """

        message_id = action.get("message_id")
        thread_id = action.get("thread_id")
        stage = action.get("stage")
        if (
            not isinstance(message_id, str)
            or not message_id
            or not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(stage, str)
            or not stage
        ):
            raise HostEvidenceValidationError(("ACTION_IDENTITY_INVALID",))
        journal_path = (
            self.project_root
            / ".ae-state/host-runtime/outcomes"
            / f"{message_id}.json"
        )
        journal = self._read_json(journal_path)
        if journal is None:
            return None
        if journal.get("status") == "rejected":
            # Core 已拒绝候选 Result，但 Worker 事实仍是同一 Action 的权威事实；
            # 修复上下文只能拿到这份原文，绝不能因 rejected 状态重新 spawn。
            if outcomes_path is None:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_PATH_MISSING",)
                )
            outcomes = self._authoritative_outcomes(
                journal=journal,
                action_message_id=message_id,
                required=True,
            )
            if outcomes is None:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_MISSING",)
                )
            self._write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") == "assembly_rejected":
            # 语义组装拒绝通常保留已完成 Worker；有事实时恢复并复用，
            # 没有事实则保持旧兼容路径，允许首次 Worker 执行。
            outcomes = self._authoritative_outcomes(
                journal=journal,
                action_message_id=message_id,
                required=False,
            )
            if outcomes is not None and outcomes_path is not None:
                self._write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") == "prepared" and not isinstance(
            journal.get("result"), dict
        ):
            outcomes = journal.get("outcomes")
            if (
                journal.get("schema_version") != "1.0"
                or journal.get("action_message_id") != message_id
                or not isinstance(outcomes, list)
            ):
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_PREPARED_INVALID",)
                )
            if outcomes_path is not None:
                # prepared journal 已在 Worker 完成后原子落盘，是 outcome
                # 的权威恢复点；宿主工作副本只能由它重建，不能反向改写事实。
                self._write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") not in {"prepared", "accepted", "committed"}:
            return None
        result = journal.get("result")
        # 早期 T517 build 曾把失败尝试误写为 committed；失败不是成功证据，
        # 恢复时必须允许同一 active Action 重新执行 Worker。
        if isinstance(result, dict) and result.get("spawned") is False:
            return None
        if (
            journal.get("schema_version") not in {"1.0", "1.1"}
            or journal.get("action_message_id") != message_id
            or not isinstance(result, dict)
            or result.get("message_type") != "result"
            or result.get("causation_id") != message_id
            or result.get("thread_id") != thread_id
            or result.get("stage") != stage
            or result.get("tick") != int(action.get("tick", 0))
        ):
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_RESULT_IDENTITY_MISMATCH",)
            )
        target = (
            result_path.resolve()
            if result_path.is_absolute()
            else (self.project_root / result_path).resolve()
        )
        if target != self.project_root and self.project_root not in target.parents:
            raise HostEvidenceValidationError(
                ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
            )
        _atomic_write_json(target, result)
        if outcomes_path is not None:
            outcomes = journal.get("outcomes", [])
            if not isinstance(outcomes, list):
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_INVALID",)
                )
            outcomes_target = (
                outcomes_path.resolve()
                if outcomes_path.is_absolute()
                else (self.project_root / outcomes_path).resolve()
            )
            if (
                outcomes_target != self.project_root
                and self.project_root not in outcomes_target.parents
            ):
                raise HostEvidenceValidationError(
                    ("OUTCOMES_OUTPUT_PATH_OUTSIDE_PROJECT",)
                )
            _atomic_write_json(outcomes_target, {"outcomes": outcomes})
        return dict(result)

    def _write_outcomes_file(
        self,
        outcomes_path: Path,
        outcomes: Sequence[Mapping[str, Any]],
    ) -> None:
        target = (
            outcomes_path.resolve()
            if outcomes_path.is_absolute()
            else (self.project_root / outcomes_path).resolve()
        )
        if target == self.project_root or self.project_root not in target.parents:
            raise HostEvidenceValidationError(
                ("OUTCOMES_OUTPUT_PATH_OUTSIDE_PROJECT",)
            )
        _atomic_write_json(target, {"outcomes": [dict(item) for item in outcomes]})

    @staticmethod
    def _authoritative_outcomes(
        *,
        journal: Mapping[str, Any],
        action_message_id: str,
        required: bool,
    ) -> list[dict[str, Any]] | None:
        raw = journal.get("outcomes")
        if journal.get("action_message_id") != action_message_id:
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_ACTION_IDENTITY_MISMATCH",)
            )
        if not isinstance(raw, list):
            if required:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_MISSING",)
                )
            return None
        if any(not isinstance(item, Mapping) for item in raw):
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_OUTCOMES_INVALID",)
            )
        expected = journal.get("outcomes_fingerprint")
        if isinstance(expected, str):
            actual = hashlib.sha256(
                _canonical_bytes({
                    "action_message_id": action_message_id,
                    "outcomes": raw,
                })
            ).hexdigest()
            if actual != expected:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_FINGERPRINT_MISMATCH",)
                )
        return [dict(item) for item in raw]

    def finalize(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        # Worker 失败是一次独立的宿主事实，不依赖 Coordinator 业务字段。
        # 必须先终结失败尝试，再校验 Architect/Developer 等成功 payload；
        # 否则超时时的空 payload 会被误判为可修复的业务 Result，既无法
        # 生成 result.json，也会错误进入“复用 Worker、禁止重启”的路径。
        if (
            isinstance(action.get("spawn"), Mapping)
            and any(outcome.status != "completed" for outcome in outcomes)
        ):
            return self._finalize_worker_failure(
                action=action,
                outcomes=outcomes,
            )
        coordinator_payload = self._normalize_echoed_identity(
            action=action,
            coordinator_payload=coordinator_payload,
        )
        coordinator_payload = self._normalize_business_payload(
            action=action,
            coordinator_payload=coordinator_payload,
        )
        if not isinstance(action.get("spawn"), Mapping):
            return self._finalize_inline(
                action=action,
                outcomes=outcomes,
                coordinator_payload=coordinator_payload,
            )
        violations, context = self._preflight(
            action=action,
            outcomes=outcomes,
            coordinator_payload=coordinator_payload,
        )
        if violations:
            raise HostEvidenceValidationError(violations)

        plan: SpawnPlan = context["plan"]
        message_id = context["message_id"]
        journal_path = (
            self.project_root
            / ".ae-state/host-runtime/outcomes"
            / f"{message_id}.json"
        )
        existing = self._read_json(journal_path)
        outcome_by_worker = {item.worker_id: item for item in outcomes}
        if existing is not None and existing.get("status") in {
            "rejected",
            "assembly_rejected",
        }:
            authoritative = self._authoritative_outcomes(
                journal=existing,
                action_message_id=message_id,
                required=existing.get("status") == "rejected",
            )
            if authoritative is not None:
                try:
                    # Result 修复只允许改变 Coordinator 语义；Worker outcome
                    # 由首次事务固定，忽略后续宿主 context 传来的替代事实。
                    outcome_by_worker = {
                        item.worker_id: item
                        for item in (
                            NativeWorkerOutcome(**raw)
                            for raw in authoritative
                        )
                    }
                except (TypeError, ValueError) as exc:
                    raise HostEvidenceValidationError((
                        "OUTCOME_JOURNAL_OUTCOMES_INVALID",
                    )) from exc
        normalized: dict[str, NativeWorkerOutcome] = {}
        for worker_id, outcome in outcome_by_worker.items():
            evidence = outcome.isolation_evidence
            canonical_evidence: str | None = None
            if evidence in (
                {"fork_context": False},
                {"fork_context": False, "fork_turns": "none"},
            ):
                canonical_evidence = "fork_context=false"
            elif evidence == {"fork_turns": "none"}:
                canonical_evidence = "fork_turns=none"
            normalized[worker_id] = (
                replace(outcome, isolation_evidence=canonical_evidence)
                if canonical_evidence is not None
                else outcome
            )
        outcome_by_worker = normalized
        config = get_default_config()
        receipts: dict[str, dict[str, Any]] = {}
        for invocation in plan.invocations:
            outcome = outcome_by_worker[invocation.worker_id]
            try:
                receipts[invocation.worker_id] = compact_worker_receipt(
                    store=ArtifactStore(
                        self.project_root / ".ae-state" / "artifacts"
                    ),
                    stage=context["stage"],
                    worker=invocation.worker_id,
                    payload=outcome.payload,
                    summary=outcome.summary,
                    inline_limit=config.max_worker_receipt_bytes,
                    summary_limit=config.max_receipt_summary_bytes,
                    requested_effort=invocation.requested_effort,
                    actual_model=outcome.actual_model,
                    native_worker_handle=outcome.native_worker_handle,
                )
            except ArtifactError as exc:
                raise HostEvidenceValidationError((
                    f"WORKER_RECEIPT_TOO_LARGE:{invocation.worker_id}",
                )) from exc

        worker_templates: dict[str, Mapping[str, Any]] = context["worker_templates"]

        def validated_attestations(
            candidates: Mapping[str, NativeWorkerOutcome],
        ) -> list[dict[str, Any]]:
            built: list[dict[str, Any]] = []
            for invocation in plan.invocations:
                outcome = candidates[invocation.worker_id]
                template = worker_templates[invocation.worker_id]
                raw_attestation = template.get("attestation")
                assert isinstance(raw_attestation, Mapping)
                attestation = dict(raw_attestation)
                attestation["status"] = "completed"
                attestation["actual_model"] = outcome.actual_model
                if outcome.isolation_evidence is not None:
                    attestation["isolation_evidence"] = outcome.isolation_evidence
                built.append(attestation)
            validate_attestations(
                action_message_id=context["message_id"],
                invocations=plan.invocations,
                attestations=built,
            )
            return built

        try:
            attestations = validated_attestations(outcome_by_worker)
        except WorkerAttestationError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc

        serialized_outcomes = [
            outcome_by_worker[item.worker_id].to_dict() for item in plan.invocations
        ]
        outcomes_fingerprint = hashlib.sha256(
            _canonical_bytes({
                "action_message_id": message_id,
                "outcomes": serialized_outcomes,
            })
        ).hexdigest()
        fingerprint_payload = {
            "action_message_id": message_id,
            "outcomes": serialized_outcomes,
            "coordinator_payload": dict(coordinator_payload),
        }
        fingerprint = hashlib.sha256(_canonical_bytes(fingerprint_payload)).hexdigest()
        if existing is not None and existing.get("status") == "prepared":
            rejection_reason: str | None = None
            try:
                raw_existing_outcomes = existing.get("outcomes")
                if not isinstance(raw_existing_outcomes, list):
                    raise ValueError("PREPARED_OUTCOME_SCHEMA_INVALID")
                parsed_existing = [
                    NativeWorkerOutcome(**dict(item))
                    for item in raw_existing_outcomes
                    if isinstance(item, Mapping)
                ]
                if len(parsed_existing) != len(raw_existing_outcomes):
                    raise ValueError("PREPARED_OUTCOME_SCHEMA_INVALID")
                validated_attestations({
                    item.worker_id: item for item in parsed_existing
                })
            except WorkerAttestationError as exc:
                rejection_reason = str(exc)
            except (KeyError, TypeError, ValueError):
                rejection_reason = "PREPARED_OUTCOME_SCHEMA_INVALID"
            if rejection_reason is not None:
                rejected_digest = hashlib.sha256(
                    _canonical_bytes(existing)
                ).hexdigest()[:16]
                rejected_path = (
                    self.project_root
                    / ".ae-state/host-runtime/rejected-outcomes"
                    / f"{message_id}-{rejected_digest}.json"
                )
                _atomic_write_json(rejected_path, {
                    "schema_version": "1.0",
                    "status": "rejected",
                    "reason": rejection_reason,
                    "journal": existing,
                })
                existing = None
        if existing is not None:
            existing_result = existing.get("result")
            retryable_failure = (
                existing.get("status") == "worker_failed"
                or (
                    isinstance(existing_result, dict)
                    and existing_result.get("spawned") is False
                )
            )
            if retryable_failure:
                existing = None
            else:
                existing_outcomes_fingerprint = existing.get("outcomes_fingerprint")
                if not isinstance(existing_outcomes_fingerprint, str):
                    existing_outcomes_fingerprint = hashlib.sha256(
                        _canonical_bytes({
                            "action_message_id": message_id,
                            "outcomes": existing.get("outcomes", []),
                        })
                    ).hexdigest()
                if existing_outcomes_fingerprint != outcomes_fingerprint:
                    raise HostEvidenceValidationError(("OUTCOME_JOURNAL_CONFLICT",))
                committed_result = existing.get("result")
                if (
                    existing.get("fingerprint") == fingerprint
                    and existing.get("status") in {"accepted", "committed"}
                    and isinstance(committed_result, dict)
                ):
                    return dict(committed_result)

        completed_at = (
            existing.get("completed_at")
            if isinstance(existing, dict)
            else None
        )
        if not isinstance(completed_at, str):
            completed_at = datetime.now(UTC).isoformat()
        if existing is None or existing.get("status") != "rejected":
            _atomic_write_json(journal_path, {
                "schema_version": "1.0",
                "status": "prepared",
                "fingerprint": fingerprint,
                "outcomes_fingerprint": outcomes_fingerprint,
                "action_message_id": message_id,
                "completed_at": completed_at,
                "outcomes": serialized_outcomes,
            })

        for invocation in plan.invocations:
            receipt = receipts[invocation.worker_id]
            _atomic_write_json(self.project_root / invocation.receipt_path, receipt)
        challenge: dict[str, Any] = context["challenge"]
        total_proof = {
            **challenge,
            "status": "completed",
            "completed_at": completed_at,
            "workers": [item.worker_id for item in plan.invocations],
            "worker_receipts": [item.receipt_path for item in plan.invocations],
        }
        total_path = (
            self.project_root
            / ".ae-state/spawn-proofs"
            / f"{context['proof_token']}.json"
        )
        _atomic_write_json(total_path, total_proof)

        result_identity = hashlib.sha256(
            _canonical_bytes({
                "fingerprint": fingerprint,
                "action_message_id": message_id,
            })
        ).hexdigest()
        result = {
            "schema_version": str(action.get("schema_version") or "1.1"),
            "message_type": "result",
            "message_id": str(uuid5(NAMESPACE_URL, result_identity)),
            "causation_id": message_id,
            "thread_id": context["thread_id"],
            "tick": int(action.get("tick", 0)),
            "stage": context["stage"],
            "correlation_id": str(
                action.get("correlation_id") or context["thread_id"]
            ),
            "extensions": {},
            **dict(coordinator_payload),
            "spawned": True,
            "spawn_proof_token": context["proof_token"],
            "worker_attestations": attestations,
        }
        OutcomeJournal(self.project_root).prepare(
            message_id,
            result,
            fingerprint=fingerprint,
            extra={
                "outcomes_fingerprint": outcomes_fingerprint,
                "completed_at": completed_at,
                "outcomes": serialized_outcomes,
            },
        )
        return result

    @staticmethod
    def _normalize_echoed_identity(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """只归一化身份完全一致的已知宿主包装；身份仍由 Core 写入。"""
        normalized = dict(coordinator_payload)
        wrapper_keys = {"action", "stage", "tick", "thread_id", "status", "result"}
        wrapped_result = normalized.get("result")
        if (
            isinstance(wrapped_result, Mapping)
            and set(normalized) == wrapper_keys
            and normalized.get("action") == action.get("action")
            and normalized.get("stage") == action.get("stage")
            and normalized.get("tick") == action.get("tick")
            and normalized.get("thread_id") == action.get("thread_id")
            and normalized.get("status") in {"ok", "success", "completed"}
        ):
            return dict(wrapped_result)
        if "stage" in normalized and normalized["stage"] == action.get("stage"):
            del normalized["stage"]
        return normalized

    @staticmethod
    def _normalize_business_payload(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """按 Core 下发合同恢复一次二次序列化，并在写证据前校验。"""

        contract = action.get("result_contract")
        if contract is None:
            return dict(coordinator_payload)
        if not isinstance(contract, Mapping):
            raise HostEvidenceValidationError(("RESULT_CONTRACT_INVALID",))
        required = contract.get("required")
        properties = contract.get("properties")
        if (
            contract.get("schema_version") != "1.0"
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or not isinstance(properties, Mapping)
            or contract.get("additionalProperties") is not False
        ):
            raise HostEvidenceValidationError(("RESULT_CONTRACT_INVALID",))
        normalized = dict(coordinator_payload)
        violations: list[str] = [
            f"COORDINATOR_FIELD_UNEXPECTED:{field}"
            for field in sorted(str(item) for item in normalized)
            if field not in properties
        ]
        for field in required:
            if field not in normalized:
                violations.append(f"COORDINATOR_FIELD_REQUIRED:{field}")
        for field, value in tuple(normalized.items()):
            declaration = properties.get(field)
            if not isinstance(declaration, Mapping):
                continue
            raw_types = declaration.get("type")
            expected = (
                [raw_types]
                if isinstance(raw_types, str)
                else raw_types
                if isinstance(raw_types, list)
                else []
            )
            if (
                isinstance(value, str)
                and "string" not in expected
                and any(item in expected for item in ("array", "object"))
            ):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    decoded = value
                if decoded is not value:
                    value = decoded
                    normalized[field] = decoded
            if not HostExecutionAssembler._matches_json_type(value, expected):
                violations.append(
                    f"COORDINATOR_FIELD_TYPE_INVALID:{field}:"
                    f"{'|'.join(str(item) for item in expected)}"
                )
        if violations:
            raise HostEvidenceValidationError(violations)
        stage = action.get("stage")
        if isinstance(stage, str):
            semantic_errors = validate_result_format(
                {"stage": stage, **normalized},
                stage,
            )
            if semantic_errors:
                raise HostEvidenceValidationError(tuple(
                    f"COORDINATOR_RESULT_INVALID:{error}"
                    for error in semantic_errors
                ))
        return normalized

    @staticmethod
    def _matches_json_type(value: object, expected: Sequence[object]) -> bool:
        checks = {
            "string": lambda item: isinstance(item, str),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        return any(
            isinstance(kind, str)
            and kind in checks
            and checks[kind](value)
            for kind in expected
        )

    def _finalize_worker_failure(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
    ) -> dict[str, Any]:
        """把原生 Worker 失败事实终结为不可伪装成业务成功的 Result。"""

        violations: list[str] = []
        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        message_id = action.get("message_id")
        thread_id = action.get("thread_id")
        stage = action.get("stage")
        tick = action.get("tick", 0)
        if not isinstance(message_id, str) or not message_id:
            violations.append("ACTION_MESSAGE_ID_MISSING")
        if not isinstance(thread_id, str) or not thread_id:
            violations.append("THREAD_ID_MISSING")
        if not isinstance(stage, str) or not stage:
            violations.append("STAGE_MISSING")
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            violations.append("ACTION_TICK_INVALID")
        expected_workers = {item.worker_id for item in plan.invocations}
        outcome_workers = {item.worker_id for item in outcomes}
        if outcome_workers != expected_workers:
            violations.append("WORKER_SET_MISMATCH")
        allowed_statuses = {"errored", "failed", "cancelled", "timeout", "timed_out"}
        for outcome in outcomes:
            violations.append(f"WORKER_NOT_COMPLETED:{outcome.worker_id}")
            if outcome.status not in allowed_statuses:
                violations.append(f"WORKER_FAILURE_STATUS_INVALID:{outcome.worker_id}")
            if not outcome.native_worker_handle:
                violations.append(f"NATIVE_WORKER_HANDLE_MISSING:{outcome.worker_id}")
            if not outcome.actual_model:
                violations.append(f"ACTUAL_MODEL_MISSING:{outcome.worker_id}")
        # WORKER_NOT_COMPLETED 在失败事务中是已知事实而非拒绝理由；保留该
        # 诊断仅用于与其他证据违规一起一次性报告。
        if not any(
            item.status not in allowed_statuses
            or not item.native_worker_handle
            or not item.actual_model
            for item in outcomes
        ) and outcome_workers == expected_workers:
            violations = [
                item for item in violations
                if not item.startswith("WORKER_NOT_COMPLETED:")
            ]
        if violations:
            raise HostEvidenceValidationError(violations)

        serialized_outcomes = [item.to_dict() for item in outcomes]
        failure_text = " | ".join(
            item.summary.strip() for item in outcomes if item.summary.strip()
        )[:512]
        timeout_markers = ("TIMEOUT", "TIMED_OUT", "DEADLINE")
        is_timeout = any(
            item.status in {"timeout", "timed_out"}
            or any(marker in item.summary.upper() for marker in timeout_markers)
            for item in outcomes
        )
        error_code = "HOST_WORKER_TIMEOUT" if is_timeout else "HOST_WORKER_FAILED"
        fingerprint_payload = {
            "action_message_id": message_id,
            "outcomes": serialized_outcomes,
            "spawn_error_code": error_code,
        }
        fingerprint = hashlib.sha256(
            _canonical_bytes(fingerprint_payload)
        ).hexdigest()
        journal_path = (
            self.project_root
            / ".ae-state/host-runtime/outcomes"
            / f"{message_id}.json"
        )
        existing = self._read_json(journal_path)
        failure_attempt = 1
        if existing is not None:
            committed_result = existing.get("result")
            if (
                existing.get("fingerprint") == fingerprint
                and existing.get("status") in {"committed", "worker_failed"}
                and isinstance(committed_result, dict)
            ):
                return dict(committed_result)
            if not (
                existing.get("status") == "worker_failed"
                or (
                    isinstance(committed_result, dict)
                    and committed_result.get("spawned") is False
                )
            ):
                raise HostEvidenceValidationError(("OUTCOME_JOURNAL_CONFLICT",))
            previous_attempt = existing.get("failure_attempt")
            if not isinstance(previous_attempt, int) or isinstance(previous_attempt, bool):
                previous_attempt = 1
            failure_attempt = previous_attempt + 1

        result_identity = hashlib.sha256(
            _canonical_bytes({
                "fingerprint": fingerprint,
                "action_message_id": message_id,
            })
        ).hexdigest()
        result = {
            "schema_version": str(action.get("schema_version") or "1.1"),
            "message_type": "result",
            "message_id": str(uuid5(NAMESPACE_URL, result_identity)),
            "causation_id": message_id,
            "thread_id": thread_id,
            "tick": tick,
            "stage": stage,
            "correlation_id": str(action.get("correlation_id") or thread_id),
            "extensions": {},
            "spawned": False,
            "spawn_error_code": error_code,
            "spawn_error": failure_text or error_code,
            "spawn_retry_attempt": failure_attempt,
        }
        _atomic_write_json(journal_path, {
            "schema_version": "1.0",
            "status": "worker_failed",
            "fingerprint": fingerprint,
            "failure_attempt": failure_attempt,
            "action_message_id": message_id,
            "outcomes": serialized_outcomes,
            "result": result,
        })
        return result

    def finalize_to_file(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
        result_path: Path,
    ) -> dict[str, Any]:
        """完成 Result 并原子落盘，宿主无需复制 stdout。"""

        target = (
            result_path.resolve()
            if result_path.is_absolute()
            else (self.project_root / result_path).resolve()
        )
        if target != self.project_root and self.project_root not in target.parents:
            raise HostEvidenceValidationError(
                ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
            )
        result = self.finalize(
            action=action,
            outcomes=outcomes,
            coordinator_payload=coordinator_payload,
        )
        _atomic_write_json(target, result)
        return result

    def _finalize_inline(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """绑定非 spawn Action，生成宿主无需手工拼装的完整 Result。"""

        effective_payload = self._bind_core_auto_decision(
            action=action,
            coordinator_payload=coordinator_payload,
        )
        effective_payload = self._bind_core_stage_fields(
            action=action,
            coordinator_payload=effective_payload,
        )
        violations: list[str] = []
        if outcomes:
            violations.append("UNEXPECTED_WORKER_OUTCOMES")
        message_id = action.get("message_id")
        thread_id = action.get("thread_id")
        stage = action.get("stage")
        tick = action.get("tick")
        if not isinstance(message_id, str) or not message_id:
            violations.append("ACTION_MESSAGE_ID_MISSING")
        if not isinstance(thread_id, str) or not thread_id:
            violations.append("THREAD_ID_MISSING")
        if not isinstance(stage, str) or not stage:
            violations.append("STAGE_MISSING")
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            violations.append("ACTION_TICK_INVALID")
        protected = {
            "schema_version",
            "message_type",
            "message_id",
            "causation_id",
            "thread_id",
            "tick",
            "stage",
            "correlation_id",
            "extensions",
            "spawned",
            "spawn_proof_token",
            "worker_attestations",
        }
        if protected.intersection(effective_payload):
            violations.append("COORDINATOR_IDENTITY_OVERRIDE")
        if violations:
            raise HostEvidenceValidationError(violations)
        assert isinstance(message_id, str)

        fingerprint_payload = {
            "action_message_id": message_id,
            "coordinator_payload": effective_payload,
        }
        fingerprint = hashlib.sha256(
            _canonical_bytes(fingerprint_payload)
        ).hexdigest()
        journal_path = (
            self.project_root
            / ".ae-state/host-runtime/outcomes"
            / f"{message_id}.json"
        )
        existing = self._read_json(journal_path)
        if existing is not None:
            committed_result = existing.get("result")
            if (
                existing.get("fingerprint") == fingerprint
                and existing.get("status") in {"prepared", "accepted", "committed"}
                and isinstance(
                committed_result, dict
                )
            ):
                return dict(committed_result)

        result_identity = hashlib.sha256(
            _canonical_bytes({
                "fingerprint": fingerprint,
                "action_message_id": message_id,
            })
        ).hexdigest()
        result = {
            "schema_version": str(action.get("schema_version") or "1.1"),
            "message_type": "result",
            "message_id": str(uuid5(NAMESPACE_URL, result_identity)),
            "causation_id": message_id,
            "thread_id": thread_id,
            "tick": tick,
            "stage": stage,
            "correlation_id": str(
                action.get("correlation_id") or thread_id
            ),
            "extensions": {},
            **effective_payload,
        }
        OutcomeJournal(self.project_root).prepare(
            message_id,
            result,
            fingerprint=fingerprint,
            extra={"outcomes": []},
        )
        return result

    @staticmethod
    def _bind_core_auto_decision(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """把线程策略生成的机器字段重新绑定到 active Action。

        宿主仍负责提供 Fill 的具体内容，但不得遗漏或改写 Core 已经决定的
        gap、resolution、来源和授权策略。
        """

        payload = dict(coordinator_payload)
        auto_decision = action.get("auto_decision")
        if action.get("stage") != "gap_review" or not isinstance(
            auto_decision, Mapping
        ):
            return payload
        raw_decision = payload.get("decision")
        decision = dict(raw_decision) if isinstance(raw_decision, Mapping) else {}
        for key in ("gap_id", "resolution", "decision_source", "policy"):
            if key in auto_decision:
                decision[key] = auto_decision[key]
        payload["decision"] = decision
        return payload

    @staticmethod
    def _bind_core_stage_fields(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """由 active Action 绑定阶段机器事实，Agent 只提供推理语义。"""

        payload = dict(coordinator_payload)
        if action.get("stage") != "gap_scan":
            return payload
        raw_gaps = payload.get("gaps")
        if isinstance(raw_gaps, list):
            payload["gaps"] = [
                {
                    **dict(gap),
                    "impact": [gap["impact"]],
                }
                if isinstance(gap, Mapping)
                and isinstance(gap.get("impact"), str)
                and gap["impact"].strip()
                else gap
                for gap in raw_gaps
            ]
        context = action.get("context")
        context_mapping: Mapping[str, Any] = (
            context if isinstance(context, Mapping) else {}
        )
        sections = context_mapping.get("design_sections")
        findings = payload.pop("section_findings", None)
        if not isinstance(sections, list) or not sections:
            # 旧 Action 没有稳定工程模型；只读兼容其既有 payload。
            return dict(coordinator_payload)
        if not isinstance(findings, list):
            raise HostEvidenceValidationError(("SECTION_FINDINGS_REQUIRED",))

        expected: dict[str, Mapping[str, Any]] = {}
        expected_by_ref: dict[str, str] = {}
        violations: list[str] = []
        for section in sections:
            if not isinstance(section, Mapping):
                violations.append("CORE_DESIGN_SECTION_INVALID")
                continue
            section_id = section.get("section_id")
            if not isinstance(section_id, str) or not section_id:
                violations.append("CORE_DESIGN_SECTION_ID_MISSING")
                continue
            if section_id in expected:
                violations.append(f"CORE_DESIGN_SECTION_DUPLICATE:{section_id}")
            expected[section_id] = section
            section_ref = section.get("design_section")
            if not isinstance(section_ref, str) or not section_ref:
                violations.append("CORE_DESIGN_SECTION_REF_MISSING")
            elif section_ref in expected_by_ref:
                violations.append(
                    f"CORE_DESIGN_SECTION_REF_DUPLICATE:{section_ref}"
                )
            else:
                expected_by_ref[section_ref] = section_id

        received: dict[str, Mapping[str, Any]] = {}
        for index, finding in enumerate(findings):
            if not isinstance(finding, Mapping):
                violations.append(f"SECTION_FINDING_INVALID:{index}")
                continue
            raw_section_ref = finding.get("section_ref")
            raw_section_id = finding.get("section_id")
            section_id = (
                expected_by_ref.get(raw_section_ref)
                if isinstance(raw_section_ref, str)
                else raw_section_id
            )
            evidence = finding.get("evidence")
            identifier_valid = (
                isinstance(raw_section_ref, str) and bool(raw_section_ref)
            ) or (
                isinstance(raw_section_id, str) and bool(raw_section_id)
            )
            if (
                not identifier_valid
                or finding.get("verdict") not in {"clear", "gap"}
                or not isinstance(evidence, list)
                or not evidence
                or not all(
                    isinstance(item, str) and item.strip() for item in evidence
                )
            ):
                violations.append(f"SECTION_FINDING_INVALID:{index}")
                continue
            if section_id not in expected:
                unknown = raw_section_ref if raw_section_ref is not None else raw_section_id
                violations.append(f"SECTION_FINDING_UNKNOWN:{unknown}")
                continue
            if section_id in received:
                violations.append(f"SECTION_FINDING_DUPLICATE:{section_id}")
                continue
            received[section_id] = finding
        for section_id in sorted(set(expected) - set(received)):
            violations.append(f"SECTION_FINDING_MISSING:{section_id}")
        if violations:
            raise HostEvidenceValidationError(violations)

        coverage = [
            {
                "section_id": section_id,
                "design_section_ref": str(expected[section_id]["design_section"]),
                "verdict": str(received[section_id]["verdict"]),
                "evidence": list(received[section_id]["evidence"]),
            }
            for section_id in expected
        ]
        gaps = payload.get("gaps", [])
        payload.update({
            "scanned_sections": len(coverage),
            "has_blocking": any(
                isinstance(gap, Mapping) and gap.get("grade") == "architectural"
                for gap in gaps
            ),
            "design_doc_digest": str(
                context_mapping.get("design_doc_digest", "")
            ),
            "scan_coverage": coverage,
        })
        return payload

    def _preflight(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        violations: list[str] = []
        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            return [str(exc)], {}
        message_id = action.get("message_id")
        thread_id = action.get("thread_id")
        stage = action.get("stage")
        proof_token = action.get("spawn_proof_token")
        if not isinstance(message_id, str) or not message_id:
            violations.append("ACTION_MESSAGE_ID_MISSING")
        if not isinstance(thread_id, str) or not thread_id:
            violations.append("THREAD_ID_MISSING")
        if not isinstance(stage, str) or not stage:
            violations.append("STAGE_MISSING")
        if not isinstance(proof_token, str) or not proof_token:
            violations.append("SPAWN_PROOF_TOKEN_MISSING")

        host_execution = action.get("host_execution")
        raw_workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        requires_native_isolation_fact = (
            isinstance(host_execution, Mapping)
            and isinstance(host_execution.get("native_worker_tools"), Mapping)
        )
        worker_templates: dict[str, Mapping[str, Any]] = {}
        if not isinstance(raw_workers, list):
            violations.append("HOST_EXECUTION_TEMPLATE_MISSING")
        else:
            for item in raw_workers:
                worker_id = item.get("worker_id") if isinstance(item, Mapping) else None
                if not isinstance(worker_id, str) or not worker_id:
                    violations.append("HOST_WORKER_TEMPLATE_INVALID")
                    continue
                if worker_id in worker_templates:
                    violations.append("HOST_WORKER_TEMPLATE_DUPLICATE")
                worker_templates[worker_id] = item

        expected_workers = {item.worker_id for item in plan.invocations}
        outcome_workers = {item.worker_id for item in outcomes}
        if outcome_workers != expected_workers:
            violations.append("WORKER_SET_MISMATCH")
        if set(worker_templates) != expected_workers:
            violations.append("HOST_TEMPLATE_WORKER_SET_MISMATCH")
        for outcome in outcomes:
            if outcome.status != "completed":
                violations.append(f"WORKER_NOT_COMPLETED:{outcome.worker_id}")
            if not outcome.native_worker_handle:
                violations.append(
                    f"NATIVE_WORKER_HANDLE_MISSING:{outcome.worker_id}"
                )
            if not outcome.actual_model:
                violations.append(f"ACTUAL_MODEL_MISSING:{outcome.worker_id}")
            if requires_native_isolation_fact and not outcome.isolation_evidence:
                violations.append(
                    f"WORKER_ISOLATION_EVIDENCE_MISSING:{outcome.worker_id}"
                )

        protected = {
            "schema_version", "message_id", "causation_id", "thread_id", "stage",
            "spawned", "spawn_proof_token", "worker_attestations",
        }
        if protected.intersection(coordinator_payload):
            violations.append("COORDINATOR_IDENTITY_OVERRIDE")
        violations.extend(
            self._coordinator_payload_violations(action, coordinator_payload)
        )

        challenge: dict[str, Any] | None = None
        if isinstance(proof_token, str) and proof_token:
            challenge_path = (
                self.project_root
                / ".ae-state/spawn-challenges"
                / f"{proof_token}.json"
            )
            challenge = self._read_json(challenge_path)
            if challenge is None:
                violations.append("SPAWN_CHALLENGE_MISSING")
            elif (
                challenge.get("token") != proof_token
                or challenge.get("thread_id") != thread_id
                or challenge.get("action_message_id") != message_id
                or challenge.get("stage") != stage
            ):
                violations.append("SPAWN_CHALLENGE_MISMATCH")
        if challenge is None:
            challenge = {}

        for invocation in plan.invocations:
            template = worker_templates.get(invocation.worker_id)
            if template is None:
                continue
            if (
                template.get("receipt_path") != invocation.receipt_path
                or template.get("prompt_ref") != invocation.prompt_ref
            ):
                violations.append(
                    f"HOST_WORKER_TEMPLATE_MISMATCH:{invocation.worker_id}"
                )
            raw_attestation = template.get("attestation")
            if not isinstance(raw_attestation, dict):
                violations.append(
                    f"ATTESTATION_TEMPLATE_MISSING:{invocation.worker_id}"
                )
                continue
            completed = dict(raw_attestation)
            completed["status"] = "completed"
            completed.setdefault("actual_model", "unknown")
            try:
                validate_attestations(
                    action_message_id=str(message_id or ""),
                    invocations=(invocation,),
                    attestations=[completed],
                )
            except WorkerAttestationError as exc:
                violations.append(
                    f"ATTESTATION_TEMPLATE_INVALID:{invocation.worker_id}:{exc}"
                )
        return violations, {
            "plan": plan,
            "message_id": message_id,
            "thread_id": thread_id,
            "stage": stage,
            "proof_token": proof_token,
            "worker_templates": worker_templates,
            "challenge": challenge,
        }

    @staticmethod
    def _coordinator_payload_violations(
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> list[str]:
        """在任何 evidence/journal 写入前拒绝跨 Action 陈旧业务字段。"""
        expected = action.get("expected_format")
        if not isinstance(expected, Mapping):
            return []
        allowed = {str(key) for key in expected}
        return [
            f"COORDINATOR_FIELD_UNEXPECTED:{key}"
            for key in sorted(str(key) for key in coordinator_payload)
            if key not in allowed
        ]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise HostEvidenceValidationError(("HOST_EVIDENCE_FILE_CORRUPT",)) from exc
        if not isinstance(raw, dict):
            raise HostEvidenceValidationError(("HOST_EVIDENCE_FILE_INVALID",))
        return raw


def collect_host_evidence_violations(
    *,
    project_root: Path,
    action: Mapping[str, Any],
    result: Mapping[str, Any],
    receipt_limit: int,
    summary_limit: int,
) -> tuple[str, ...]:
    """对严格 Action 一次收集全部完成证据问题，不做任何写入。"""

    violations: list[str] = []
    try:
        plan = SpawnPlan.from_action(action)
    except SpawnContractError as exc:
        return (str(exc),)
    root = project_root.resolve()
    token = action.get("spawn_proof_token")
    if not isinstance(token, str) or result.get("spawn_proof_token") != token:
        violations.append("SPAWN_PROOF_TOKEN_MISMATCH")
    else:
        proof_path = root / ".ae-state/spawn-proofs" / f"{token}.json"
        challenge_path = root / ".ae-state/spawn-challenges" / f"{token}.json"
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
            if (
                not isinstance(proof, dict)
                or not isinstance(challenge, dict)
                or proof.get("status") != "completed"
                or proof.get("token") != token
                or challenge.get("token") != token
                or challenge.get("thread_id") != action.get("thread_id")
                or challenge.get("action_message_id") != action.get("message_id")
                or challenge.get("stage") != action.get("stage")
            ):
                violations.append("SPAWN_PROOF_INCOMPLETE")
        except (OSError, json.JSONDecodeError):
            violations.append("SPAWN_PROOF_INCOMPLETE")

    raw_attestations = result.get("worker_attestations")
    if not isinstance(raw_attestations, list):
        violations.append("WORKER_ATTESTATIONS_MISSING")
    else:
        try:
            validate_attestations(
                action_message_id=str(action.get("message_id") or ""),
                invocations=plan.invocations,
                attestations=raw_attestations,
            )
        except WorkerAttestationError as exc:
            violations.append(f"WORKER_ATTESTATIONS_INVALID:{exc}")

    stage = str(action.get("stage") or "")
    store = ArtifactStore(root / ".ae-state/artifacts")
    for invocation in plan.invocations:
        try:
            receipt = json.loads(
                (root / invocation.receipt_path).read_text(encoding="utf-8")
            )
            if not isinstance(receipt, dict):
                raise ArtifactError("worker receipt 必须为 object")
            validate_worker_receipt(
                receipt,
                expected_stage=stage,
                store=store,
                receipt_limit=receipt_limit,
                summary_limit=summary_limit,
                expected_effort=invocation.requested_effort,
            )
            if receipt.get("worker") != invocation.worker_id:
                raise ArtifactError("worker receipt worker 与 Action 不一致")
            handle = receipt.get("native_worker_handle")
            if not isinstance(handle, str) or not handle:
                raise ArtifactError("worker receipt 缺少 native_worker_handle")
        except (OSError, json.JSONDecodeError, ArtifactError):
            violations.append(f"WORKER_RECEIPT_MISSING:{invocation.worker_id}")
    return tuple(dict.fromkeys(violations))


__all__ = [
    "HostEvidenceValidationError",
    "HostExecutionAssembler",
    "NativeWorkerOutcome",
    "collect_host_evidence_violations",
]
