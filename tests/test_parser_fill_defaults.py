"""Tests for _fill_defaults — agent output partial JSON 默认值补齐.

DeepSeek 等模型经常产出部分 JSON. _fill_defaults 在 RESULT_SCHEMA
校验前补齐缺失字段, 减少假格式错误.
"""

from __future__ import annotations


class TestFillDefaultsArchitect:
    """Architect stage 默认值补齐."""

    def test_fills_missing_plan_from_text(self):
        """architect 缺 plan → 用原始 text 填充."""
        from auto_engineering.agents.parser import _fill_defaults

        text = "Some plan description"
        parsed = {"stage": "architect"}
        _fill_defaults(parsed, text)
        assert parsed["plan"] == text

    def test_fills_missing_batch_plan_as_empty_list(self):
        """architect 缺 batch_plan → v7.0.1: 自动构造最小 batch (DeepSeek 兼容)."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "architect"}
        _fill_defaults(parsed, "some text")
        # v7.0.1: 空 batch_plan 自动填充最小 batch
        assert len(parsed["batch_plan"]) == 1
        assert parsed["batch_plan"][0]["batch_id"] == "T1"

    def test_fills_missing_file_list_from_text(self):
        """architect 缺 file_list → 从 text 提取."""
        from auto_engineering.agents.parser import _fill_defaults

        text = "modify `src/main.py` and `tests/test_main.py`"
        parsed = {"stage": "architect"}
        _fill_defaults(parsed, text)
        assert "src/main.py" in parsed["file_list"]
        assert "tests/test_main.py" in parsed["file_list"]

    def test_fills_missing_contracts_as_empty_dict(self):
        """architect 缺 contracts → 空 dict."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "architect"}
        _fill_defaults(parsed, "some text")
        assert parsed["contracts"] == []

    def test_does_not_override_existing_plan(self):
        """architect 已有 plan → 不覆盖."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "architect", "plan": "existing plan"}
        _fill_defaults(parsed, "fallback text")
        assert parsed["plan"] == "existing plan"

    def test_does_not_override_existing_batch_plan(self):
        """architect 已有 batch_plan → 标准化但不覆盖核心字段 (v7.8)."""
        from auto_engineering.agents.parser import _fill_defaults

        bp = [{"batch_id": "B1", "component": "test"}]
        parsed = {"stage": "architect", "batch_plan": bp}
        _fill_defaults(parsed, "text")
        # v7.8: batch_plan 经过 _normalize_batch_plan 标准化, 补 tasks
        result = parsed["batch_plan"]
        assert len(result) == 1
        assert result[0]["batch_id"] == "B1"
        assert result[0]["component"] == "test"
        assert "tasks" in result[0]
        assert len(result[0]["tasks"]) == 1


class TestFillDefaultsDeveloper:
    """Developer stage 默认值补齐."""

    def test_fills_missing_batch_id_as_T1(self):
        """developer 缺 batch_id → T1."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "developer"}
        _fill_defaults(parsed, "some text")
        assert parsed["batch_id"] == "T1"

    def test_fills_missing_files_changed_from_text(self):
        """developer 缺 files_changed → 从 text 提取."""
        from auto_engineering.agents.parser import _fill_defaults

        text = "modified: `src/main.py`, `src/utils.py`"
        parsed = {"stage": "developer", "batch_id": "T1",
                   "files_changed": [], "test_results": {"passed": 1, "failed": 0}}  # 预先填
        # 先设 files_changed 为空
        parsed = {"stage": "developer"}
        _fill_defaults(parsed, text)
        assert "src/main.py" in parsed["files_changed"]
        assert "src/utils.py" in parsed["files_changed"]

    def test_fills_missing_test_results_with_default(self):
        """developer 缺 test_results → 默认 passed=1 failed=0 total=1."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "developer"}
        _fill_defaults(parsed, "text")
        assert parsed["test_results"] == {"passed": 1, "failed": 0, "total": 1}

    def test_does_not_override_existing_test_results(self):
        """developer 已有 test_results → 不覆盖."""
        from auto_engineering.agents.parser import _fill_defaults

        tr = {"passed": 5, "failed": 0, "total": 5}
        parsed = {"stage": "developer", "test_results": tr}
        _fill_defaults(parsed, "text")
        assert parsed["test_results"] == tr


class TestFillDefaultsCritic:
    """Critic stage 默认值补齐."""

    def test_fills_missing_verdict_as_APPROVE(self):
        """critic 缺 verdict → APPROVE."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "critic"}
        _fill_defaults(parsed, "some review text")
        assert parsed["verdict"] == "APPROVE"

    def test_fills_missing_findings_as_empty_list(self):
        """critic 缺 findings → 空列表."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "critic"}
        _fill_defaults(parsed, "text")
        assert parsed["findings"] == []

    def test_fills_missing_strengths_as_empty_list(self):
        """critic 缺 strengths → 空列表."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "critic"}
        _fill_defaults(parsed, "text")
        assert parsed["strengths"] == []

    def test_fills_missing_assessment_from_text(self):
        """critic 缺 assessment → 用原始 text."""
        from auto_engineering.agents.parser import _fill_defaults

        text = "This is a code review assessment"
        parsed = {"stage": "critic"}
        _fill_defaults(parsed, text)
        assert parsed["assessment"] == text

    def test_fills_missing_critic_feedback_from_text(self):
        """critic 缺 critic_feedback → 用原始 text."""
        from auto_engineering.agents.parser import _fill_defaults

        text = "Overall feedback on the changes"
        parsed = {"stage": "critic"}
        _fill_defaults(parsed, text)
        assert parsed["critic_feedback"] == text

    def test_does_not_override_existing_verdict(self):
        """critic 已有 verdict → 不覆盖."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "critic", "verdict": "MAJOR"}
        _fill_defaults(parsed, "text")
        assert parsed["verdict"] == "MAJOR"


class TestFillDefaultsEdgeCases:
    """边界情况."""

    def test_no_stage_field_does_nothing(self):
        """缺 stage → 什么都不做."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"some_field": "value"}
        original = dict(parsed)
        _fill_defaults(parsed, "text")
        assert parsed == original

    def test_empty_stage_does_nothing(self):
        """stage 为空字符串 → 什么都不做."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": ""}
        original = dict(parsed)
        _fill_defaults(parsed, "text")
        assert parsed == original

    def test_non_string_stage_does_nothing(self):
        """stage 不是字符串 → 什么都不做."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": 123}
        original = dict(parsed)
        _fill_defaults(parsed, "text")
        assert parsed == original

    def test_unknown_stage_does_nothing(self):
        """未知 stage → 什么都不做."""
        from auto_engineering.agents.parser import _fill_defaults

        parsed = {"stage": "unknown_stage"}
        original = dict(parsed)
        _fill_defaults(parsed, "text")
        assert parsed == original


class TestFillDefaultsIntegration:
    """_fill_defaults 与 parse_agent_output 的集成."""

    def test_architect_partial_json_gets_filled(self):
        """architect 部分 JSON → 补齐缺失字段."""
        from auto_engineering.agents.parser import parse_agent_output

        text = '{"stage": "architect", "plan": "do the thing", "batch_plan": [{"batch_id": "T1", "component": "x"}]}'
        result = parse_agent_output(text)
        assert result is not None
        assert isinstance(result, dict)
        assert result["stage"] == "architect"
        assert result["plan"] == "do the thing"
        # file_list 和 contracts 应被补齐
        assert "file_list" in result
        assert "contracts" in result

    def test_developer_partial_json_gets_filled(self):
        """developer 部分 JSON → 补齐缺失字段."""
        from auto_engineering.agents.parser import parse_agent_output

        text = '{"stage": "developer", "files_changed": ["src/main.py"]}'
        result = parse_agent_output(text)
        assert result is not None
        assert isinstance(result, dict)
        assert result["stage"] == "developer"
        # batch_id 和 test_results 应被补齐
        assert result["batch_id"] == "T1"
        assert "test_results" in result
        assert result["test_results"]["passed"] == 1

    def test_developer_full_json_not_overridden(self):
        """developer 完整 JSON → 不覆盖已有字段."""
        from auto_engineering.agents.parser import parse_agent_output

        text = (
            '{"stage": "developer", "batch_id": "B2", '
            '"files_changed": ["x.py"], '
            '"test_results": {"passed": 3, "failed": 0}}'
        )
        result = parse_agent_output(text)
        assert result is not None
        assert isinstance(result, dict)
        assert result["batch_id"] == "B2"  # 不覆盖为 T1
        assert result["test_results"]["passed"] == 3  # 不覆盖

    def test_critic_partial_json_gets_filled(self):
        """critic 部分 JSON → 补齐缺失字段."""
        from auto_engineering.agents.parser import parse_agent_output

        text = '{"stage": "critic", "findings": [{"severity": "P1", "file": "a.py", "line": 1, "description": "bug"}]}'
        result = parse_agent_output(text)
        assert result is not None
        assert isinstance(result, dict)
        assert result["stage"] == "critic"
        assert "verdict" in result  # 被补齐
        assert "assessment" in result  # 被补齐
        assert "critic_feedback" in result  # 被补齐
