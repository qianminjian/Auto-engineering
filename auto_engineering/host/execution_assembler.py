"""把宿主真实 Worker outcome 原子终结为 Core 可验证证据。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from auto_engineering.config.runtime_config import get_default_config
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.host.outcome_recovery import OutcomeRecoveryService
from auto_engineering.host.outcome_repair import (
    assembly_rejection_can_extend_outcomes,
    merge_authoritative_outcomes,
)
from auto_engineering.host.result_contract import ResultContractService
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_attestation import (
    WorkerAttestationError,
    validate_attestations,
)
from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    NativeWorkerOutcome,
    WorkerOutcomeCollectionError,
    _atomic_write_bytes,
    _atomic_write_json,
    _business_payload_reports_test_failure,
    _canonical_bytes,
    _canonical_worker_business_status,
    _native_business_artifact,
    _native_handle_is_missing,
    _resolve_worker_execution_binding,
    can_replace_retryable_outcome,
)
from auto_engineering.host.worker_failure import WorkerFailureService
from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    compact_worker_receipt,
    validate_worker_receipt,
)


class HostExecutionAssembler:
    """以 outcome journal 为恢复点，幂等完成一整个 spawn Action。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._outcome_recovery = OutcomeRecoveryService(
            self.project_root,
            finalize=self.finalize,
            finalize_to_file=self.finalize_to_file,
        )
        self._result_contract = ResultContractService()
        self._worker_failure = WorkerFailureService(
            self.project_root,
            recover_completed_worker_artifacts=self.recover_completed_worker_artifacts,
        )

    def stage_native_result(
        self,
        *,
        action: Mapping[str, Any],
        worker_id: str,
        native_result_file: Path,
        raw_envelope: bytes,
    ) -> None:
        """把原生回包原样暂存到当前 Worker 的绑定路径。

        这是 ``record_worker_outcome`` 的输入侧操作，不是另一条状态机：
        它只校验 Action 绑定并原子写入，随后仍由同一个 Assembler 解析、
        合并宿主事实和生成 outcomes。使用 bytes 是为了保留原生 envelope，
        避免宿主先解析/重编码导致证据漂移。
        """

        if not isinstance(raw_envelope, bytes) or not raw_envelope.strip():
            raise HostEvidenceValidationError((
                f"WORKER_NATIVE_RESULT_EMPTY:{worker_id}",
            ))
        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        invocation = next(
            (item for item in plan.invocations if item.worker_id == worker_id),
            None,
        )
        if invocation is None:
            raise HostEvidenceValidationError((f"WORKER_UNKNOWN:{worker_id}",))
        host_execution = action.get("host_execution")
        raw_workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        template = next(
            (
                item for item in raw_workers
                if isinstance(item, Mapping) and item.get("worker_id") == worker_id
            ),
            None,
        ) if isinstance(raw_workers, list) else None
        native_ref = (
            template.get("native_result_path")
            if isinstance(template, Mapping)
            else None
        )
        outcome_ref = (
            template.get("outcome_path")
            if isinstance(template, Mapping)
            else invocation.outcome_path
        )
        native_path = native_result_file.resolve()
        try:
            native_relative = str(native_path.relative_to(self.project_root))
        except ValueError:
            native_relative = ""
        if (
            not isinstance(native_ref, str)
            or native_ref != native_relative
            or not isinstance(outcome_ref, str)
            or native_path == self.project_root
            or self.project_root not in native_path.parents
            or native_path == (self.project_root / outcome_ref).resolve()
        ):
            raise HostEvidenceValidationError((
                f"WORKER_NATIVE_RESULT_PATH_INVALID:{worker_id}",
            ))
        _atomic_write_bytes(native_path, raw_envelope)

    def recover_completed_worker_artifacts(
        self,
        *,
        action: Mapping[str, Any],
        result_path: Path | None = None,
    ) -> dict[str, Any] | None:
        """在 Coordinator 文件缺失时，从已提交的单 Worker 业务产物恢复。

        这是宿主上下文在 ``WorkerOutcome`` 已落盘后的崩溃恢复，不是重新
        执行 Worker。多 Worker 的合并语义必须由 Coordinator 提供，因此
        不在这里猜测或拼接。
        """

        host_execution = action.get("host_execution")
        work_files = (
            host_execution.get("work_files")
            if isinstance(host_execution, Mapping)
            else None
        )
        outcomes_ref = (
            work_files.get("outcomes")
            if isinstance(work_files, Mapping)
            else None
        )
        coordinator_ref = (
            work_files.get("coordinator_result")
            if isinstance(work_files, Mapping)
            else None
        )
        result_ref = (
            work_files.get("result")
            if isinstance(work_files, Mapping)
            else None
        )

        def bound_path(value: object) -> Path | None:
            if not isinstance(value, (str, Path)) or not value:
                return None
            candidate = Path(value)
            resolved = (
                candidate.resolve()
                if candidate.is_absolute()
                else (self.project_root / candidate).resolve()
            )
            if resolved == self.project_root or self.project_root not in resolved.parents:
                return None
            return resolved

        outcomes_path = bound_path(outcomes_ref)
        if outcomes_path is None:
            message_id = action.get("message_id")
            if not isinstance(message_id, str) or not message_id:
                return None
            outcomes_path = (
                self.project_root
                / ".ae-state/host-runtime/recovery"
                / f"{message_id}.outcomes.json"
            )
        try:
            outcomes = self.collect_worker_outcomes_from_artifacts(
                action=action,
                outcomes_path=outcomes_path,
            )
        except WorkerOutcomeCollectionError:
            return None
        if len(outcomes) != 1 or outcomes[0].status != "completed":
            return None
        payload = outcomes[0].payload
        if not isinstance(payload, dict):
            return None
        coordinator_path = bound_path(coordinator_ref)
        if coordinator_path is not None:
            _atomic_write_json(coordinator_path, payload)
        effective_result_path = bound_path(result_path) if result_path is not None else bound_path(result_ref)
        if effective_result_path is None:
            return self.finalize(
                action=action,
                outcomes=outcomes,
                coordinator_payload=payload,
            )
        return self.finalize_to_file(
            action=action,
            outcomes=outcomes,
            coordinator_payload=payload,
            result_path=effective_result_path,
        )

    def record_worker_outcome(
        self,
        *,
        action: Mapping[str, Any],
        worker_id: str,
        native_worker_handle: str | None,
        native_result_file: Path | None = None,
        status: str,
        actual_model: str = "unreported",
        isolation_evidence: str | None = None,
    ) -> dict[str, Any]:
        """把一个 Worker 业务产物与宿主原生事实合并到共享 outcomes。

        这是主 Agent 在原生 spawn 返回后调用的唯一写入口。Worker 私有文件
        永远不被覆盖；宿主事实只从本次调用参数和 Action 模板取得，合并结果
        以同目录原子替换写入，避免主 Agent 手工拼装协议 JSON。
        """

        if not isinstance(worker_id, str) or not worker_id:
            raise HostEvidenceValidationError(("WORKER_ID_MISSING",))
        allowed_statuses = {"completed", "failed", "cancelled", "timeout", "timed_out", "errored"}
        if status not in allowed_statuses:
            raise HostEvidenceValidationError((f"WORKER_STATUS_INVALID:{worker_id}",))
        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        invocation = next(
            (item for item in plan.invocations if item.worker_id == worker_id),
            None,
        )
        if invocation is None:
            raise HostEvidenceValidationError((f"WORKER_UNKNOWN:{worker_id}",))
        host_execution = action.get("host_execution")
        raw_workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        template = next(
            (
                item for item in raw_workers
                if isinstance(item, Mapping) and item.get("worker_id") == worker_id
            ),
            None,
        ) if isinstance(raw_workers, list) else None
        outcome_ref = (
            template.get("outcome_path")
            if isinstance(template, Mapping)
            else invocation.outcome_path
        )
        if not isinstance(outcome_ref, str) or not outcome_ref:
            raise HostEvidenceValidationError((f"WORKER_OUTCOME_PATH_MISSING:{worker_id}",))
        outcome_path = (self.project_root / outcome_ref).resolve()
        if outcome_path == self.project_root or self.project_root not in outcome_path.parents:
            raise HostEvidenceValidationError((f"WORKER_OUTCOME_PATH_INVALID:{worker_id}",))
        def load_native_business() -> dict[str, Any]:
            if native_result_file is None:
                raise HostEvidenceValidationError((
                    f"WORKER_NATIVE_RESULT_MISSING:{worker_id}",
                ))
            native_ref = template.get("native_result_path") if isinstance(template, Mapping) else None
            native_path = native_result_file.resolve()
            try:
                native_relative = str(native_path.relative_to(self.project_root))
            except ValueError:
                native_relative = ""
            if (
                not isinstance(native_ref, str)
                or native_ref != native_relative
                or native_path == self.project_root
                or self.project_root not in native_path.parents
                or native_path == outcome_path
            ):
                raise HostEvidenceValidationError((
                    f"WORKER_NATIVE_RESULT_PATH_INVALID:{worker_id}",
                ))
            try:
                native_raw = json.loads(native_path.read_text(encoding="utf-8"))
                return _native_business_artifact(
                    native_raw,
                    worker_id=worker_id,
                    status=status,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                HostEvidenceValidationError,
            ) as exc:
                raise HostEvidenceValidationError((
                    f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
                )) from exc

        if not outcome_path.is_file():
            # 只有私有文件完全缺失时，Host 才能从本次原生回包恢复一次。
            # 一旦 Worker 已经写出文件，该文件就是唯一业务权威；不能
            # 用另一条 native 解析路径覆盖 Worker 的非法协议。
            raw_business = load_native_business()
            _atomic_write_json(outcome_path, raw_business)
        else:
            try:
                raw_business = json.loads(outcome_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HostEvidenceValidationError((
                    f"WORKER_BUSINESS_ARTIFACT_INVALID:{worker_id}",
                )) from exc
        if isinstance(raw_business, Mapping) and isinstance(raw_business.get("outcome"), Mapping):
            raw_business = raw_business["outcome"]
        # Claude Worker 偶尔会把 expected_format 业务对象直接写到私有路径，
        # 虽然没有携带 Host 身份字段，但仍然是当前 Worker 已授权的业务产物。
        # 在唯一的 record 边界按当前 Action 的 expected_format 做一次确定性
        # envelope 归一化；不覆盖原文件，也不从自然语言或宿主字段推断事实。
        if isinstance(raw_business, Mapping):
            expected_format = action.get("expected_format")
            expected_keys = (
                set(expected_format)
                if isinstance(expected_format, Mapping)
                else set()
            )
            forbidden_business = {
                "spawned", "spawn_proof_token", "native_worker_handle", "actual_model",
                "isolation_evidence", "worker_attestations", "attestation", "receipt",
            }
            if (
                expected_keys
                and expected_keys.issubset(raw_business)
                and not forbidden_business.intersection(raw_business)
                and not {"worker_id", "status", "payload", "summary"}.intersection(raw_business)
            ):
                raw_business = {
                    "worker_id": worker_id,
                    "status": status,
                    "payload": dict(raw_business),
                    "summary": "native_worker_result",
                }
            elif (
                set(raw_business) == {"worker_id", "status", "payload"}
                and raw_business.get("worker_id") == worker_id
                and isinstance(raw_business.get("status"), str)
                and isinstance(raw_business.get("payload"), dict)
            ):
                # ``summary`` is audit metadata, not business data.  Native
                # result parsing already applies this normalization; apply
                # the same one at the private-file handoff so a Worker that
                # omitted only this metadata does not lose a valid payload.
                # Keep the private artifact untouched: the Host only
                # normalizes the in-memory envelope before merging facts.
                raw_business = {
                    **raw_business,
                    "summary": "native_worker_result",
                }
        required_business = {"worker_id", "status", "payload", "summary"}
        if (
            not isinstance(raw_business, Mapping)
            or not required_business.issubset(raw_business)
        ):
            raise HostEvidenceValidationError((
                f"WORKER_BUSINESS_ARTIFACT_INVALID:{worker_id}",
            ))
        forbidden_business = {
            "spawned", "spawn_proof_token", "native_worker_handle", "actual_model",
            "isolation_evidence", "worker_attestations", "attestation", "receipt",
        }
        if forbidden_business.intersection(raw_business):
            raise HostEvidenceValidationError((f"WORKER_BUSINESS_BOUNDARY_VIOLATION:{worker_id}",))
        if set(raw_business) != required_business:
            raise HostEvidenceValidationError((f"WORKER_BUSINESS_BOUNDARY_VIOLATION:{worker_id}",))
        if raw_business.get("worker_id") != worker_id or not isinstance(raw_business.get("payload"), dict):
            raise HostEvidenceValidationError((f"WORKER_BUSINESS_ARTIFACT_INVALID:{worker_id}",))
        business_status = raw_business.get("status")
        status_key = _canonical_worker_business_status(status)
        business_status_key = _canonical_worker_business_status(business_status)
        if business_status_key != status_key:
            raise HostEvidenceValidationError((f"WORKER_STATUS_CONFLICT:{worker_id}",))
        # Worker 可能已经完成执行，但其业务测试仍然失败。这个事实由
        # payload 自身确定性分类为 Host failure；不修改私有 artifact，
        # 也不要求 Coordinator 伪造 status 或把失败计数改成 0。
        effective_status = (
            "failed"
            if status_key == "completed"
            and _business_payload_reports_test_failure(raw_business["payload"])
            else status
        )
        summary = raw_business.get("summary")
        if not isinstance(summary, str):
            raise HostEvidenceValidationError((f"WORKER_BUSINESS_ARTIFACT_INVALID:{worker_id}",))
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HostEvidenceValidationError(("ACTION_MESSAGE_ID_MISSING",))
        handle = native_worker_handle
        if not handle:
            handle = f"unreported:{message_id}:{worker_id}"
        if effective_status == "completed" and _native_handle_is_missing(handle):
            raise HostEvidenceValidationError((f"NATIVE_WORKER_HANDLE_MISSING:{worker_id}",))
        model = actual_model if isinstance(actual_model, str) and actual_model else "unreported"
        isolation = isolation_evidence.strip() if isinstance(isolation_evidence, str) else None
        if effective_status == "completed" and not isolation:
            raise HostEvidenceValidationError((f"NATIVE_ISOLATION_EVIDENCE_MISSING:{worker_id}",))
        generation, fence = _resolve_worker_execution_binding(
            action,
            template if isinstance(template, Mapping) else None,
            worker_id,
        )
        outcome = NativeWorkerOutcome(
            worker_id=worker_id,
            native_worker_handle=handle,
            status=effective_status,
            payload=dict(raw_business["payload"]),
            summary=summary,
            actual_model=model,
            isolation_evidence=isolation,
            execution_generation=generation if isinstance(generation, int) else None,
            fencing_token=fence if isinstance(fence, str) else None,
        )
        return self._merge_outcome_into_shared(
            action=action,
            plan=plan,
            outcome=outcome,
        )

    def record_invalid_worker_failure(
        self,
        *,
        action: Mapping[str, Any],
        worker_id: str,
        native_worker_handle: str | None,
        actual_model: str = "unreported",
        isolation_evidence: str | None = None,
        detail: str,
        native_output_available: bool = False,
    ) -> dict[str, Any]:
        """把非法 Worker 业务产物收敛为同一条宿主失败事实路径。

        私有业务文件已经存在时，它仍是唯一业务权威，不能被 native 回包
        覆盖或猜测修复。这里只记录有界的宿主诊断和执行身份，随后复用
        ``_merge_outcome_into_shared`` 与 ``WorkerFailureService`` 的既有链路。
        """

        if not isinstance(worker_id, str) or not worker_id:
            raise HostEvidenceValidationError(("WORKER_ID_MISSING",))
        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            raise HostEvidenceValidationError((str(exc),)) from exc
        invocation = next(
            (item for item in plan.invocations if item.worker_id == worker_id),
            None,
        )
        if invocation is None:
            raise HostEvidenceValidationError((f"WORKER_UNKNOWN:{worker_id}",))
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HostEvidenceValidationError(("ACTION_MESSAGE_ID_MISSING",))
        host_execution = action.get("host_execution")
        raw_workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        template = next(
            (
                item for item in raw_workers
                if isinstance(item, Mapping) and item.get("worker_id") == worker_id
            ),
            None,
        ) if isinstance(raw_workers, list) else None
        generation, fence = _resolve_worker_execution_binding(
            action,
            template if isinstance(template, Mapping) else None,
            worker_id,
        )
        bounded_detail = detail.strip()[:512] if isinstance(detail, str) else ""
        if not bounded_detail:
            bounded_detail = f"WORKER_BUSINESS_ARTIFACT_INVALID:{worker_id}"
        handle = native_worker_handle or f"unreported:{message_id}:{worker_id}"
        model = actual_model.strip() if isinstance(actual_model, str) else ""
        isolation = (
            isolation_evidence.strip()
            if isinstance(isolation_evidence, str) and isolation_evidence.strip()
            else "unreported"
        )
        outcome = NativeWorkerOutcome(
            worker_id=worker_id,
            native_worker_handle=handle,
            status="failed",
            payload={
                "error_code": "HOST_WORKER_OUTPUT_INVALID",
                "detail": bounded_detail,
                "native_output_available": bool(native_output_available),
            },
            summary=f"HOST_WORKER_OUTPUT_INVALID:{worker_id}:{bounded_detail}"[:512],
            actual_model=model or "unreported",
            isolation_evidence=isolation,
            execution_generation=generation if isinstance(generation, int) else None,
            fencing_token=fence if isinstance(fence, str) else None,
        )
        return self._merge_outcome_into_shared(
            action=action,
            plan=plan,
            outcome=outcome,
        )

    def _merge_outcome_into_shared(
        self,
        *,
        action: Mapping[str, Any],
        plan: SpawnPlan,
        outcome: NativeWorkerOutcome,
    ) -> dict[str, Any]:
        """把一个已分类 outcome 幂等合并到当前 Action 的共享副本。"""

        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HostEvidenceValidationError(("ACTION_MESSAGE_ID_MISSING",))
        host_execution = action.get("host_execution")
        work_files = host_execution.get("work_files") if isinstance(host_execution, Mapping) else None
        outcomes_ref = work_files.get("outcomes") if isinstance(work_files, Mapping) else None
        outcomes_path = (
            (self.project_root / outcomes_ref).resolve()
            if isinstance(outcomes_ref, str) and outcomes_ref
            else self.project_root / ".ae-state/host-runtime/recovery" / f"{message_id}.outcomes.json"
        )
        if outcomes_path == self.project_root or self.project_root not in outcomes_path.parents:
            raise HostEvidenceValidationError(("OUTCOMES_OUTPUT_PATH_INVALID",))
        existing_raw: object = []
        if outcomes_path.is_file():
            try:
                existing_raw = json.loads(outcomes_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                # outcomes.json 是当前 Action 的可重建工作副本，不是 Core
                # 权威账本。新的 Host 回写已通过 native handle/model/
                # isolation 校验后，可以原子重建损坏副本；权威历史仍由
                # Outcome Journal 保存，不能让半成品阻断同一 Action 恢复。
                existing_raw = []
        existing_items = existing_raw.get("outcomes") if isinstance(existing_raw, Mapping) else existing_raw
        if not isinstance(existing_items, list):
            existing_items = []
        existing_by_worker: dict[str, NativeWorkerOutcome] = {}
        for item in existing_items:
            if not isinstance(item, Mapping):
                continue
            try:
                parsed = NativeWorkerOutcome(**dict(item))
            except (TypeError, ValueError):
                # 旧宿主可能已将 host-only 半成品写入共享副本。它没有
                # Worker 业务 payload，不能参与合并，也不能覆盖本次已验证
                # 的 outcome；后续 Core 仍会校验完整 Worker 集合。
                continue
            if parsed.worker_id in existing_by_worker:
                # 重复条目使该 Worker 的旧副本不具备确定性；丢弃旧条目，
                # 由本次原生回写提供唯一事实。其他 Worker 仍可保留。
                existing_by_worker.pop(parsed.worker_id)
                continue
            existing_by_worker[parsed.worker_id] = parsed
        previous = existing_by_worker.get(outcome.worker_id)
        if previous is None:
            existing_by_worker[outcome.worker_id] = outcome
        elif previous.to_dict() == outcome.to_dict():
            return outcome.to_dict()
        elif not can_replace_retryable_outcome(previous, outcome):
            raise HostEvidenceValidationError((
                f"OUTCOMES_CONFLICT:{outcome.worker_id}",
            ))
        else:
            existing_by_worker[outcome.worker_id] = outcome
        merged = [
            existing_by_worker[item.worker_id]
            for item in plan.invocations
            if item.worker_id in existing_by_worker
        ]
        _atomic_write_json(outcomes_path, {"outcomes": [item.to_dict() for item in merged]})
        return outcome.to_dict()

    def collect_worker_outcomes_from_artifacts(
        self,
        *,
        action: Mapping[str, Any],
        outcomes_path: Path,
    ) -> list[NativeWorkerOutcome]:
        """汇总每个 Worker 的私有产出，形成唯一共享 outcomes 文件。

        Coordinator 不再负责创造 Worker 事实；它只负责合并已存在的、按
        invocation 绑定的 WorkerOutcome。当前 Action 必须提供 canonical
        ``outcome_path``，缺失或不可读时直接 fail-closed。
        """

        try:
            plan = SpawnPlan.from_action(action)
        except SpawnContractError as exc:
            raise WorkerOutcomeCollectionError(
                "HOST_WORKER_OUTPUT_INVALID", "unknown", str(exc)
            ) from exc
        outcomes: list[NativeWorkerOutcome] = []
        host_execution = action.get("host_execution")
        worker_templates = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        template_by_worker = {
            item.get("worker_id"): item
            for item in worker_templates
            if isinstance(item, Mapping) and isinstance(item.get("worker_id"), str)
        } if isinstance(worker_templates, list) else {}
        for invocation in plan.invocations:
            template = template_by_worker.get(invocation.worker_id)
            if isinstance(template, Mapping):
                candidate = template.get("outcome_path")
                if not isinstance(candidate, str) or not candidate:
                    raise WorkerOutcomeCollectionError(
                        "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                        "outcome_path_missing",
                    )
                if candidate != invocation.outcome_path:
                    raise WorkerOutcomeCollectionError(
                        "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                        "outcome_path_drift",
                    )
            relative = invocation.outcome_path
            path = (self.project_root / relative).resolve()
            if path == self.project_root or self.project_root not in path.parents:
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    "path_outside_project",
                )
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_MISSING", invocation.worker_id
                ) from exc
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    exc.__class__.__name__,
                ) from exc
            if isinstance(raw, Mapping) and isinstance(raw.get("outcome"), Mapping):
                raw = raw["outcome"]
            if not isinstance(raw, Mapping):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    "top_level_must_be_object",
                )
            # 私有文件是 Worker 业务边界，不是宿主事实边界。若只收到业务
            # 字段，不能把它升级成 NativeWorkerOutcome；必须等 Host Driver
            # 用原生 API 返回的句柄/模型/隔离证据完成合并，否则会把模型文本
            # 或 unreported 哨兵误当成真实宿主证明。
            business_fields = {"worker_id", "status", "payload", "summary"}
            host_fields = {
                "native_worker_handle", "actual_model", "isolation_evidence",
            }
            if (
                (bool(raw) and set(raw).issubset(business_fields))
                or (
                    business_fields.issubset(raw)
                    and not (host_fields & set(raw))
                )
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_ATTESTATION_MISSING", invocation.worker_id,
                    "private_business_artifact_only",
                )
            try:
                outcome = NativeWorkerOutcome(**dict(raw))
            except (TypeError, ValueError) as exc:
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    exc.__class__.__name__,
                ) from exc
            if outcome.worker_id != invocation.worker_id:
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    "worker_id_mismatch",
                )
            if (
                outcome.status == "completed"
                and outcome.native_worker_handle.startswith("unreported:")
            ):
                # native handle 必须来自宿主原生 spawn 返回；Worker 不能用
                # 哨兵值冒充 Host Attestation。模型未知仍可使用 unreported，
                # 但句柄未知不能提交成功证据。
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_INVALID", invocation.worker_id,
                    "native_handle_unreported",
                )
            expected_generation, expected_fence = _resolve_worker_execution_binding(
                action,
                template if isinstance(template, Mapping) else None,
                invocation.worker_id,
            )
            if (
                (expected_generation is not None or expected_fence is not None)
                and (
                    not isinstance(expected_generation, int)
                    or expected_generation < 1
                    or not isinstance(expected_fence, str)
                    or len(expected_fence) != 64
                    or outcome.execution_generation != expected_generation
                    or outcome.fencing_token != expected_fence
                )
            ):
                raise WorkerOutcomeCollectionError(
                    "HOST_WORKER_OUTPUT_STALE", invocation.worker_id,
                    "execution_fence_mismatch",
                )
            outcomes.append(outcome)
        _atomic_write_json(outcomes_path, {"outcomes": [item.to_dict() for item in outcomes]})
        return outcomes

    def restore_committed_result_to_file(
        self,
        *,
        action: Mapping[str, Any],
        result_path: Path,
        outcomes_path: Path | None = None,
    ) -> dict[str, Any] | None:
        return self._outcome_recovery.restore_committed_result_to_file(
            action=action,
            result_path=result_path,
            outcomes_path=outcomes_path,
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
                # 语义预检可能在 Worker 尚未全部回写时产生
                # ``assembly_rejected``。这类记录只有 Coordinator 的拒绝
                # 证据，没有权威 outcomes；不能把空列表指纹锁死，阻止
                # 后续补齐 Worker 后的合法重试。若已有 outcomes，则仍按
                # 指纹严格拒绝替换事实。
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
        return ResultContractService.normalize_echoed_identity(
            action=action,
            coordinator_payload=coordinator_payload,
        )

    @staticmethod
    def _normalize_business_payload(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return ResultContractService.normalize_business_payload(
            action=action,
            coordinator_payload=coordinator_payload,
        )

    @staticmethod
    def _matches_json_type(value: object, expected: Sequence[object]) -> bool:
        return ResultContractService.matches_json_type(value, expected)

    def _finalize_worker_failure(
        self,
        *,
        action: Mapping[str, Any],
        outcomes: Sequence[NativeWorkerOutcome],
    ) -> dict[str, Any]:
        return self._worker_failure.finalize_worker_failure(
            action=action,
            outcomes=outcomes,
        )

    def finalize_missing_worker_output(
        self,
        *,
        action: Mapping[str, Any],
        reason_code: str = "HOST_WORKER_OUTPUT_MISSING",
        detail: str = "宿主未收到 Worker 的结构化输出",
        result_path: Path | None = None,
    ) -> dict[str, Any]:
        return self._worker_failure.finalize_missing_worker_output(
            action=action,
            reason_code=reason_code,
            detail=detail,
            result_path=result_path,
        )

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
        existing = OutcomeRecoveryService.read_json(journal_path)
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
    @staticmethod
    def _bind_core_auto_decision(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return ResultContractService.bind_core_auto_decision(
            action=action,
            coordinator_payload=coordinator_payload,
        )

    @staticmethod
    def _bind_core_stage_fields(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return ResultContractService.bind_core_stage_fields(
            action=action,
            coordinator_payload=coordinator_payload,
        )

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
            challenge = OutcomeRecoveryService.read_json(challenge_path)
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
    @staticmethod
    def _coordinator_payload_violations(
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> list[str]:
        return ResultContractService.coordinator_payload_violations(
            action,
            coordinator_payload,
        )

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
    "WorkerOutcomeCollectionError",
    "collect_host_evidence_violations",
]
