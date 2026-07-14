"""AnthropicProvider — LLM 调用封装.

设计参考: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 18.
封装 anthropic SDK,提供 LLMResponse/LLMUsage 数据类,统一接口给 Agent 调用.

v3.1 扩展 (v2.0 dev-loop 真接):
    - LLMResponse 加 stop_reason + tool_use_blocks(支持 BaseAgent 工具循环)
    - create_message 加 tools 参数 + 解析 SDK content blocks(text + tool_use)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import anthropic

_logger = logging.getLogger("ae.llm")


@dataclass
class LLMUsage:
    """Token 用量统计."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """LLM 调用结构化响应.

    字段:
        content          — text block 拼接的纯文本(text 类型)
        model            — 调用的模型名
        usage            — token 用量
        stop_reason      — SDK 返回的停止原因("end_turn" | "tool_use" | "max_tokens")
        tool_use_blocks  — tool_use 类型 block 解析结果(每个 dict 含 id/name/input)
    """

    content: str = ""
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    stop_reason: str = "end_turn"
    tool_use_blocks: list[dict] = field(default_factory=list)


class AnthropicProvider:
    """Anthropic Claude API 客户端封装.

    P0-4: 生产 retry 策略 — RateLimitError / APIConnectionError 重试.
    max_retries=0 表示不重试 (默认 3 次).
    v2.5 P2-D-4: 真实指数退避 (2^attempt 秒) — 之前 time.sleep(0) 在限流
    场景下瞬间失败 4 次浪费 budget. 测试环境用 _BACKOFF_FACTOR=0 旁路.
    v2.5 P2-D-6: close() / __enter__-__exit__ 显式释放 httpx 连接.
    """

    # 可重试异常类型 (anthropic SDK)
    # 2026-07-04 修复 (Bug 2 prismscan 集成): 不重试 AuthenticationError (401)
    # 因为 auth 错误是配置问题, 重试只会浪费 budget + 延迟失败.
    # 异常时显式抛出 (包含 status code + response body 前 200 字符, 供 orchestrator
    # / critic agent 诊断). 之前会被 RateLimitError 静默捕获, 导致空 verdict.
    _RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
    )

    # 测试环境可设为 0 跳过真实 sleep, 生产保持 1.0
    _BACKOFF_FACTOR: float = 1.0

    def __init__(
        self,
        api_key: str | None = None,
        client: anthropic.Anthropic | None = None,
        max_retries: int = 3,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            # 2026-07-04 修复 (Issue #5, 100 分): 显式传 api_key 当显式提供,
            # 避免 silent-drop. 否则调用方传 api_key="..." 实际没生效.
            # SDK 默认从 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN env 读.
            if api_key is not None:
                self._client = anthropic.Anthropic(api_key=api_key)
            else:
                self._client = anthropic.Anthropic()  # SDK 自动从 env 读 key
        self._max_retries = max_retries

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        """标准化消息 content 为 content-block 格式 (DeepSeek 兼容).

        DeepSeek Anthropic-compatible 端点要求 content 必须是
        [{type, text/tool_use_id, ...}] 格式, 不接受纯字符串 content.
        """
        normalized = []
        for msg in messages:
            content = msg.get("content")
            role = msg.get("role")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                normalized_blocks = []
                for block in content:
                    if isinstance(block, dict):
                        if "type" not in block:
                            # tool_use block 缺 type → 补充
                            if "name" in block and "input" in block:
                                block = {"type": "tool_use", **block}
                            # tool_result block 或 text block 缺 type
                            elif "tool_use_id" in block:
                                block = {"type": "tool_result", **block}
                            elif "text" in block:
                                block = {"type": "text", **block}
                        normalized_blocks.append(block)
                    elif isinstance(block, str):
                        normalized_blocks.append({"type": "text", "text": block})
                    else:
                        normalized_blocks.append(block)
                content = normalized_blocks
            normalized.append({"role": role, "content": content})
        return normalized

    def close(self) -> None:
        """显式关闭底层 httpx 连接 (v2.5 P2-D-6).

        Anthropic SDK 内部维护 httpx.Client, 进程长跑时连接不释放.
        长 dev-loop 跑完推荐调 close() / async with provider as _.
        """
        if hasattr(self._client, "close"):
            self._client.close()

    def __enter__(self) -> AnthropicProvider:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def create_message(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 Claude API.

        Args:
            model    — 模型名(例 "claude-sonnet-4-6")
            max_tokens — 最大输出 token
            system   — system prompt
            messages — 对话历史 [{"role": ..., "content": ...}]
            tools    — 可选,工具 schema 列表(Anthropic tool format)

        Returns:
            LLMResponse(content/model/usage/stop_reason/tool_use_blocks)

        Raises:
            anthropic.RateLimitError: 超过 max_retries 后仍未成功
            anthropic.APIConnectionError: 超过 max_retries 后仍未成功
            anthropic.APITimeoutError: 超过 max_retries 后仍未成功
            其他异常: 立即抛出, 不重试
        """
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self._normalize_messages(messages),
        }
        if tools:
            kwargs["tools"] = tools

        # P0-4: retry 策略 — RateLimitError / APIConnectionError / APITimeoutError
        # 总尝试次数 = 1 (原始) + max_retries
        # v2.5 P2-D-4: 真实指数退避 2^attempt 秒, 测试用 _BACKOFF_FACTOR=0
        import time
        for attempt in range(1, self._max_retries + 2):  # 1..max_retries+1
            try:
                response = self._client.messages.create(**kwargs)  # type: ignore[call-overload]  # SDK 严格 overload vs 动态 dict kwargs
                break  # 成功, 退出 retry loop
            except self._RETRYABLE_EXCEPTIONS as exc:
                if attempt > self._max_retries:
                    raise
                backoff = (2 ** (attempt - 1)) * self._BACKOFF_FACTOR
                _logger.warning(
                    "LLM 调用重试 %d/%d, 退避 %.1fs: %s",
                    attempt, self._max_retries, backoff, type(exc).__name__,
                )
                if backoff > 0:
                    time.sleep(backoff)

        content_text = ""
        tool_use_blocks: list[dict] = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_use_blocks.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return LLMResponse(
            content=content_text,
            model=response.model,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
            tool_use_blocks=tool_use_blocks,
        )
