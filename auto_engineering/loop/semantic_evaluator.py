"""v2.3 Phase J — LLM 语义评估 (第 4 级收敛判定).

设计来源:
    - Phase 1 审计 P1.6: Phase B 实现 Orchestrator 接受
      semantic_evaluator: Callable[[RoundResult], Awaitable[bool]],
      但生产环境无内置 LLM evaluator, 用户需自己写. 第 4 级
      语义收敛永远不触发.
    - v2.3 Phase J: 内置 ClaudeSemanticEvaluator, 接 Claude API
      真判"本轮产出满足需求". OrchestratorConfig 默认配置
      (有 API key 时).
    - 借鉴 LangGraph ConditionalEdge: LLM 评估下一步路由.

设计决策:
    - 协议: `async (round_result: RoundResult) -> bool` —
      与 OrchestratorConfig.semantic_evaluator 类型一致.
    - 无 API key: 默认返回 True (不阻止, 让其他 Gate 决定),
      graceful degradation 行为.
    - JSON 解析失败: 默认返回 False (保守, 阻止停止, 避免
      "假阳性停止").
    - Prompt 构造: 用 requirement + 本轮 outcomes + gate_results,
      让 Claude 评估 "本轮产出是否满足需求".
    - 借鉴 LangGraph ConditionalEdge: LLM-based routing 决策.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from auto_engineering.llm.anthropic_provider import AnthropicProvider

if TYPE_CHECKING:
    from auto_engineering.loop.round import RoundResult


@dataclass
class ClaudeSemanticEvaluator:
    """用 Claude API 评估本轮产出是否满足需求.

    Attributes:
        model: 调用的模型名 (默认 "claude-haiku-4-5")
        prompt_template: 评估 prompt 模板, 接受 requirement / summary /
            gate_results 三个占位符
        max_tokens: Claude 响应最大 token 数 (默认 256, JSON 响应足够)
        temperature: Claude 采样温度 (默认 0.0, 确定性评估)

    Note:
        - 协议: 
        - JSON 解析失败: 返回 False (保守)
    """

    model: str = "claude-haiku-4-5"
    prompt_template: str = (
        "判断本轮产出是否满足需求.\n"
        "需求: {requirement}\n"
        "本轮结果: {summary}\n"
        "Gate 结果: {gate_results}\n"
        "请回应严格 JSON: {{\"satisfied\": bool, \"reason\": str}}"
    )
    max_tokens: int = 256
    temperature: float = 0.0
    api_key: str | None = None
    # 2026-07-05 修复 (对标审计 P0-4): 注入 requirement 避免 "(see task outcomes)"
    # 占位符. 参考 LangGraph conditional edge: 路由决策需要完整状态上下文.
    requirement: str = ""
    _provider: AnthropicProvider | None = None

    def __post_init__(self) -> None:
        """P1-E: 预创建 AnthropicProvider, 多次 __call__ 复用.

        SDK 自动从 env 读 key (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN).
        测试可通过 api_key="..." 显式传入覆盖.
        """
        # 预创建 provider (api_key=None 时 SDK 自动从 env 读)
        self._provider = AnthropicProvider(api_key=self.api_key)

    def _has_api_key(self) -> bool:
        """检测是否有 API key (用于 graceful degradation 决策).

        2026-07-04 修复 (v5.0 深度审计 P0-T-02): 之前 __call__ 无条件 return True,
        导致 test_satisfied_true_returns_true 等 5 个测试失败 (因为 mock Claude
        API 永远不被调). 现区分"无 key" (graceful True) 与 "有 key" (调 API).
        """
        if self.api_key:
            return True
        return bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    async def __call__(self, round_result: RoundResult) -> bool:
        """评估本轮产出是否满足需求.

        Args:
            round_result: 本轮的 RoundResult (含 outcomes / history / gate_results)

        Returns:
            bool: True = 满足需求, False = 未满足
            JSON 解析失败时: False (保守)
        """
        # Graceful degradation: 无 API key → True (不阻止, 让其他 Gate 决定)
        if not self._has_api_key():
            return True

        # 1. 构造评估 prompt
        prompt = self._build_prompt(round_result)

        # 2. 调 Claude API
        try:
            response = await self._call_claude(prompt)
        except Exception:
            # API 调用失败 → 保守返回 False (不阻止停止, 继续运行)
            return False

        # 3. 解析 JSON 回应
        return self._parse_satisfied(response)

    def _build_prompt(self, round_result: RoundResult) -> str:
        """构造评估 prompt — 包含 requirement / summary / gate_results.

        Args:
            round_result: 本轮 RoundResult

        Returns:
            格式化的 prompt 字符串
        """
        # requirement 从 round_result.history[0] 读 (如果可得)
        # history 元素是 RoundHistory, 不含 requirement 字段
        # 用 outcomes + gate_results 构造 summary
        summary_parts = []
        for outcome in round_result.outcomes:
            summary_parts.append(f"{outcome.task_id}={outcome.status}")
        summary = (
            f"outcomes: [{', '.join(summary_parts)}]"
            if summary_parts
            else "outcomes: []"
        )

        # gate_results 从 history[0] 读 (RoundHistory 字段)
        gate_results_str = "{}"
        if round_result.history:
            latest = round_result.history[0]
            # gate_results 是 dict[gate_name, Verdict], 转 bool
            gate_status = {
                name: getattr(verdict, "passed", False)
                for name, verdict in (latest.gate_results or {}).items()
            }
            gate_results_str = str(gate_status)

        return self.prompt_template.format(
            requirement=self.requirement or "(no requirement provided)",
            summary=summary,
            gate_results=gate_results_str,
        )

    async def _call_claude(self, prompt: str):
        """调 Claude API (异步包装, 不阻塞 event loop).

        P1-E: 复用 self._provider (避免每轮 new instance + SDK client 重连).

        Args:
            prompt: 评估 prompt

        Returns:
            LLMResponse (AnthropicProvider.create_message 返回)

        Note:
            AnthropicProvider.create_message 是同步方法. 用 asyncio.to_thread 包
            后才不阻塞 event loop. 直接 await 同步方法在 Python 3.10+ 抛 TypeError.
        """
        import asyncio

        response = await asyncio.to_thread(
            self._provider.create_message,
            model=self.model,
            max_tokens=self.max_tokens,
            system="你是代码审查员, 判断本轮产出是否满足需求.",
            messages=[{"role": "user", "content": prompt}],
        )
        return response

    def _parse_satisfied(self, response) -> bool:
        """从 Claude 响应解析 satisfied 字段.

        Args:
            response: LLMResponse 对象 (有 .content 属性)

        Returns:
            bool: 解析成功 → 数据值, 解析失败 → False (保守)
        """
        try:
            content = response.content[0].text if response.content else ""
            data = json.loads(content)
            return bool(data.get("satisfied", False))
        except (json.JSONDecodeError, KeyError, IndexError, AttributeError, TypeError):
            # 任何解析错误 → False (保守, 不误判停止)
            return False


# ============================================================
# 公开 API
# ============================================================

__all__ = [
    "ClaudeSemanticEvaluator",
]


# Type alias (与 OrchestratorConfig.semantic_evaluator 一致)
SemanticEvaluator = Callable[["RoundResult"], Awaitable[bool]]
