"""Host Execution Assembler 的 Result 组装阶段。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.config.runtime_config import get_default_config
from auto_engineering.host.architect_result_coverage import (
    architect_result_coverage_violations,
)
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.host.outcome_recovery import OutcomeRecoveryService
from auto_engineering.host.outcome_repair import (
    assembly_rejection_can_extend_outcomes,
    merge_authoritative_outcomes,
)
from auto_engineering.host.recovery_contract import is_worker_execution_action
from auto_engineering.host.result_attestation import build_validated_attestations
from auto_engineering.host.result_fingerprint import (
    serialize_and_fingerprint_outcomes,
)
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import WorkerAttestationError
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
    _atomic_write_json,
    _canonical_bytes,
)
from auto_engineering.loop.architect_plan_coverage import architect_plan_manifest
from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    compact_worker_receipt,
)


class ResultFinalizationMixin:
    """以已验证 Worker outcomes 组装一次幂等的 Core Result。"""

    project_root: Path

    @staticmethod
    def _normalize_echoed_identity(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _normalize_business_payload(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _finalize_worker_failure(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _finalize_inline(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _preflight(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        raise NotImplementedError

    @staticmethod
    def _architect_coverage_violations(
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
        coordinator_payload: Mapping[str, Any],
    ) -> tuple[str, ...]:
        return architect_result_coverage_violations(
            action=action,
            outcomes=outcomes,
            coordinator_payload=coordinator_payload,
        )

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
        worker_action = is_worker_execution_action(action)
        if worker_action and any(
            outcome.status != "completed" for outcome in outcomes
        ):
            return self._finalize_worker_failure(
                action=action,
                outcomes=outcomes,
            )
        coordinator_payload = self._normalize_echoed_identity(
            action=action,
            coordinator_payload=coordinator_payload,
        )
        coverage_violations = self._architect_coverage_violations(
            action=action,
            outcomes=outcomes,
            coordinator_payload=coordinator_payload,
        )
        if coverage_violations:
            raise HostEvidenceValidationError(coverage_violations)
        coordinator_payload = self._normalize_business_payload(
            action=action,
            coordinator_payload=coordinator_payload,
        )
        if not worker_action:
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
        existing = OutcomeRecoveryService.read_json(journal_path)
        outcome_by_worker = {item.worker_id: item for item in outcomes}
        if existing is not None and existing.get("status") in {
            "rejected",
            "assembly_rejected",
        }:
            authoritative = OutcomeRecoveryService.authoritative_outcomes(
                journal=existing,
                action_message_id=message_id,
                required=existing.get("status") == "rejected",
            )
            if authoritative is not None:
                # Result 修复只允许改变 Coordinator 语义；Worker outcome
                # 由首次事务固定，同一 Worker 后续事实不能替换。
                outcome_by_worker = merge_authoritative_outcomes(
                    authoritative, outcomes
                )
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
        try:
            attestations = build_validated_attestations(
                candidates=outcome_by_worker,
                plan=plan,
                worker_templates=worker_templates,
                action_message_id=context["message_id"],
            )
        except WorkerAttestationError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        serialized_outcomes, outcomes_fingerprint, fingerprint = (
            serialize_and_fingerprint_outcomes(
                action_message_id=message_id,
                outcome_by_worker=outcome_by_worker,
                plan=plan,
                coordinator_payload=coordinator_payload,
            )
        )
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
                build_validated_attestations(
                    candidates={item.worker_id: item for item in parsed_existing},
                    plan=plan,
                    worker_templates=worker_templates,
                    action_message_id=context["message_id"],
                )
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
                incomplete_assembly_rejection = (
                    existing.get("status") == "assembly_rejected"
                    and not isinstance(existing_outcomes_fingerprint, str)
                    and not isinstance(existing.get("outcomes"), list)
                )
                if incomplete_assembly_rejection:
                    existing_outcomes_fingerprint = None
                elif not isinstance(existing_outcomes_fingerprint, str):
                    existing_outcomes_fingerprint = hashlib.sha256(
                        _canonical_bytes({
                            "action_message_id": message_id,
                            "outcomes": existing.get("outcomes", []),
                        })
                    ).hexdigest()
                if (
                    existing_outcomes_fingerprint is not None
                    and existing_outcomes_fingerprint != outcomes_fingerprint
                    and not assembly_rejection_can_extend_outcomes(
                        existing, outcomes
                    )
                ):
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
        if existing is None or existing.get("status") not in {
            "rejected", "assembly_rejected"
        }:
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
        if context["stage"] == "architect" and len(outcomes) == 1:
            # Result 修复可能携带了新的候选 outcome；Worker 事实已经由
            # outcome journal 固化，coverage manifest/digest 必须绑定合并后
            # 的 authoritative outcome，不能让 Coordinator 借候选回写替换它。
            authoritative_outcome = outcome_by_worker[
                plan.invocations[0].worker_id
            ]
            manifest = architect_plan_manifest(
                authoritative_outcome.payload.get("batch_plan")
            )
            if manifest is not None:
                result["extensions"]["architect_plan_coverage"] = manifest
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


__all__ = ["ResultFinalizationMixin"]
