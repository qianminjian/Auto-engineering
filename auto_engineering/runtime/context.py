"""TaskContext — runtime 层任务上下文.

参考 AutoGen MessageContext(精简版).
设计:Context 是 Agent.execute 的输入,聚合 state + 当前 Task 元信息.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from auto_engineering.engine.state import LoopState


@dataclass
class TaskContext:
    """Agent 执行时的上下文. Agent.execute(task, ctx) 接收.

    字段:
        state         — 共享 LoopState(引用,不 copy)
        requirement   — 原始需求文本(冗余于 state.requirement,便于访问)
        current_stage — 当前 Stage.name(冗余于 state.current_stage)
        inputs        — 从 Task.input_channels 提取的 channel 值 dict
        outputs       — 准备写入 state 的 outputs(暂存,execute 返回后 apply)
    """

    state: LoopState
    requirement: str
    current_stage: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
