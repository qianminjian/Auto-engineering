"""CLI Result 接受、修复与中断恢复的 canonical projection service。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from auto_engineering.engine.state import EngineState

if TYPE_CHECKING:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore


def record_outcome_acceptance(
    *,
    root: Path,
    submitted_result_file: Path,
    core_response: Mapping[str, Any],
) -> bool:
    """用 Core 响应完成宿主候选 Result 事务；无 journal 时保持兼容。"""


    from auto_engineering.host.outcome_journal import (
        OutcomeJournal,
        OutcomeJournalTransitionError,
    )

    try:
        submitted = json.loads(submitted_result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(submitted, Mapping):
        return False
    journal = OutcomeJournal(root)
    try:
        return journal.complete_from_core(submitted, core_response)
    except OutcomeJournalTransitionError as exc:
        raise RuntimeError(f"OUTCOME_ACCEPTANCE_RECORD_FAILED:{exc}") from exc


def project_result_repair_action(
    active_action: Mapping[str, Any],
    core_response: Mapping[str, Any],
    *,
    state_reconciliation_expected_format: Callable,
    state_reconciliation_result_contract: Callable,
) -> dict[str, Any]:
    """保持 Core active Action 身份，只附加本次候选拒绝事实。"""

    projected = dict(active_action)
    projected["result_rejection"] = {
        "error_code": core_response.get("error_code", "RESULT_REJECTED"),
        "message": core_response.get("message", "Result 未被 Core 接受"),
        "violations": core_response.get("violations", []),
        "repair_required": True,
        "required_operation": "repair_current_action",
        "active_action_message_id": active_action.get("message_id"),
        "forbidden_operations": ["tick_with_old_result", "resume_old_action"],
    }
    original_instruction = active_action.get("instruction")
    gate = active_action.get("gate")
    is_state_reconciliation_gate = (
        active_action.get("action") == "gate"
        and isinstance(gate, Mapping)
        and gate.get("id") == "state_reconciliation"
    )
    if is_state_reconciliation_gate:
        projected["expected_format"] = state_reconciliation_expected_format()
        projected["result_contract"] = state_reconciliation_result_contract()
        repair_instruction = (
            "当前 active Action 是状态协调 Gate。上一次 Result 未被 Core 接受；"
            "只修复当前 Gate 决策，不重做任何项目或 Worker 工作。"
            "coordinator-result 必须严格写成 {\"gate_resolution\": "
            "{\"gate_id\": \"state_reconciliation\", "
            "\"resolution\": \"reinitialize 或 reconcile 的 option id\"}}；"
            "不得提交顶层 decision、gate_id 或 decision 字段。"
            "Result 的 causation_id 由 Finalizer 绑定当前 Gate message_id。"
        )
    else:
        repair_instruction = (
            "上一次候选 Result 未被 Core 接受。保持当前 Action 身份，"
            "只根据 result_rejection 修复当前语义产物；不得重做已完成的 Worker 工作。"
            "随后必须原样执行 action.host_execution.operations 中的 finalize、validate、"
            "submit.argv，只替换 argv 首项 __AE_BUNDLED_RUNNER__；不得手写、复制或猜测"
            "任何路径，不得使用其他 Action 或 /tmp 临时文件作为输入。"
        )
        rejection_message = str(projected["result_rejection"].get("message", ""))
        if "BATCH_DESIGN_ITEM_SCOPE" in rejection_message:
            repair_instruction += (
                "这是机器设计项范围校验，不需要用户输入或重新启动 Worker。"
                "直接从 result_rejection.message 中‘有效 design_item_refs’后的列表"
                "逐字复制到对应 batch 的 design_item_refs；不得使用章节号、标题或 slug。"
            )
    projected["instruction"] = (
        f"{original_instruction}\n\n## Result 修复\n\n{repair_instruction}"
        if isinstance(original_instruction, str) and original_instruction
        else repair_instruction
    )
    host_execution = projected.get("host_execution")
    if isinstance(host_execution, Mapping):
        work_files = host_execution.get("work_files")
        projected["repair_operation"] = {
            "operation": "repair_current_action",
            "action_message_id": active_action.get("message_id"),
            "coordinator_result_ref": (
                work_files.get("coordinator_result")
                if isinstance(work_files, Mapping)
                else None
            ),
            "next_operations": ["finalize", "validate", "submit"],
        }
    return projected


def project_host_attestation_repair_action(
    mapped_action: Mapping[str, Any],
    *,
    worker_id: str,
    detail: str,
    project_result_repair_action_fn: Callable,
) -> dict[str, Any]:
    """保留已完成 Worker 的 active Action，等待宿主补交原生事实。

    私有业务 outcome 已存在时，问题不是 Worker 失败，而是 Host Driver 没有
    调用 ``record-worker-outcome``。若直接生成 ``spawned=false``，Core 会推进
    失败代际并在下一次 Action 上找不到上一代 outcome，最终把可修复的宿主
    回写遗漏放大成重跑/预算耗尽。这个投影只供当前宿主修复，不改变 Core
    持久化的 canonical Action，也不允许重新 spawn。
    """

    projected = project_result_repair_action_fn(
        mapped_action,
        {
            "error_code": "HOST_WORKER_ATTESTATION_MISSING",
            "message": "Worker 业务产物已存在，但宿主原生事实尚未回写。",
            "violations": [f"{worker_id}:{detail}"],
            },
        )
    host_execution = projected.get("host_execution")
    if not isinstance(host_execution, Mapping):
        return projected
    host = dict(host_execution)
    work_files = host.get("work_files")
    recovery: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "worker_attestation_pending",
        "spawn_permitted": False,
        "forbidden_operations": ["spawn_worker"],
        "required_operation": "record_worker_outcome_then_finalize",
        "worker_id": worker_id,
        "detail": detail,
    }
    if isinstance(work_files, Mapping):
        for key in ("outcomes", "coordinator_result", "result"):
            value = work_files.get(key)
            if isinstance(value, str) and value:
                recovery[f"{key}_ref"] = value
    host["recovery"] = recovery
    projected["host_execution"] = host
    # The recovery view retains worker templates for the fixed record command,
    # but removes spawn so a compliant host cannot accidentally launch again.
    projected.pop("spawn", None)
    projected["instruction"] = (
        "当前 Worker 已写入私有业务 outcome，但宿主事实回写缺失。"
        "禁止重新启动或等待新的 Worker；使用仍然有效的原生 Worker 返回值，"
        "按 host_execution.workers[].record_worker_outcome 固定模板补交 handle、"
        "actual_model 和实际 isolation_evidence，随后按当前 Action 的 finalize、"
        "validate、submit 顺序继续。若宿主已丢失原生 handle，必须保留该错误并停止，"
        "不得用 unreported 句柄伪造 completed。"
    )
    return projected


def project_submitted_worker_failure_recovery(
    *,
    action: Mapping[str, Any] | None,
    submitted_result: Mapping[str, Any],
    root: Path,
    map_bound_action_fn: Callable,
    root_bound_path_fn: Callable,
    project_host_attestation_repair_action_fn: Callable,
) -> dict[str, Any] | None:
    """在 Core 消耗失败预算前识别已落盘的私有 Worker 产物。

    宿主可能在原生 Agent 返回后先提交了 ``HOST_WORKER_FAILED``，而尚未执行
    ``record-worker-outcome``。若把这个 Result 直接交给 Core，会把“宿主回写
    漏接”错误地记为 Worker 失败，并推进失败 generation。这里仅识别严格的
    私有业务 artifact；宿主事实仍必须随后通过固定回写合同补齐，不能由 CLI
    猜测或生成。
    """

    if not isinstance(action, Mapping) or not isinstance(action.get("spawn"), Mapping):
        return None
    if submitted_result.get("spawned") is not False:
        return None
    if submitted_result.get("spawn_error_code") not in {
        "HOST_WORKER_FAILED",
        "HOST_WORKER_FAILURE_EXHAUSTED",
    }:
        return None

    from auto_engineering.host.execution_assembler import (
        HostExecutionAssembler,
        WorkerOutcomeCollectionError,
    )

    mapped_action = map_bound_action_fn(
        dict(action),
        root,
        include_failure_journal=False,
    )
    host_execution = mapped_action.get("host_execution")
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
    if not isinstance(outcomes_ref, str) or not outcomes_ref:
        return None
    outcomes_path = root_bound_path_fn(Path(outcomes_ref), root)
    try:
        raw_outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw_outcomes = None
    outcome_items = (
        raw_outcomes.get("outcomes")
        if isinstance(raw_outcomes, Mapping)
        else None
    )
    from auto_engineering.host.worker_evidence import (
        worker_failure_outcomes_are_ready,
    )
    # record-worker-outcome 已经把完整失败事实写入共享 outcomes 时，必须
    # 交回 Core 的 HOST_WORKER_FAILED → resource_wait 路径；不能因为私有
    # artifact 仍然只含业务字段，就再次投影成“等待宿主回写”。
    if worker_failure_outcomes_are_ready(
        action=mapped_action,
        outcome_items=outcome_items,
    ):
        return None
    try:
        HostExecutionAssembler(root).collect_worker_outcomes_from_artifacts(
            action=mapped_action,
            outcomes_path=outcomes_path,
        )
    except WorkerOutcomeCollectionError as exc:
        if exc.code != "HOST_WORKER_ATTESTATION_MISSING":
            return None
        return project_host_attestation_repair_action_fn(
            mapped_action,
            worker_id=exc.worker_id,
            detail=exc.detail or "private_business_artifact_only",
        )
    return None


def process_state_reconciliation_result(
    *,
    result_file: Path,
    root: Path,
    store: SQLiteCheckpointStore[EngineState],
    events: SQLiteEventStore,
    debug: bool = False,
    debug_dir: str | None = None,
    build_injectables_fn: Callable,
    tick_orchestrator_cls: type,
) -> dict | None:
    """处理协调 Gate Result；非协调 Result 返回 None 交回常规 Tick。"""

    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    resolution = result.get("gate_resolution")
    if not isinstance(resolution, dict) or resolution.get("gate_id") != "state_reconciliation":
        return None
    if resolution.get("resolution") == "reconcile":
        return None

    from auto_engineering.loop.protocol import payload_digest
    from auto_engineering.loop.state_reconciliation import StateReconciliationService

    thread_id = result.get("thread_id")
    causation_id = result.get("causation_id")
    if isinstance(thread_id, str) and isinstance(causation_id, str):
        replay = events.load_protocol_result(thread_id, causation_id)
        if replay is not None:
            previous_hash, response = replay
            if previous_hash != payload_digest(result):
                raise ValueError("RESULT_CONFLICT: 相同协调 Gate 已提交不同选择")
            return response

    old_state = events.load_projection(str(thread_id))
    if old_state is None:
        raise ValueError("STATE_CORRUPT: 协调 Result 对应的旧 thread 不存在")
    outcome = StateReconciliationService(events).select(result)
    if outcome.choice != "reinitialize":
        return dict(outcome.response)

    old_thread_id = old_state.thread_id
    store.release_project_thread(old_thread_id)
    new_thread_id = str(uuid4())
    existing = store.reserve_project_thread(new_thread_id)
    if existing is not None:
        raise ValueError(f"PROJECT_THREAD_ACTIVE: {existing}")
    try:
        inj = build_injectables_fn(root)
        orch = tick_orchestrator_cls(
            root,
            checkpoint_store=store,
            event_store=events,
            context_offloader=inj["context_offloader"],
            session_summarizer=inj.get("session_summarizer"),
            tracer=inj["tracer"],
            audit_logger=inj["audit_logger"],
            debug=debug,
            debug_dir=debug_dir,
        )
        design_doc_path = outcome.intent.get("design_doc_path")
        if not isinstance(design_doc_path, str) or not design_doc_path:
            raise ValueError("STATE_RECONCILIATION_INTENT_INVALID")
        from auto_engineering.loop.design_ledger_reinitialization import (
            reinitialize_design_intake,
        )

        resolved_design_doc = Path(design_doc_path)
        if not resolved_design_doc.is_absolute():
            resolved_design_doc = root / resolved_design_doc
        reinitialize_design_intake(root, resolved_design_doc)
        action = orch.init(
            old_state.requirement,
            design_doc_path=design_doc_path,
            thread_id=new_thread_id,
        )
        if isinstance(causation_id, str):
            events.replace_protocol_result_response(
                old_thread_id,
                causation_id,
                action,
            )
        return action
    except BaseException:
        store.release_project_thread(new_thread_id)
        raise


def validate_state_reconciliation_result_file(
    *,
    result_file: Path,
    active_thread: str,
    events: SQLiteEventStore,
) -> dict[str, Any] | None:
    """只读校验状态协调 Result；非协调 Result 返回 None。"""

    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, Mapping):
        return None
    resolution = result.get("gate_resolution")
    if not isinstance(resolution, Mapping):
        return None
    if resolution.get("gate_id") != "state_reconciliation":
        return None

    from auto_engineering.loop.action_responses import ErrorResponse
    from auto_engineering.loop.protocol import ProtocolValidationError
    from auto_engineering.loop.state_reconciliation import (
        StateReconciliationError,
        StateReconciliationService,
    )

    if result.get("thread_id") != active_thread:
        return ErrorResponse(
            "ACTION_NOT_ACTIVE",
            "Result 指向的 thread 不是当前 active thread",
        ).to_dict()
    try:
        StateReconciliationService(events).validate(result)
    except ProtocolValidationError as exc:
        return ErrorResponse(exc.code.value, str(exc)).to_dict()
    except StateReconciliationError as exc:
        return ErrorResponse(
            "STATE_RECONCILIATION_RESULT_INVALID",
            str(exc),
            suggestion="只提交当前 state_reconciliation Gate 的合法 reinitialize 选择。",
        ).to_dict()

    state = events.load_projection(active_thread)
    if state is None:
        return ErrorResponse(
            "STATE_RECONCILIATION_RESULT_INVALID",
            "协调 Result 对应的 active thread 状态不存在",
        ).to_dict()
    return {
        "action": "validation_passed",
        "stage": state.current_stage,
        "thread_id": state.thread_id,
        "causation_id": result.get("causation_id"),
    }
