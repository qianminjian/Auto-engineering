"""Tests for agents/schema.py — derive_output_schema."""

import pytest
from auto_engineering.agents.schema import derive_output_schema


class TestDeriveOutputSchema:
    def test_json_example_parses_correctly(self):
        result = derive_output_schema('{"verdict": "APPROVE", "findings": []}')
        assert result is not None
        assert result["type"] == "object"
        assert "verdict" in result["properties"]
        assert result["properties"]["verdict"]["type"] == "string"
        assert "findings" in result["properties"]
        assert result["properties"]["findings"]["type"] == "array"

    def test_json_with_int_and_bool(self):
        result = derive_output_schema('{"count": 42, "active": true}')
        assert result is not None
        assert result["properties"]["count"]["type"] == "integer"
        assert result["properties"]["active"]["type"] == "boolean"

    def test_json_with_float(self):
        result = derive_output_schema('{"score": 3.14}')
        assert result is not None
        assert result["properties"]["score"]["type"] == "number"

    def test_regex_fallback_for_malformed_json(self):
        result = derive_output_schema('{"name": "test", "value": broken}')
        assert result is not None
        assert result["type"] == "object"
        assert "name" in result["properties"]
        assert "value" in result["properties"]

    def test_no_braces_returns_none(self):
        result = derive_output_schema("plain text without json")
        assert result is None

    def test_empty_braces_returns_none(self):
        result = derive_output_schema("{}")
        assert result is None

    def test_unbalanced_braces_returns_none(self):
        result = derive_output_schema("no closing brace {")
        assert result is None

    def test_nested_dict_handled(self):
        result = derive_output_schema('{"outer": {"inner": "value"}}')
        assert result is not None
        assert result["properties"]["outer"]["type"] == "object"
