"""Worker 业务产物与宿主原生证据的边界原语。

本模块只负责 Worker evidence 的值对象、原生回包解析和 Action 代际绑定。
它不推进 Tick、不创建 Action，也不负责最终 Result 组装；这些职责仍由
``HostExecutionAssembler`` 与 Core 持有。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class HostEvidenceValidationError(ValueError):
    """一次报告全部证据问题，避免宿主逐轮修补 JSON。"""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(dict.fromkeys(violations))
        super().__init__("HOST_EVIDENCE_INVALID: " + ",".join(self.violations))


class WorkerOutcomeCollectionError(ValueError):
    """Worker 私有产出无法汇总为 Action-scoped outcomes。"""

    def __init__(self, code: str, worker_id: str, detail: str = "") -> None:
        self.code = code
        self.worker_id = worker_id
        self.detail = detail
        suffix = f":{detail}" if detail else ""
        super().__init__(f"{code}:{worker_id}{suffix}")


def _native_handle_is_missing(value: str | None) -> bool:
    """识别宿主显式传入的缺失句柄哨兵，避免误当成真实句柄。"""

    return not value or value == "unreported" or value.startswith("unreported:")


def _canonical_worker_business_status(value: object) -> str | None:
    """在 Worker 与 Host 的唯一交接边界归一化业务状态。"""

    if not isinstance(value, str):
        return None
    return {
        "complete": "completed",
        "success": "completed",
        "ok": "completed",
        "timeout": "timed_out",
    }.get(value, value)


def _business_payload_reports_test_failure(payload: Mapping[str, Any]) -> bool:
    """判断业务产物是否明确报告了测试失败或测试错误。

    这是 Worker 业务产物进入宿主失败终结路径的唯一分类规则。只接受
    非布尔整数且大于零，避免把字符串、布尔值或缺失字段猜测成失败。
    """

    test_results = payload.get("test_results")
    if not isinstance(test_results, Mapping):
        return False
    return any(
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        for key in ("failed", "errors")
        for value in (test_results.get(key),)
    )


def _native_business_artifact(
    raw: object,
    *,
    worker_id: str,
    status: str,
) -> dict[str, Any]:
    """从原生 Agent 返回中提取唯一业务对象，不采纳宿主事实字段。

    Claude 的原生返回通常是 ``{"content": [{"type": "text", ...}]}``，
    而 Worker 可能在文本中使用 JSON fenced block。这里仅接受一个对象；
    结果若已经是四字段 Worker artifact 则原样校验，否则把纯业务对象放入
    当前 Host 已知的 Worker envelope。句柄、模型和隔离事实永远不从文本读取。
    """

    required = {"worker_id", "status", "payload", "summary"}
    envelope_identity = {"worker_id", "status", "payload"}
    host_fields = {
        "native_worker_handle", "actual_model", "isolation_evidence",
        "attestation", "worker_attestations", "receipt", "outcomes",
    }

    # Codex 原生 Worker 的结构化返回在 Host 暂存时可能带一个单层
    # ``result`` envelope。只接受精确的单键包装且只解一层；不能递归猜测
    # 任意对象，否则会把 Worker 自己声明的协议字段误当成宿主事实。
    if isinstance(raw, Mapping) and set(raw) == {"result"}:
        wrapped = raw["result"]
        if not isinstance(wrapped, Mapping):
            raise HostEvidenceValidationError((
                f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
            ))
        raw = wrapped

    candidates: list[Mapping[str, Any]] = []
    if isinstance(raw, Mapping) and set(raw) == required:
        candidates = [raw]
    elif isinstance(raw, Mapping) and isinstance(raw.get("content"), list):
        content_blocks = raw["content"]
        assert isinstance(content_blocks, list)
        texts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, Mapping) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                texts.append(text)
        for text in texts:
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    candidate = json.loads(stripped)
                except json.JSONDecodeError:
                    candidate = None
                if isinstance(candidate, Mapping):
                    candidates.append(candidate)
            for match in re.findall(
                r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL
            ):
                try:
                    candidate = json.loads(match)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, Mapping):
                    candidates.append(candidate)
    elif isinstance(raw, list):
        texts = []
        for block in raw:
            if not isinstance(block, Mapping) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                texts.append(text)
        for text in texts:
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    candidate = json.loads(stripped)
                except json.JSONDecodeError:
                    candidate = None
                if isinstance(candidate, Mapping):
                    candidates.append(candidate)
            for match in re.findall(
                r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL
            ):
                try:
                    candidate = json.loads(match)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, Mapping):
                    candidates.append(candidate)
    elif isinstance(raw, Mapping):
        # Codex 的结构化 Worker 返回也可能已经是裸业务对象。它仍然只
        # 作为 payload 使用，宿主 envelope 继续由本次 record 调用绑定。
        candidates = [raw]
    if len(candidates) != 1:
        raise HostEvidenceValidationError((
            f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
        ))

    candidate = candidates[0]
    if set(candidate) == {"result"}:
        raise HostEvidenceValidationError((
            f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
        ))
    if host_fields.intersection(candidate):
        raise HostEvidenceValidationError((
            f"WORKER_NATIVE_RESULT_HOST_FIELDS:{worker_id}",
        ))
    artifact_like = required.intersection(candidate)
    if artifact_like:
        candidate_keys = set(candidate)
        if candidate_keys != required and candidate_keys != envelope_identity:
            raise HostEvidenceValidationError((
                f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
            ))
        if (
            candidate.get("worker_id") != worker_id
            or not isinstance(candidate.get("status"), str)
            or _canonical_worker_business_status(candidate.get("status"))
            != _canonical_worker_business_status(status)
            or not isinstance(candidate.get("payload"), dict)
            or (
                candidate_keys == required
                and not isinstance(candidate.get("summary"), str)
            )
        ):
            raise HostEvidenceValidationError((
                f"WORKER_NATIVE_RESULT_INVALID:{worker_id}",
            ))
        normalized = dict(candidate)
        # summary is audit metadata, not Worker business output. Some native
        # hosts return the strict identity/status/payload envelope without it;
        # normalize that shape once here instead of making the Coordinator
        # invent business facts or rejecting an otherwise valid result.
        normalized.setdefault("summary", "native_worker_result")
        return normalized

    # Native Agent 的结构化业务 JSON 是 payload；envelope 字段由本次
    # Host 调用的 Action/原生状态绑定，不能由文本自己声明。
    return {
        "worker_id": worker_id,
        "status": status,
        "payload": dict(candidate),
        "summary": "native_worker_result",
    }


@dataclass(frozen=True, slots=True)
class NativeWorkerOutcome:
    worker_id: str
    native_worker_handle: str
    status: str
    payload: dict[str, Any]
    summary: str
    actual_model: str
    isolation_evidence: str | None = None
    execution_generation: int | None = None
    fencing_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.execution_generation is None:
            value.pop("execution_generation")
        if self.fencing_token is None:
            value.pop("fencing_token")
        return value


def can_replace_retryable_outcome(
    previous: NativeWorkerOutcome,
    current: NativeWorkerOutcome,
) -> bool:
    """判断同一 Action 的新回写是否可以替换旧的可重试事实。"""

    retryable_statuses = {
        "failed",
        "cancelled",
        "timeout",
        "timed_out",
        "errored",
    }
    # Host Driver 可能先按 ``unreported`` 回写失败事实，随后在同一
    # Action repair 中按 Action 模板的 ``unknown`` 哨兵再次提交。两者都
    # 表示“模型未报告”，不是新的 Worker 执行；只要 native identity、
    # generation、fence、业务结果和隔离证据完全一致，就应保持幂等。
    same_generation_placeholder_repair = (
        previous.worker_id == current.worker_id
        and previous.native_worker_handle == current.native_worker_handle
        and previous.status == current.status
        and previous.payload == current.payload
        and previous.summary == current.summary
        and previous.execution_generation == current.execution_generation
        and previous.fencing_token == current.fencing_token
        and previous.isolation_evidence == current.isolation_evidence
        and previous.actual_model in {"unknown", "unreported"}
        and current.actual_model in {"unknown", "unreported"}
    )
    return (
        same_generation_placeholder_repair
        or (
            previous.status in retryable_statuses
            and isinstance(previous.execution_generation, int)
            and not isinstance(previous.execution_generation, bool)
            and isinstance(current.execution_generation, int)
            and not isinstance(current.execution_generation, bool)
            and current.execution_generation > previous.execution_generation
        )
    )


def _outcomes_are_ready(
    *,
    action: Mapping[str, object],
    outcome_items: object,
    allowed_statuses: set[str],
) -> bool:
    """按同一值对象形状校验一组 Action-scoped Worker outcomes。"""

    if not isinstance(outcome_items, list):
        return False
    spawn = action.get("spawn")
    if not isinstance(spawn, Mapping):
        return False
    invocations = spawn.get("invocations")
    if not isinstance(invocations, list) or not invocations:
        return False
    expected_workers = {
        item.get("worker_id")
        for item in invocations
        if isinstance(item, Mapping) and isinstance(item.get("worker_id"), str)
    }
    if len(outcome_items) != len(expected_workers) or not expected_workers:
        return False
    parsed: dict[str, NativeWorkerOutcome] = {}
    for item in outcome_items:
        if not isinstance(item, Mapping):
            return False
        try:
            outcome = NativeWorkerOutcome(**dict(item))
        except (TypeError, ValueError):
            return False
        if (
            outcome.worker_id not in expected_workers
            or outcome.worker_id in parsed
            or outcome.status not in allowed_statuses
            or not isinstance(outcome.payload, dict)
            or not isinstance(outcome.summary, str)
            or not outcome.summary
            or not isinstance(outcome.actual_model, str)
            or not outcome.actual_model
            or _native_handle_is_missing(outcome.native_worker_handle)
            or not outcome.isolation_evidence
        ):
            return False
        parsed[outcome.worker_id] = outcome
    return set(parsed) == expected_workers


def native_outcomes_are_ready(
    *,
    action: Mapping[str, object],
    outcome_items: object,
) -> bool:
    """只把完整的 completed outcomes 视为可恢复。"""

    return _outcomes_are_ready(
        action=action,
        outcome_items=outcome_items,
        allowed_statuses={"completed"},
    )


def worker_failure_outcomes_are_ready(
    *,
    action: Mapping[str, object],
    outcome_items: object,
) -> bool:
    """判断共享 outcomes 是否已形成完整的 Worker 失败事实。"""

    return _outcomes_are_ready(
        action=action,
        outcome_items=outcome_items,
        allowed_statuses={"failed", "cancelled", "timeout", "timed_out", "errored"},
    )


def _resolve_worker_execution_binding(
    action: Mapping[str, Any],
    template: Mapping[str, Any] | None,
    worker_id: str,
) -> tuple[int | None, str | None]:
    """解析并校验 Action 顶层与宿主 Worker 模板的同一代际绑定。"""

    action_generation = action.get("execution_generation")
    action_fence = action.get("fencing_token")
    template_generation = template.get("execution_generation") if template else None
    template_fence = template.get("fencing_token") if template else None
    has_action_binding = action_generation is not None or action_fence is not None
    if has_action_binding:
        if (
            not isinstance(action_generation, int)
            or isinstance(action_generation, bool)
            or action_generation < 1
            or not isinstance(action_fence, str)
            or len(action_fence) != 64
        ):
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
            )
        # Action 级 fence 与 Worker 级 fence 是两个不同作用域：前者绑定
        # 宿主会话，后者还包含 worker_id。两者不能直接比较，但都必须
        # 与同一个 execution_generation 对齐。
        if template is None:
            # 旧的宿主视图可能没有 workers 模板；此时不把 Action 级
            # lease 伪装成 Worker 级交接，避免同一兼容失败被误判为新代。
            return None, None
        if template_generation != action_generation:
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_MISMATCH:{worker_id}",)
            )
        if template_fence is None:
            return action_generation, None
        if not isinstance(template_fence, str) or len(template_fence) != 64:
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
            )
        return action_generation, template_fence
    if template_generation is None and template_fence is None:
        return None, None
    if (
        not isinstance(template_generation, int)
        or isinstance(template_generation, bool)
        or template_generation < 1
        or not isinstance(template_fence, str)
        or len(template_fence) != 64
    ):
        raise HostEvidenceValidationError(
            (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
        )
    return template_generation, template_fence


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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """原样原子写入宿主回包，不对 native envelope 做二次序列化。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


__all__ = [
    "HostEvidenceValidationError",
    "NativeWorkerOutcome",
    "WorkerOutcomeCollectionError",
    "_atomic_write_bytes",
    "_atomic_write_json",
    "_business_payload_reports_test_failure",
    "_canonical_bytes",
    "_canonical_worker_business_status",
    "_native_business_artifact",
    "_native_handle_is_missing",
    "_resolve_worker_execution_binding",
    "native_outcomes_are_ready",
    "worker_failure_outcomes_are_ready",
]
