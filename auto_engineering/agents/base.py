"""BaseAgent — Agent 基类. v2.0 dev-loop 真接.

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

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from auto_engineering.agents.authz import authz_check
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
        contract_gate   — v2.0 multi-agent 契约确认钩子(Phase 06 Task 5.2).
                          签名: Callable[[Task, TaskContext], bool].
                          默认 None = auto-approve,不阻塞 execute().
                          返回 False 时抛 AEError(CONTRACT_REJECTED), LLM 不被调用.
    """

    llm: AnthropicProvider
    system_prompt: str
    role: str = "BaseAgent"  # P1-A: 工厂返回时覆盖 (architect/developer/critic)
    tools: list[BaseTool] = field(default_factory=list)
    max_tool_calls: int = 10
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    contract_gate: Callable[[Task, TaskContext], bool] | None = None

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
            token_tracker — TokenTracker(可选). 超 max_tokens 抛 BUDGET_EXCEEDED.

        Returns:
            TaskResult(values/raw_response/tool_calls/task_id/agent_type)

        Raises:
            AEError(INVALID_AGENT_OUTPUT)    — LLM 输出无 JSON
            AEError(MAX_TOOL_CALLS_EXCEEDED) — 工具循环超限
            AEError(BUDGET_EXCEEDED)          — token 超限
            Exception via cancellation.check() — 用户取消
        """
        messages: list[dict] = [{"role": "user", "content": task.description}]
        # P0.1: 优先用 task.tools（AgentRuntime 已解析为 BaseTool 实例），降级用 self.tools
        effective_tools = task.tools if task.tools else self.tools
        tool_map = {t.name: t for t in effective_tools}
        tool_calls_log: list[dict] = []

        # Phase 06 Task 5.2: 契约确认 gate（two-green gate 的第一绿）
        # 默认 None = auto-approve；用户/CI 可注入交互式确认 gate.
        # 返回 False 时抛 CONTRACT_REJECTED,LLM 不被调用.
        if self.contract_gate is not None and not self.contract_gate(task, ctx):
            raise AEError(
                ErrorCode.CONTRACT_REJECTED,
                f"Contract gate rejected task '{task.id}' for agent "
                f"'{self.__class__.__name__}'",
            )

        for _ in range(self.max_tool_calls + 1):
            if cancellation is not None:
                cancellation.check()

            # P1.3: LLM 异常分类
            # D-P0-1 (deep audit): llm.create_message 是同步函数. 直接 await
            # 会让 asyncio.gather 假象 — 所有并行 agent 串行化等待 LLM.
            # 用 asyncio.to_thread 把同步 LLM 调用移到 thread pool, 真正并行.
            # 同模式: semantic_evaluator.py:164 已正确实现.
            try:
                response = await asyncio.to_thread(
                    self.llm.create_message,
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self._build_system_prompt(task),
                    messages=messages,
                    tools=[t.to_schema() for t in effective_tools] if effective_tools else None,
                )
            except Exception as exc:  # 详见下面特定异常映射
                raise self._map_llm_exception(exc) from exc

            # v2.0: TokenTracker 累加 + 超阈值抛错
            if token_tracker is not None:
                token_tracker.add(response)  # 超 max_tokens 抛 BUDGET_EXCEEDED

            if response.stop_reason == "tool_use" and response.tool_use_blocks:
                tool_results: list[dict] = []
                for tool_use in response.tool_use_blocks:
                    tool_name = tool_use["name"]
                    tool_input = tool_use.get("input", {}) or {}
                    tool_id = tool_use.get("id", "")
                    tool_calls_log.append({"name": tool_name, "input": tool_input})

                    # v5.0 §B4.4 step 3b: 未注册工具 → error tool_result JSON
                    if tool_name not in tool_map:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": json.dumps({"error": f"unknown tool: {tool_name}"}),
                                "is_error": True,
                            }
                        )
                        continue

                    # v5.0 §B4.4 step 3b: 未授权工具 → error tool_result JSON
                    # R-23: 授权失败降级为可观察错误,不抛异常
                    if not authz_check(self.role, tool_name):
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": json.dumps(
                                    {"error": f"tool {tool_name} not authorized for {self.role}"}
                                ),
                                "is_error": True,
                            }
                        )
                        continue

                    # P1.7: 工具参数 schema 校验
                    tool = tool_map[tool_name]
                    self._validate_tool_input(tool, tool_input, tool_name)

                    try:
                        result = await tool.execute(**tool_input)
                        # P1.4: error_code 存在 → 工具认定的业务错误,抛 AEError
                        if result.error_code is not None:
                            raise AEError(
                                ErrorCode.INVALID_AGENT_OUTPUT,
                                f"Tool '{tool_name}' error: {result.error}",
                            )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": result.content,
                                "is_error": not result.success,
                            }
                        )
                    except AEError:
                        raise  # 已分类的 AEError 透传
                    except Exception as exc:
                        # v5.0 §B4.4 step 3b: 工具异常 → error tool_result JSON
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": json.dumps({"error": str(exc)}),
                                "is_error": True,
                            }
                        )

                messages.append({"role": "assistant", "content": response.tool_use_blocks})
                messages.append({"role": "user", "content": tool_results})
                continue

            values = self._parse_final_response(response.content)
            return TaskResult(
                task_id=task.id,
                values=values,
                raw_response=response,
                tool_calls=tool_calls_log,
                agent_type=self.role,  # P1-A: role='architect'|'developer'|'critic'
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

    def _map_llm_exception(self, exc: Exception) -> AEError:
        """将 LLM SDK 异常映射为 AEError.

        P1.3: LLM 调用错误分类。使用 type(exc).__name__ 而非 isinstance
        (避免 mock 对象无法通过 isinstance 校验)。
            - APITimeoutError      → LLM_TIMEOUT
            - APIConnectionError   → LLM_NETWORK_ERROR
            - APIStatusError      → LLM_INVALID_RESPONSE
            - AuthenticationError → LLM_AUTH_ERROR
            - RateLimitError      → LLM_RATE_LIMIT
            - 其他                → LLM_UNKNOWN_ERROR
        """
        exc_name = type(exc).__name__
        if exc_name == "APITimeoutError":
            return AEError(ErrorCode.LLM_TIMEOUT, f"LLM timeout: {exc}")
        if exc_name == "APIConnectionError":
            return AEError(ErrorCode.LLM_NETWORK_ERROR, f"LLM connection error: {exc}")
        if exc_name == "APIStatusError":
            return AEError(ErrorCode.LLM_INVALID_RESPONSE, f"LLM API error: {exc}")
        if exc_name == "AuthenticationError":
            return AEError(ErrorCode.LLM_AUTH_ERROR, f"LLM auth error: {exc}")
        if exc_name == "RateLimitError":
            return AEError(ErrorCode.LLM_RATE_LIMIT, f"LLM rate limit: {exc}")
        return AEError(ErrorCode.LLM_UNKNOWN_ERROR, f"LLM error: {exc}")

    def _validate_tool_input(self, tool: BaseTool, tool_input: dict, tool_name: str) -> None:
        """P1.7: 校验 tool_input 符合 tool.parameters schema.

        规则:
        - 必填字段缺失 → 抛 INVALID_AGENT_OUTPUT
        - 类型错误(传 string 给 integer) → 抛 INVALID_AGENT_OUTPUT

        注意: LLM 可能传多余字段,这是正常的(Anthropic 默认允许 extras),不作为错误.
        """
        schema = tool.parameters
        if not schema:
            return  # 无 schema,跳过校验

        for param_name, param_spec in schema.items():
            if param_name not in tool_input:
                # 必填字段缺失
                if param_spec.get("required", True):
                    raise AEError(
                        ErrorCode.INVALID_AGENT_OUTPUT,
                        f"Tool '{tool_name}' missing required parameter: {param_name}",
                    )
                continue

            expected_type = param_spec.get("type", "string")
            actual = tool_input[param_name]
            if actual is None:
                continue
            # 类型校验(只做基础类型检查)
            if expected_type == "integer" and not isinstance(actual, int):
                raise AEError(
                    ErrorCode.INVALID_AGENT_OUTPUT,
                    f"Tool '{tool_name}' parameter '{param_name}' must be integer, "
                    f"got {type(actual).__name__}",
                )
            if expected_type == "boolean" and not isinstance(actual, bool):
                raise AEError(
                    ErrorCode.INVALID_AGENT_OUTPUT,
                    f"Tool '{tool_name}' parameter '{param_name}' must be boolean, "
                    f"got {type(actual).__name__}",
                )

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


# P1-A: 合并 3 Agent 类为 1 个. Agent 是 BaseAgent 的 alias, 旧名保留向后兼容.
Agent = BaseAgent
