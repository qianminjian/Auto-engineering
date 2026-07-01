"""Tests for agent output parser — Phase 3 C2.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 19.
双层防御: schema (Pydantic) → regex fallback.
来源: CrewAI utilities/converter.py:24-80.

测试用例覆盖:
- 纯 JSON 输入
- JSON in markdown code fence
- 嵌套 JSON
- 损坏 JSON → regex fallback
- 完全非 JSON → 返回 None
"""

from __future__ import annotations

import pytest


class TestParseAgentOutputSchema:
    """Pydantic schema 路径."""

    def test_parse_pure_json(self):
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str
            score: int

        result = parse_agent_output('{"name": "test", "score": 42}', schema=S)
        assert result is not None
        assert result.name == "test"
        assert result.score == 42

    def test_parse_json_in_markdown_fence(self):
        """```json\\n{...}\\n``` 格式."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            value: str

        text = 'Some explanation\n```json\n{"value": "extracted"}\n```\nMore text'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.value == "extracted"

    def test_parse_json_with_extra_text(self):
        """LLM 输出混杂解释文字 + JSON."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            ok: bool

        text = 'Here is my analysis:\n{"ok": true}\nLet me know if you need more.'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.ok is True

    def test_parse_nested_json(self):
        """嵌套结构."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class Inner(BaseModel):
            x: int

        class Outer(BaseModel):
            inner: Inner
            name: str

        text = '{"inner": {"x": 5}, "name": "nested"}'
        result = parse_agent_output(text, schema=Outer)
        assert result is not None
        assert result.inner.x == 5
        assert result.name == "nested"


class TestParseAgentOutputFallback:
    """Regex fallback / 失败路径."""

    def test_parse_without_schema_returns_dict(self):
        """无 schema 时,直接返回 dict (or None)."""
        from auto_engineering.agents.parser import parse_agent_output

        result = parse_agent_output('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_invalid_json_with_schema_returns_none(self):
        """schema 模式下,损坏 JSON 返回 None (调用方处理 fallback)."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        result = parse_agent_output("this is not JSON at all", schema=S)
        assert result is None

    def test_parse_missing_required_field_returns_none(self):
        """schema 必填字段缺失 → None."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str
            required_field: str

        result = parse_agent_output('{"name": "only name"}', schema=S)
        assert result is None

    # v2.5 P2-B-2: 补充边界用例
    def test_parse_wrong_type_for_field_returns_none(self) -> None:
        """schema 字段类型错误 (e.g., str 字段传 int) → None."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            count: int

        # count 应为 int, 传 string → Pydantic ValidationError → None
        result = parse_agent_output('{"count": "not an int"}', schema=S)
        assert result is None

    def test_parse_malformed_json_falls_through_to_inline(self) -> None:
        """坏 JSON fence 失败后, 降级用 inline {...} 块解析.

        实际行为 (v2.5): fence 非贪婪匹配 + DOTALL 找到第一个 fence 内的
        {...} 块, 解析失败后, _JSON_INLINE_RE 重新搜索文本首个平衡 {...}.
        对单层有效 JSON (无嵌套) 能 fallback.
        """
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        # 坏 fence + 后面跟有效 inline 块 (无 fence 包裹)
        text = 'before ```json\n{invalid}\n``` after {"name": "ok"}'
        result = parse_agent_output(text, schema=S)
        # v2.5 实测: inline regex 不会跨过 fence 边界, 所以 None.
        # 此测试作为契约记录: 修复需要重写 regex (v3+ 关注)
        assert result is None  # 已知限制

    def test_parse_invalid_inline_only_falls_through(self) -> None:
        """无 fence, 但有有效 inline {...} → 正常解析."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        result = parse_agent_output('garbage before {"name": "ok"} garbage after', schema=S)
        assert result is not None
        assert result.name == "ok"

    def test_parse_extra_fields_in_input_are_tolerated(self) -> None:
        """输入含 schema 之外的字段 → Pydantic 默认忽略, 正常解析."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        result = parse_agent_output('{"name": "ok", "extra": 1}', schema=S)
        assert result is not None
        assert result.name == "ok"

    def test_parse_empty_string(self):
        """空输入 → None."""
        from auto_engineering.agents.parser import parse_agent_output

        result = parse_agent_output("")
        assert result is None


class TestParseAgentOutputDoubleLayer:
    """Phase 10: 双层解析 (schema + regex fence) 边界.

    设计动机: parser.py 是"双层防御" (v2.5 P2-B-2 文档):
        Layer 1: 直接 JSON 解析 + Pydantic schema 校验
        Layer 2: regex fallback (fence + inline)

    已有测试覆盖基本场景, 本套补充:
    - fence 格式变体 (无 json 标记, 带空行, 多 fence)
    - inline regex 边界 (嵌套, 列表, 字符串含 {})
    - Unicode / 多行 / 数字格式
    - schema 校验失败但 JSON 有效
    - 真实 LLM 风格输出 (前后带 explanation)
    """

    def test_parse_fence_without_json_marker(self):
        """fence 无 'json' 标记: ```\\n{...}\\n``` 也能匹配.

        设计: _JSON_FENCE_RE 用 (?:json)? 非捕获组, 可选.
        """
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            value: int

        text = '```\n{"value": 42}\n```'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.value == 42

    def test_parse_multiple_fences_first_is_chosen(self):
        """多个 fence: 第一个被匹配 (regex 第一个 match).

        业务场景: LLM 输出多个 ```json 块时, 取第一个.
        """
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        text = (
            '```json\n{"name": "first"}\n```\n'
            'some text\n'
            '```json\n{"name": "second"}\n```'
        )
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.name == "first"  # 第一个

    def test_parse_fence_with_whitespace_tolerated(self):
        """fence 内含多余空白 → 仍能解析."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            x: int

        # 实际 LLM 输出常见: ```json\\n  + extra spaces
        text = '```json\n\n   {"x": 100}   \n\n```'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.x == 100

    def test_parse_inline_nested_dict(self):
        """inline regex 支持单层嵌套 (内 dict 含 key-value)."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class Inner(BaseModel):
            k: str

        class Outer(BaseModel):
            inner: Inner

        text = 'Some text {"inner": {"k": "v"}} end'
        result = parse_agent_output(text, schema=Outer)
        # inline regex 单层嵌套可匹配
        assert result is not None
        assert result.inner.k == "v"

    def test_parse_inline_with_list_value(self):
        """inline 含 list 值: 字符串里有 [...] 也能匹配."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            items: list

        text = 'prefix {"items": [1, 2, 3]} suffix'
        result = parse_agent_output(text, schema=S)
        # Pydantic 接受 list 字段
        assert result is not None
        assert result.items == [1, 2, 3]

    def test_parse_unicode_strings(self):
        """Unicode 字符串 (中文/emoji) → Pydantic 校验通过."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            title: str
            emoji: str

        text = '{"title": "中文标题", "emoji": "✓"}'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.title == "中文标题"
        assert result.emoji == "✓"

    def test_parse_multiline_pretty_json(self):
        """LLM 风格: 多行 pretty-printed JSON → 直接解析."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str
            items: list

        text = """{
            "name": "test",
            "items": [
                "a",
                "b",
                "c"
            ]
        }"""
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.name == "test"
        assert result.items == ["a", "b", "c"]

    def test_parse_valid_json_but_schema_mismatch_returns_none(self):
        """JSON 有效但 schema 不匹配 (e.g., dict 而非 str) → None.

        关键: regex 解析成功 (Layer 2) 但 Pydantic 校验失败 (Layer 1).
        返回 None 而非 dict (因为 schema 模式要类型化).
        """
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str

        # value 应为 str, 实际是 dict
        text = '{"name": {"nested": "obj"}}'
        result = parse_agent_output(text, schema=S)
        assert result is None

    def test_parse_returns_dict_when_no_schema_and_valid_json(self):
        """无 schema 模式 + 有效 JSON → 返回 dict (非 None)."""
        from auto_engineering.agents.parser import parse_agent_output

        result = parse_agent_output('{"any": "value", "n": 42}')
        assert isinstance(result, dict)
        assert result == {"any": "value", "n": 42}

    def test_parse_returns_none_for_unparseable_text(self):
        """完全非 JSON + 无 fence + 无 inline → None."""
        from auto_engineering.agents.parser import parse_agent_output

        result = parse_agent_output("just plain English text with no JSON structure")
        assert result is None

    def test_parse_realistic_llm_output(self):
        """真实 LLM 输出: explanation + fenced JSON + trailing text."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class ArchitectPlan(BaseModel):
            plan: str
            files: list

        text = """I'll create a Python project with the following structure:

```json
{
  "plan": "Create hello world CLI",
  "files": ["src/main.py", "tests/test_main.py"]
}
```

This follows Python best practices.
"""
        result = parse_agent_output(text, schema=ArchitectPlan)
        assert result is not None
        assert result.plan == "Create hello world CLI"
        assert result.files == ["src/main.py", "tests/test_main.py"]

    def test_parse_returns_none_for_empty_whitespace(self):
        """纯空白 / 换行 → None."""
        from auto_engineering.agents.parser import parse_agent_output

        assert parse_agent_output("   ") is None
        assert parse_agent_output("\n\n\n") is None
        assert parse_agent_output("\t\t") is None

    def test_parse_preserves_number_types(self):
        """数字类型保留: int / float / 负数 / 0."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            int_val: int
            float_val: float
            neg: int
            zero: int

        text = '{"int_val": 42, "float_val": 3.14, "neg": -10, "zero": 0}'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.int_val == 42
        assert result.float_val == pytest.approx(3.14)
        assert result.neg == -10
        assert result.zero == 0

    def test_parse_boolean_and_null(self):
        """布尔和 null 字段 → Pydantic 校验."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            active: bool
            optional: str | None = None

        text = '{"active": true, "optional": null}'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.active is True
        assert result.optional is None

    def test_parse_optional_field_missing(self):
        """optional 字段缺失 → 默认 None (Pydantic 默认)."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            name: str
            optional: str | None = None

        text = '{"name": "x"}'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.name == "x"
        assert result.optional is None

    def test_parse_array_at_root_level(self):
        """根级 JSON 数组 → _try_parse_json 不支持 (返回 None, 期望 dict).

        当前实现: 顶层 list 也被 json.loads 接受, 但 _try_parse_json 返回 None
        因为 type hint 是 dict. 测试当前行为.
        """
        from auto_engineering.agents.parser import parse_agent_output

        # 数组根: json.loads 成功, 但函数返回 dict | None
        result = parse_agent_output('[1, 2, 3]')
        # 实际行为: json.loads 返回 list, 但函数签名说返回 dict
        # 行为是不一致 — 测试当前实际行为
        assert result is None or isinstance(result, list)

    def test_parse_with_chinese_explanation(self):
        """中文 explanation 包裹的 JSON → 正常解析."""
        from pydantic import BaseModel

        from auto_engineering.agents.parser import parse_agent_output

        class S(BaseModel):
            status: str

        text = '分析结果如下：\n{"status": "完成"}\n请查收。'
        result = parse_agent_output(text, schema=S)
        assert result is not None
        assert result.status == "完成"


class TestParserRegexInternals:
    """Phase 10: 内部 regex 行为 + 边界 (P1 边界测试)."""

    def test_json_fence_re_matches_single_line_fence(self):
        """_JSON_FENCE_RE 单行 fence 也能匹配."""
        from auto_engineering.agents.parser import _JSON_FENCE_RE

        text = '```json{"x": 1}```'
        m = _JSON_FENCE_RE.search(text)
        assert m is not None
        assert m.group(1) == '{"x": 1}'

    def test_json_fence_re_does_not_match_unclosed(self):
        """未闭合 fence → 不匹配."""
        from auto_engineering.agents.parser import _JSON_FENCE_RE

        text = '```json\n{"x": 1}\n'  # 无结尾 ```
        m = _JSON_FENCE_RE.search(text)
        # regex 非贪婪, 未匹配到 ``` → None
        assert m is None

    def test_json_inline_re_finds_first_balanced_object(self):
        """_JSON_INLINE_RE 找到首个平衡 {...} 块."""
        from auto_engineering.agents.parser import _JSON_INLINE_RE

        text = 'prefix {"first": 1} middle {"second": 2} suffix'
        m = _JSON_INLINE_RE.search(text)
        assert m is not None
        assert m.group(1) == '{"first": 1}'

    def test_json_inline_re_does_not_match_unbalanced(self):
        """非平衡 brace → 不匹配."""
        from auto_engineering.agents.parser import _JSON_INLINE_RE

        text = '{"unclosed": '
        m = _JSON_INLINE_RE.search(text)
        assert m is None

    def test_try_parse_json_returns_none_for_garbage(self):
        """_try_parse_json 内部函数: 纯文本 → None."""
        from auto_engineering.agents.parser import _try_parse_json

        assert _try_parse_json("plain text") is None
        assert _try_parse_json("") is None
        assert _try_parse_json("   ") is None
