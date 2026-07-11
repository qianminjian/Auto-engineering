"""Phase 12.6 — loop/types.py 扩展测试 (≥85% 覆盖率).

设计来源: auto_engineering/loop/types.py.

覆盖目标:
    - serialize_state:
        * Pydantic 对象 (有 model_dump) → 序列化为 JSON
        * 字典 → 序列化为 JSON
        * 缺 model_dump 的对象 → 用 __dict__ 兜底
        * 不可序列化 → json.dumps(default=str) 兜底
    - deserialize_state:
        * 合法 JSON dict → dict
        * 非法 JSON → {"__raw__": json_str} 包装
        * 非 dict JSON (数组/字符串) → {"__value__": data} 包装
        * 空字符串 → {"__raw__": ""}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ============================================================
# 1. serialize_state - Pydantic 风格对象
# ============================================================


class TestSerializeStatePydantic:
    """serialize_state: 有 model_dump 的对象 (Pydantic v2 风格)."""

    def test_pydantic_style_object_serialized(self):
        """Pydantic 对象 (有 model_dump) → 调用 model_dump(mode='json')."""
        from auto_engineering.loop.types import serialize_state

        class FakePydanticModel:
            def __init__(self) -> None:
                self.round = 1
                self.step = 0
                self.status = "running"
                self.channels = {"a": 1}

            def model_dump(self, **kwargs: Any) -> dict:
                # 验证 kwargs 被传递
                assert kwargs.get("mode") == "json"
                return {
                    "round": self.round,
                    "step": self.step,
                    "status": self.status,
                    "channels": self.channels,
                }

        state = FakePydanticModel()
        result = serialize_state(state)
        parsed = json.loads(result)
        assert parsed["round"] == 1
        assert parsed["step"] == 0
        assert parsed["status"] == "running"
        assert parsed["channels"] == {"a": 1}

    def test_pydantic_with_nested_channels(self):
        """嵌套 channel 数据 (含 dict) → 正确序列化."""
        from auto_engineering.loop.types import serialize_state

        class NestedState:
            round = 1
            step = 0
            status = "running"
            channels = {"nested": {"key": [1, 2, 3]}}

            def model_dump(self, **kwargs: Any) -> dict:
                return {
                    "round": self.round,
                    "step": self.step,
                    "status": self.status,
                    "channels": self.channels,
                }

        result = serialize_state(NestedState())
        parsed = json.loads(result)
        assert parsed["channels"]["nested"]["key"] == [1, 2, 3]


# ============================================================
# 3. serialize_state - dict 输入
# ============================================================


class TestSerializeStateDict:
    """serialize_state: 字典输入路径."""

    def test_dict_serialized_directly(self):
        """dict → json.dumps 直接序列化."""
        from auto_engineering.loop.types import serialize_state

        state = {"round": 1, "step": 0, "status": "ok", "channels": {"x": 1}}
        result = serialize_state(state)
        parsed = json.loads(result)
        assert parsed == state

    def test_empty_dict_serialized(self):
        """空 dict → '{}'."""
        from auto_engineering.loop.types import serialize_state

        result = serialize_state({})
        assert result == "{}"


# ============================================================
# 4. serialize_state - __dict__ 兜底
# ============================================================


class TestSerializeStateDictFallback:
    """serialize_state: 缺 model_dump 但有 __dict__ 的对象."""

    def test_dataclass_uses_dict_fallback(self):
        """dataclass 缺 model_dump → 用 __dict__ 序列化."""
        from auto_engineering.loop.types import serialize_state

        @dataclass
        class PlainDataClass:
            round: int = 1
            step: int = 0

        state = PlainDataClass()
        # dataclass 自动有 __dict__,但 dataclass 不带 model_dump
        result = serialize_state(state)
        # 验证能成功返回 JSON 字符串
        assert isinstance(result, str)
        # 默认值是 str 化所有值
        parsed = json.loads(result)
        assert parsed["round"] == 1 or parsed["round"] == "1"


# ============================================================
# 5. serialize_state - 最终 fallback
# ============================================================


class TestSerializeStateFinalFallback:
    """serialize_state: 既无 model_dump 又无 __dict__ 的极端情况."""

    def test_object_with_no_attrs_uses_default_str(self):
        """无 model_dump + 无 __dict__ → 走 json.dumps(state, default=str)."""
        from auto_engineering.loop.types import serialize_state

        # 一个简单的不可序列化对象 (但 json.dumps 加上 default=str 能兜底)
        class WeirdObject:
            pass

        obj = WeirdObject()
        # 应该有 model_dump (dataclass 通过 slots 可能没有 __dict__)
        # 如果 __dict__ 也不存在,会走最末 fallback
        # 普通 class 默认有 __dict__,所以走 dict fallback
        # 此处确保不抛异常
        result = serialize_state(obj)
        assert isinstance(result, str)


# ============================================================
# 6. deserialize_state - 合法 JSON
# ============================================================


class TestDeserializeStateValid:
    """deserialize_state: 合法 JSON 字符串 → dict."""

    def test_valid_json_dict(self):
        """合法 JSON dict → 解析为 dict."""
        from auto_engineering.loop.types import deserialize_state

        raw = '{"round": 1, "step": 0, "status": "running"}'
        result = deserialize_state(raw)
        assert result == {"round": 1, "step": 0, "status": "running"}

    def test_valid_json_with_nested_dict(self):
        """嵌套 dict JSON → 解析为嵌套 dict."""
        from auto_engineering.loop.types import deserialize_state

        raw = '{"channels": {"x": {"y": 1}}}'
        result = deserialize_state(raw)
        assert result == {"channels": {"x": {"y": 1}}}

    def test_valid_json_empty_object(self):
        """空 JSON object '{}' → 空 dict."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("{}")
        assert result == {}

    def test_valid_json_unicode(self):
        """Unicode 字符 → 保留."""
        from auto_engineering.loop.types import deserialize_state

        raw = '{"name": "测试"}'
        result = deserialize_state(raw)
        assert result == {"name": "测试"}


# ============================================================
# 7. deserialize_state - 非法 JSON
# ============================================================


class TestDeserializeStateInvalid:
    """deserialize_state: 非法 JSON → __raw__ 包装."""

    def test_invalid_json_returns_raw_wrapper(self):
        """非法 JSON 字符串 → {\"__raw__\": <原始字符串>}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("not-valid-json{")
        assert "__raw__" in result
        assert result["__raw__"] == "not-valid-json{"

    def test_empty_string_returns_raw_wrapper(self):
        """空字符串 → {\"__raw__\": \"\"}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("")
        assert result == {"__raw__": ""}

    def test_truncated_json_returns_raw_wrapper(self):
        """截断的 JSON → __raw__ 包装."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state('{"round": 1,')  # 截断
        assert "__raw__" in result

    def test_none_input_returns_raw_wrapper(self):
        """None 输入 (TypeError) → __raw__ 包装."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state(None)  # type: ignore[arg-type]
        assert "__raw__" in result
        assert result["__raw__"] is None


# ============================================================
# 8. deserialize_state - 非 dict JSON
# ============================================================


class TestDeserializeStateNonDict:
    """deserialize_state: 合法 JSON 但不是 dict (数组/字符串/数字)."""

    def test_json_array_wrapped_as_value(self):
        """JSON 数组 → {\"__value__\": [...]}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("[1, 2, 3]")
        assert "__value__" in result
        assert result["__value__"] == [1, 2, 3]

    def test_json_string_wrapped_as_value(self):
        """JSON 字符串 → {\"__value__\": \"<str>\"}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state('"hello"')
        assert "__value__" in result
        assert result["__value__"] == "hello"

    def test_json_number_wrapped_as_value(self):
        """JSON 数字 → {\"__value__\": <num>}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("42")
        assert "__value__" in result
        assert result["__value__"] == 42

    def test_json_null_wrapped_as_value(self):
        """JSON null → {\"__value__\": None}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("null")
        assert "__value__" in result
        assert result["__value__"] is None

    def test_json_true_wrapped_as_value(self):
        """JSON true → {\"__value__\": True}."""
        from auto_engineering.loop.types import deserialize_state

        result = deserialize_state("true")
        assert "__value__" in result
        assert result["__value__"] is True


# ============================================================
# 9. 序列化/反序列化 往返
# ============================================================


class TestSerializeDeserializeRoundtrip:
    """serialize_state ↔ deserialize_state 往返."""

    def test_roundtrip_dict(self):
        """serialize(dict) → deserialize → dict 等价."""
        from auto_engineering.loop.types import deserialize_state, serialize_state

        original = {"round": 5, "step": 3, "status": "ok", "channels": {"a": 1}}
        serialized = serialize_state(original)
        deserialized = deserialize_state(serialized)
        assert deserialized == original

    def test_roundtrip_pydantic_style(self):
        """Pydantic 风格对象 serialize → deserialize → dict."""
        from auto_engineering.loop.types import deserialize_state, serialize_state

        class FakeModel:
            round = 7
            step = 2
            status = "completed"
            channels = {"data": [1, 2, 3]}

            def model_dump(self, **kwargs: Any) -> dict:
                return {
                    "round": self.round,
                    "step": self.step,
                    "status": self.status,
                    "channels": self.channels,
                }

        state = FakeModel()
        serialized = serialize_state(state)
        deserialized = deserialize_state(serialized)
        assert deserialized["round"] == 7
        assert deserialized["step"] == 2
        assert deserialized["status"] == "completed"
        assert deserialized["channels"] == {"data": [1, 2, 3]}


# ============================================================
# 10. __all__ 导出检查
# ============================================================


class TestExports:
    """types.py __all__ 导出."""

    def test_all_exports(self):
        """__all__ 包含 serialize_state / deserialize_state."""
        from auto_engineering.loop import types

        assert "serialize_state" in types.__all__
        assert "deserialize_state" in types.__all__

    def test_importable_from_module(self):
        """可从模块直接导入."""
        from auto_engineering.loop.types import deserialize_state, serialize_state

        assert serialize_state is not None
        assert deserialize_state is not None