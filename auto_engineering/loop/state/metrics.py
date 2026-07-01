"""指标快照 + 跨 Agent 信号.

MetricsSnapshot: Pydantic BaseModel, JSON 序列化指标存储.
Signal: dataclass, 跨 Agent 通信信号.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class Signal:
    """跨 Agent 信号 (Signal 流).

    Attributes:
        type: 信号类型 (e.g. "metric.update", "task.done", "round.complete")
        payload: 信号数据 (任意 JSON 可序列化值)
        source: 信号源 (可选, agent/task id)
    """

    type: str
    payload: Any
    source: str | None = None


class MetricsSnapshot(BaseModel):
    """指标快照 (CheckpointEnvelope.metrics).

    Attributes:
        values: 指标名 -> 值
    """

    model_config = {"arbitrary_types_allowed": True}

    values: dict[str, float | int] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> float | int | None:
        return self.values.get(key)

    def __setitem__(self, key: str, value: float | int) -> None:
        self.values[key] = value

    def get(self, key: str, default: float | int | None = None) -> float | int | None:
        return self.values.get(key, default)
