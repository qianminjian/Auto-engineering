"""宿主原生输出中的 usage/cost 事实解析。

该模块只读取宿主已经产生的 ``stream-json`` 结果，不估算、不从自然语言
摘要猜测成本，也不把结果内容写回 Loop 状态。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class HostUsageAttestationError(ValueError):
    """宿主 usage 回包缺失或不满足机器合同。"""


@dataclass(frozen=True, slots=True)
class HostUsageAttestation:
    """一次宿主进程的最终 usage 事实。"""

    cost_usd: float
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    source: str = "claude-cli-result"


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HostUsageAttestationError(f"HOST_USAGE_FIELD_INVALID:{field}")
    return value


def _result_usage(payload: dict[str, Any]) -> HostUsageAttestation | None:
    cost = payload.get("total_cost_usd")
    usage = payload.get("usage")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        return None
    if not isinstance(usage, dict):
        return None
    required_fields = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    )
    if any(field not in usage for field in required_fields):
        return None
    return HostUsageAttestation(
        cost_usd=float(cost),
        input_tokens=_non_negative_int(usage.get("input_tokens"), "input_tokens"),
        cache_read_tokens=_non_negative_int(
            usage.get("cache_read_input_tokens"), "cache_read_input_tokens"
        ),
        cache_write_tokens=_non_negative_int(
            usage.get("cache_creation_input_tokens"),
            "cache_creation_input_tokens",
        ),
        output_tokens=_non_negative_int(usage.get("output_tokens"), "output_tokens"),
    )


def read_claude_stream_usage(path: Path) -> HostUsageAttestation:
    """读取 Claude ``--output-format stream-json`` 的最终结果 usage。

    stream 中可能包含多个中间事件；最后一个带有完整 ``total_cost_usd`` 与
    usage 的结果对象是唯一可接受的成本事实。JSON 解析失败的单行允许跳过，
    但最终没有完整结果时必须失败闭环。
    """

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise HostUsageAttestationError("CLAUDE_USAGE_ATTESTATION_UNREADABLE") from exc
    found: HostUsageAttestation | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        candidate = _result_usage(payload)
        if candidate is not None:
            found = candidate
    if found is None:
        raise HostUsageAttestationError("CLAUDE_COST_EVIDENCE_MISSING")
    return found


__all__ = [
    "HostUsageAttestation",
    "HostUsageAttestationError",
    "read_claude_stream_usage",
]
