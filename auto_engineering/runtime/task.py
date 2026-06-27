"""Task + TaskResult — runtime 层任务数据模型.

参考 CrewAI task.py:114-213 富 Task 模型(精简版,只保留 v1.0 必要字段).

设计要点:
    - Task 是 runtime 层抽象,Stage 是 graph 层抽象。两者字段重叠(v1.0),
      v2.0 可能拆分:Stage(graph 层)+ Task(runtime 层)。
    - Task.id 通常 == Stage.name(同一概念在 graph/runtime 两层表达)。
    - dataclass 而非 Pydantic:与 LoopState/Stage/Checkpoint 风格一致(YAGNI)。
    - Task/TaskResult 都是 mutable:运行时可调整。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """运行时任务数据模型. 对应 StageGraph.Stage 但在 runtime 层.

    字段:
        id              — 任务唯一标识(通常 == Stage.name)
        description     — 任务描述(给 Agent 看)
        expected_output — 期望产出描述(CrewAI 风格,提升 LLM 输出质量)
        output_schema   — JSON Schema 约束 LLM 输出结构
        tools           — 工具名列表(运行时由 ToolRegistry 解析)
        input_channels  — 从 LoopState 读哪些 channel
        output_channels — 写哪些 channel 到 LoopState
    """

    id: str
    description: str
    expected_output: str
    output_schema: dict | None = None
    tools: list[str] = field(default_factory=list)
    input_channels: list[str] = field(default_factory=list)
    output_channels: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    """任务执行结果.

    字段:
        task_id       — 对应 Task.id
        values        — 输出 dict(键对应 Task.output_channels)
        raw_response  — Agent 原始响应(LLM 文本,用于调试)
        tool_calls    — 工具调用记录(LLM 调用了哪些工具)
        agent_type    — 哪个 Agent 跑的(architect/developer/critic)
    """

    task_id: str
    values: dict[str, Any]
    raw_response: Any = None
    tool_calls: list[dict] = field(default_factory=list)
    agent_type: str = ""


# P1-B: 向后兼容 alias. 旧名 Task 仍可 import, AgentTask 是新推荐名.
AgentTask = Task
