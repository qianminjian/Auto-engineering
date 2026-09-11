"""Worker 失败事实的分类、幂等 Journal 和有界恢复边界。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.host.outcome_recovery import OutcomeRecoveryService
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
    _atomic_write_json,
    _canonical_bytes,
    _resolve_worker_execution_binding,
)
from auto_engineering.host.worker_failure_recovery import (
    read_recorded_failure_outcomes,
)

_RecoverCompleted = Callable[..., dict[str, Any] | None]


class WorkerFailureService:
    """只处理 Worker 失败证据，不拥有 Tick、Action 或 Worker 启动权。"""

    def __init__(
        self,
        project_root: Path,
        *,
        recover_completed_worker_artifacts: _RecoverCompleted,
    ) -> None:
        self.project_root = project_root.resolve()
        self._recover_completed_worker_artifacts = recover_completed_worker_artifacts

    def finalize_worker_failure(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
    ) -> dict[str, Any]:
        """把原生 Worker 失败事实终结为不可伪装成业务成功的 Result。"""

        violations: list[str] = []
        try:
            plan = SpawnPlan.for_recording(action)
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
        host_execution = action.get("host_execution")
        raw_workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        templates = {
            item.get("worker_id"): item
            for item in raw_workers
            if isinstance(item, Mapping) and isinstance(item.get("worker_id"), str)
        } if isinstance(raw_workers, list) else {}
        allowed_statuses = {"errored", "failed", "cancelled", "timeout", "timed_out"}
        for outcome in outcomes:
            violations.append(f"WORKER_NOT_COMPLETED:{outcome.worker_id}")
            if outcome.status not in allowed_statuses:
                violations.append(f"WORKER_FAILURE_STATUS_INVALID:{outcome.worker_id}")
            if not outcome.native_worker_handle:
                violations.append(f"NATIVE_WORKER_HANDLE_MISSING:{outcome.worker_id}")
            if not outcome.actual_model:
                violations.append(f"ACTUAL_MODEL_MISSING:{outcome.worker_id}")
            try:
                expected_generation, expected_fence = _resolve_worker_execution_binding(
                    action,
                    templates.get(outcome.worker_id),
                    outcome.worker_id,
                )
            except HostEvidenceValidationError as exc:
                violations.extend(exc.violations)
            else:
                if (
                    expected_generation is not None
                    and (
                        outcome.execution_generation != expected_generation
                        or outcome.fencing_token != expected_fence
                    )
                ):
                    violations.append(
                        f"WORKER_OUTCOME_STALE:{outcome.worker_id}:execution_fence_mismatch"
                    )
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
        # 重试预算按失败类别隔离。Prompt/hash/能力等宿主合同错误不能消耗
        # Worker 超时预算，否则“第一次输入错误 + 第一次真实超时”会被错误
        # 判定为连续两次超时并提前终止当前 Action。
        failure_kind = "timeout" if is_timeout else "worker"
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
        existing = OutcomeRecoveryService.read_json(journal_path)
        failure_attempt = 1
        attempt_history: list[dict[str, Any]] = []
        if existing is not None:
            committed_result = existing.get("result")
            previous_result = committed_result
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
            previous_kind = existing.get("failure_kind")
            if previous_kind is None:
                previous_result = existing.get("result")
                previous_code = (
                    previous_result.get("spawn_error_code")
                    if isinstance(previous_result, Mapping)
                    else None
                )
                previous_kind = (
                    "timeout" if previous_code == "HOST_WORKER_TIMEOUT" else "worker"
                )
            previous_attempt = existing.get("failure_attempt")
            raw_history = existing.get("attempt_history")
            if isinstance(raw_history, list):
                attempt_history = [
                    dict(item) for item in raw_history[-7:]
                    if isinstance(item, Mapping)
                ]
            attempt_history.append({
                "failure_kind": previous_kind,
                "failure_attempt": (
                    previous_attempt
                    if isinstance(previous_attempt, int)
                    and not isinstance(previous_attempt, bool)
                    else 1
                ),
                "spawn_error_code": (
                    previous_result.get("spawn_error_code")
                    if isinstance(previous_result, Mapping)
                    else None
                ),
                "fingerprint": existing.get("fingerprint"),
            })
            if (
                previous_kind == failure_kind
                and isinstance(previous_attempt, int)
                and not isinstance(previous_attempt, bool)
            ):
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
            "failure_kind": failure_kind,
            "attempt_history": attempt_history,
            "fingerprint": fingerprint,
            "failure_attempt": failure_attempt,
            "action_message_id": message_id,
            "outcomes": serialized_outcomes,
            "result": result,
        })
        return result

    def finalize_missing_worker_output(
        self,
        *,
        action: Mapping[str, Any],
        reason_code: str = "HOST_WORKER_OUTPUT_MISSING",
        detail: str = "宿主未收到 Worker 的结构化输出",
        result_path: Path | None = None,
    ) -> dict[str, Any]:
        """将 Worker 无输出转换为可重试的失败 Result。"""

        if reason_code in {
            "HOST_WORKER_OUTPUT_MISSING",
            "HOST_WORKER_OUTPUT_INVALID",
        }:
            recovered = self._recover_completed_worker_artifacts(
                action=action,
                result_path=result_path,
            )
            if recovered is not None:
                return recovered
            recorded_failure = read_recorded_failure_outcomes(
                self.project_root,
                action,
            )
            if recorded_failure is not None:
                result = self.finalize_worker_failure(
                    action=action,
                    outcomes=recorded_failure,
                )
                if result_path is not None:
                    target = (
                        result_path.resolve()
                        if result_path.is_absolute()
                        else (self.project_root / result_path).resolve()
                    )
                    if target == self.project_root or self.project_root not in target.parents:
                        raise HostEvidenceValidationError(
                            ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
                        )
                    _atomic_write_json(target, result)
                return result

        try:
            plan = SpawnPlan.for_recording(action)
        except SpawnContractError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HostEvidenceValidationError(("ACTION_MESSAGE_ID_MISSING",))
        platform = (
            action.get("host_execution", {}).get("platform")
            if isinstance(action.get("host_execution"), Mapping)
            else None
        )
        isolation = (
            "fork_context=false" if platform == "codex"
            else "fresh_context" if platform == "claude-code"
            else None
        )
        outcomes = []
        for invocation in plan.invocations:
            template = None
            host_execution = action.get("host_execution")
            raw_workers = (
                host_execution.get("workers")
                if isinstance(host_execution, Mapping)
                else None
            )
            if isinstance(raw_workers, list):
                template = next(
                    (
                        item for item in raw_workers
                        if isinstance(item, Mapping)
                        and item.get("worker_id") == invocation.worker_id
                    ),
                    None,
                )
            generation, fence = _resolve_worker_execution_binding(
                action,
                template,
                invocation.worker_id,
            )
            outcomes.append(NativeWorkerOutcome(
                worker_id=invocation.worker_id,
                native_worker_handle=(
                    f"unreported:{message_id}:{invocation.worker_id}"
                ),
                status="failed",
                payload={
                    "error_code": reason_code,
                    "detail": detail,
                    "native_output_available": False,
                },
                summary=f"{reason_code}: {detail}",
                actual_model="unreported",
                isolation_evidence=isolation,
                execution_generation=generation,
                fencing_token=fence,
            ))
        result = self.finalize_worker_failure(
            action=action,
            outcomes=outcomes,
        )
        if result_path is not None:
            target = (
                result_path.resolve()
                if result_path.is_absolute()
                else (self.project_root / result_path).resolve()
            )
            if target == self.project_root or self.project_root not in target.parents:
                raise HostEvidenceValidationError(
                    ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
                )
            _atomic_write_json(target, result)
        return result

__all__ = ["WorkerFailureService"]
