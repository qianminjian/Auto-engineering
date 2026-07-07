"""Output schema derivation — 从 expected_output 文本推导 JSON Schema.

从 loop/orchestrator.py 提取 (v5.4 审计 A5).
"""

from __future__ import annotations

import json
import logging
import re

__all__ = ["derive_output_schema"]

_logger = logging.getLogger("ae.agents.schema")


def derive_output_schema(expected_output: str) -> dict | None:
    """从 expected_output 文本推导 output_schema.

    优先尝试 JSON 解析 (如 expected_output 本身是 JSON 示例),
    否则用正则提取 key 名. 无法推导时返回 None.
    """
    brace_start = expected_output.find("{")
    if brace_start == -1:
        return None
    brace_end = expected_output.rfind("}")
    if brace_end <= brace_start:
        return None

    json_candidate = expected_output[brace_start:brace_end + 1]
    try:
        parsed = json.loads(json_candidate)
        if isinstance(parsed, dict) and parsed:
            return _dict_to_schema(parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    keys = re.findall(r'"(\w+)"\s*:', json_candidate)
    if not keys:
        return None
    _logger.debug("derive_output_schema: regex derivation (non-JSON), keys=%s", keys)
    properties = {k: {"type": "string"} for k in keys}
    return {"type": "object", "properties": properties, "required": keys}


def _dict_to_schema(d: dict) -> dict:
    """将示例 dict 转为 JSON Schema (推断类型)."""
    type_map = {bool: "boolean", int: "integer", float: "number", str: "string", list: "array", dict: "object"}
    properties = {}
    for k, v in d.items():
        t = type_map.get(type(v), "string")
        properties[k] = {"type": t}
    return {"type": "object", "properties": properties, "required": list(d.keys())}
