"""BaseAgent — Agent 基类. Phase 0.1 dev-loop 真接.

设计要点:
    - LLM 调用循环(while turn < max_tool_calls + 1)
    - 工具循环:stop_reason=='tool_use' → 执行 tool → 追加 tool_result → 续调 LLM
    - 输出解析:agents/parser.py 双层防御
    - output_schema 注入 system prompt(LLM 知道 JSON 结构)
    - cancellation 协作(每次 LLM 调用前检查)
    - Agent Protocol 兼容(runtime/runtime.Agent)

借鉴:
    - AutoGen _base_agent.py:60-254 (BaseAgent lifecycle)
    - CrewAI Task.handle_partial_json (output 解析)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import AnthropicProvider
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task, TaskResult
from auto_engineering.tools.base import BaseTool


@dataclass
class BaseAgent:
    """Agent 基类 — LLM 调用 + 工具循环 + 输出解析.

    Attributes:
        llm             — AnthropicProvider(LLM 调用封装)
        system_prompt   — system 消息(角色定义 + 行为约束)
        tools           — 可用工具列表(BaseTool 实例)
        max_tool_calls  — 工具循环上限(防止 LLM 死循环, 默认 10)
        model           — Claude 模型名
        max_tokens      — 单次响应最大 token
    """

    llm: AnthropicProvider
    system_prompt: str
    tools: list[BaseTool] = field(default_factory=list)
    max_tool_calls: int = 10
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096

    async def execute(
        self,
        task: Task,
        ctx: TaskContext,
        cancellation: Any = None,
        token_tracker: Any = None,
    ) -> TaskResult:
        """执行 task: LLM 调用循环 + 工具循环 + 输出解析.

        流程:
            1. messages = [{role:user, content:task.description}]
            2. while turn < max_tool_calls + 1:
                a. cancellation.check()(已取消则抛)
                b. llm.create_message(system, messages, tools)
                c. if stop_reason=='tool_use' and tool_use_blocks:
                    - 执行所有 tool → 追加 tool_result 到 messages
                    - continue
                d. else:
                    - 解析 content 为 dict
                    - 返回 TaskResult
            3. 超 max_tool_calls → 抛 MAX_TOOL_CALLS_EXCEEDED

        Args:
            task         — Task dataclass
            ctx          — TaskContext
            cancellation — CancellationToken(可选)
            token_tracker — TokenTracker(可选). 调用后累加 LLMUsage.超 max_tokens 抛 BUDGET_EXCEEDED.

        Returns:
            TaskResult(values/raw_response/tool_calls/task_id/agent_type)

        Raises:
            AEError(INVALID_AGENT_OUTPUT)    — LLM 输出无 JSON
            AEError(MAX_TOOL_CALLS_EXCEEDED) — 工具循环超限
            AEError(BUDGET_EXCEEDED)          — token 超限
            Exception via cancellation.check() — 用户取消
        """
        messages: list[dict] = [
            {"role": "user", "content": task.description}
        ]
        tool_map = {t.name: t for t in self.tools}
        tool_calls_log: list[dict] = []

        for _ in range(self.max_tool_calls + 1):
            if cancellation is not None:
                cancellation.check()

            response = await self.llm.create_message(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._build_system_prompt(task),
                messages=messages,
                tools=[t.to_schema() for t in self.tools] if self.tools else None,
            )

            # Phase 1.3: TokenTracker 累加 + 超阈值抛错
            if token_tracker is not None:
                token_tracker.add(response)  # 超 max_tokens 抛 BUDGET_EXCEEDED

            if response.stop_reason == "tool_use" and response.tool_use_blocks:
                tool_results: list[dict] = []
                for tool_use in response.tool_use_blocks:
                    tool_name = tool_use["name"]
                    tool_input = tool_use.get("input", {}) or {}
                    tool_id = tool_use.get("id", "")
                    tool_calls_log.append({"name": tool_name, "input": tool_input})

                    if tool_name not in tool_map:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Error: tool '{tool_name}' not found",
                            "is_error": True,
                        })
                        continue

                    try:
                        result = await tool_map[tool_name].execute(**tool_input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result.content,
                            "is_error": not result.success,
                        })
                    except Exception as exc:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        })

                messages.append({"role": "assistant", "content": response.tool_use_blocks})
                messages.append({"role": "user", "content": tool_results})
                continue

            values = self._parse_final_response(response.content)
            return TaskResult(
                task_id=task.id,
                values=values,
                raw_response=response,
                tool_calls=tool_calls_log,
                agent_type=self.__class__.__name__,
            )

        raise AEError(
            ErrorCode.MAX_TOOL_CALLS_EXCEEDED,
            f"Agent '{self.__class__.__name__}' exceeded {self.max_tool_calls} tool calls",
        )

    def _build_system_prompt(self, task: Task) -> str:
        """构造 system prompt. 有 output_schema 时注入 schema 约束."""
        system = self.system_prompt
        if task.output_schema:
            schema_str = json.dumps(task.output_schema, indent=2, ensure_ascii=False)
            system += (
                "\n\n## Output Schema\n"
                "你必须输出符合以下 JSON Schema 的 JSON"
                "(用 markdown ```json``` fence 或纯文本):\n"
                f"```json\n{schema_str}\n```"
            )
        return system

    def _parse_final_response(self, content: str) -> dict:
        """解析 LLM 最终响应为 dict. 双层防御(直接 JSON / fence / 内联块).

        解析失败 → 抛 AEError(INVALID_AGENT_OUTPUT)
        """
        from auto_engineering.agents.parser import parse_agent_output

        parsed = parse_agent_output(content)
        if parsed is None:
            raise AEError(
                ErrorCode.INVALID_AGENT_OUTPUT,
                f"Failed to parse LLM output as JSON: {content[:200]}",
            )
        return parsed
