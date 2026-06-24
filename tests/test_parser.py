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

    def test_parse_empty_string(self):
        """空输入 → None."""
        from auto_engineering.agents.parser import parse_agent_output

        result = parse_agent_output("")
        assert result is None
