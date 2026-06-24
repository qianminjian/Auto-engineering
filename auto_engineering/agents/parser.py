"""Agent output parser — 双层防御 (schema → regex fallback).

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 19.
来源: CrewAI utilities/converter.py:24-80.

Layer 1 (schema): 尝试直接 JSON 解析 + Pydantic schema 校验
Layer 2 (regex): 如果直接解析失败,提取 markdown ```json ... ``` 块或首个 {...} 块

返回:
- schema 模式: Pydantic model instance 或 None
- 无 schema: dict 或 None
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# markdown ```json ... ``` 块
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
# 任意位置首个 {...} 块（贪婪匹配跨行）
_JSON_INLINE_RE = re.compile(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", re.DOTALL)


def _try_parse_json(text: str) -> dict | None:
    """尝试从 text 中提取 JSON dict. 返回 dict 或 None."""
    if not text or not text.strip():
        return None
    # 1. 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. markdown fence
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # 3. 首个 {...} 块
    m = _JSON_INLINE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def parse_agent_output[T: BaseModel](
    text: str,
    schema: type[T] | None = None,
) -> T | dict | None:
    """解析 LLM 输出.

    Args:
        text: LLM 输出文本（可能含 markdown fence / 解释文字）
        schema: 可选 Pydantic model class,用于校验 + 类型化返回

    Returns:
        schema 模式: schema 实例 或 None（解析失败）
        无 schema: dict 或 None
    """
    parsed = _try_parse_json(text)
    if parsed is None:
        return None
    if schema is not None:
        try:
            return schema.model_validate(parsed)
        except ValidationError:
            return None
    return parsed