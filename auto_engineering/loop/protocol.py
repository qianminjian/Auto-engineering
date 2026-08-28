"""跨宿主 Action/Result Protocol Envelope v1.1。

本模块只处理稳定协议元数据、基础校验和规范化摘要；stage 业务字段仍由
``actions.RESULT_SCHEMA`` 与各阶段处理器负责。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator

from auto_engineering.loop.execution_control import (
    ExecutionControl,
    control_for_action,
)

SCHEMA_VERSION = "1.1"


class ProtocolErrorCode(StrEnum):
    """跨宿主可稳定判断的协议错误码。"""

    INVALID_ENVELOPE = "INVALID_ENVELOPE"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    RESULT_CONFLICT = "RESULT_CONFLICT"
    ACTION_NOT_ACTIVE = "ACTION_NOT_ACTIVE"


class ProtocolValidationError(ValueError):
    """协议 envelope 不合法。"""

    def __init__(self, code: ProtocolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProtocolEnvelope:
    """Action/Result 共用的不可变协议头。"""

    schema_version: str
    message_type: str
    message_id: str
    thread_id: str
    tick: int
    stage: str | None
    causation_id: str | None
    correlation_id: str
    extensions: Mapping[str, Any]


@dataclass(frozen=True)
class ActionEnvelope(ProtocolEnvelope):
    """Core 发给宿主的 Action envelope。"""


@dataclass(frozen=True)
class ResultEnvelope(ProtocolEnvelope):
    """宿主回给 Core 的 Result envelope。"""


_COMMON_REQUIRED = (
    "schema_version",
    "message_type",
    "message_id",
    "thread_id",
    "tick",
    "stage",
    "correlation_id",
    "extensions",
)
_RESULT_SCHEMA = json.loads(
    Path(__file__).with_name("stage-result.schema.json").read_text(encoding="utf-8")
)
_ACTION_SCHEMA = json.loads(
    Path(__file__).with_name("action.schema.json").read_text(encoding="utf-8")
)
_ACTION_VALIDATOR = Draft202012Validator(_ACTION_SCHEMA)
_RESULT_ALLOWED_FIELDS = frozenset(_RESULT_SCHEMA["properties"])


def action_envelope(
    payload: Mapping[str, Any],
    *,
    thread_id: str | None = None,
    tick: int | None = None,
    stage: str | None = None,
    causation_id: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """为现有 Action payload 添加 v1.1 协议头。

    调用方显式参数优先；未提供时从 payload 读取。``stage=None`` 对终态和错误
    Action 是合法值。
    """

    resolved_thread = thread_id if thread_id is not None else payload.get("thread_id")
    resolved_tick = tick if tick is not None else payload.get("tick")
    resolved_stage = stage if stage is not None else payload.get("stage")
    if not isinstance(resolved_thread, str) or not resolved_thread:
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Action 缺少有效 thread_id",
        )
    if not isinstance(resolved_tick, int) or isinstance(resolved_tick, bool):
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Action 缺少有效 tick",
        )

    extensions = dict(payload.get("extensions") or {})
    ae_extension = dict(extensions.get("ae") or {})
    raw_control = ae_extension.get("execution_control")
    if raw_control is None:
        ae_extension["execution_control"] = control_for_action(payload).to_dict()
    elif isinstance(raw_control, Mapping):
        parsed_control = ExecutionControl.from_dict(raw_control)
        expected_control = control_for_action(payload)
        if parsed_control != expected_control:
            raise ProtocolValidationError(
                ProtocolErrorCode.INVALID_ENVELOPE,
                "Action execution_control 与 Action 语义不一致",
            )
    else:
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Action execution_control 必须为 object",
        )
    extensions["ae"] = ae_extension

    envelope: dict[str, Any] = {
        **payload,
        "schema_version": SCHEMA_VERSION,
        "message_type": "action",
        "message_id": message_id or str(uuid4()),
        "thread_id": resolved_thread,
        "tick": resolved_tick,
        "stage": resolved_stage,
        "correlation_id": resolved_thread,
        "extensions": extensions,
    }
    if causation_id is not None:
        envelope["causation_id"] = causation_id
    return envelope


def validate_action_envelope(action: Mapping[str, Any]) -> None:
    """按 v1.1 SSOT 校验 Core 输出；任何漂移都在持久化前 fail-closed。"""
    errors = sorted(_ACTION_VALIDATOR.iter_errors(dict(action)), key=lambda item: list(item.path))
    if errors:
        detail = "; ".join(error.message for error in errors[:3])
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            f"Action 不符合 v1.1 schema: {detail}",
        )


def validate_result_envelope(result: Mapping[str, Any]) -> ResultEnvelope:
    """校验原生 v1.1 Result 的公共协议头。"""

    missing = [field for field in (*_COMMON_REQUIRED, "causation_id") if field not in result]
    if missing:
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            f"Result 缺少协议字段: {', '.join(missing)}",
        )
    if result.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolValidationError(
            ProtocolErrorCode.SCHEMA_VERSION_UNSUPPORTED,
            f"不支持 schema_version={result.get('schema_version')!r}",
        )
    if result.get("message_type") != "result":
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Result message_type 必须为 'result'",
        )
    for field in ("message_id", "thread_id", "causation_id", "correlation_id"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise ProtocolValidationError(
                ProtocolErrorCode.INVALID_ENVELOPE,
                f"Result 字段 {field} 必须为非空字符串",
            )
    tick = result.get("tick")
    if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Result tick 必须为非负整数",
        )
    extensions = result.get("extensions")
    if not isinstance(extensions, Mapping):
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Result extensions 必须为 object",
        )
    stage = result.get("stage")
    if stage is not None and not isinstance(stage, str):
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            "Result stage 必须为字符串或 null",
        )
    unexpected = sorted(set(result) - _RESULT_ALLOWED_FIELDS)
    if unexpected:
        raise ProtocolValidationError(
            ProtocolErrorCode.INVALID_ENVELOPE,
            f"Result 含未知顶层字段: {', '.join(unexpected)}",
        )
    return ResultEnvelope(
        schema_version=SCHEMA_VERSION,
        message_type="result",
        message_id=result["message_id"],
        thread_id=result["thread_id"],
        tick=tick,
        stage=stage,
        causation_id=result["causation_id"],
        correlation_id=result["correlation_id"],
        extensions=dict(extensions),
    )


def payload_digest(message: Mapping[str, Any]) -> str:
    """计算语义 payload 摘要；忽略每次传输可变化的 ``message_id``。"""

    normalized = {key: value for key, value in message.items() if key != "message_id"}
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
