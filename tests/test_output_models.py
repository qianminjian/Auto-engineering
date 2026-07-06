"""测试 agents/output_models.py 的 Pydantic 模型."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from auto_engineering.agents.output_models import ArchitectOutput, CriticOutput, DeveloperOutput


class TestArchitectOutput:
    """ArchitectOutput 模型测试."""

    def test_valid_minimal(self):
        """最小合法输入 — 所有字段取默认值."""
        obj = ArchitectOutput()
        assert obj.files_needed == []
        assert obj.plan == ""
        assert obj.batch_plan == []

    def test_valid_full(self):
        """完整合法输入."""
        data = {
            "files_needed": ["a.py", "b.py"],
            "files_to_create": ["c.py"],
            "files_to_modify": ["a.py"],
            "plan": "## Plan\n1. Do X",
            "file_list": ["a.py", "b.py", "c.py"],
            "batch_plan": [{"id": "B1", "description": "step 1", "files": ["a.py"], "depends_on": []}],
            "contracts": {"a.py": {"inputs": [], "outputs": []}},
        }
        obj = ArchitectOutput(**data)
        assert obj.files_needed == ["a.py", "b.py"]
        assert obj.plan == "## Plan\n1. Do X"
        assert len(obj.batch_plan) == 1

    def test_extra_fields_ignored(self):
        """额外字段被忽略."""
        obj = ArchitectOutput(plan="ok", unknown_field=42)
        assert obj.plan == "ok"
        assert not hasattr(obj, "unknown_field")


class TestDeveloperOutput:
    """DeveloperOutput 模型测试."""

    def test_valid_minimal(self):
        """最小合法输入."""
        obj = DeveloperOutput()
        assert obj.files_changed == []
        assert obj.commit_hash == ""
        assert obj.test_results == {"passed": 0, "failed": 0, "errors": 0}

    def test_valid_full(self):
        """完整合法输入."""
        data = {
            "files_changed": ["src/main.py"],
            "commit_hash": "a" * 40,
            "test_results": {"passed": 10, "failed": 0, "errors": 0},
        }
        obj = DeveloperOutput(**data)
        assert obj.commit_hash == "a" * 40
        assert obj.test_results["passed"] == 10

    def test_commit_hash_pattern_invalid(self):
        """commit_hash 不符合 40 位 hex 格式时抛 ValidationError."""
        with pytest.raises(ValidationError):
            DeveloperOutput(commit_hash="short")

    def test_commit_hash_valid_40hex(self):
        """commit_hash 符合 40 位 hex 格式."""
        obj = DeveloperOutput(commit_hash="0123456789abcdef0123456789abcdef01234567")
        assert obj.commit_hash == "0123456789abcdef0123456789abcdef01234567"

    def test_extra_fields_ignored(self):
        """额外字段被忽略."""
        obj = DeveloperOutput(extra=99)
        assert obj.files_changed == []


class TestCriticOutput:
    """CriticOutput 模型测试."""

    def test_valid_minimal(self):
        """最小合法输入 — 默认 MAJOR verdict."""
        obj = CriticOutput()
        assert obj.verdict == "MAJOR"
        assert obj.findings == []

    def test_valid_approve(self):
        """APPROVE 判定."""
        obj = CriticOutput(verdict="APPROVE")
        assert obj.verdict == "APPROVE"

    def test_valid_major_with_findings(self):
        """MAJOR 判定含 findings."""
        data = {
            "verdict": "MAJOR",
            "findings": [
                {"file": "a.py", "line": 42, "severity": "P0", "issue": "null deref", "suggested_fix": "add guard"},
            ],
            "critic_feedback": "needs work",
            "suggested_fix": "diff --git ...",
        }
        obj = CriticOutput(**data)
        assert len(obj.findings) == 1
        assert obj.findings[0]["severity"] == "P0"
        assert obj.critic_feedback == "needs work"

    def test_verdict_invalid_value(self):
        """verdict 不是 APPROVE/MAJOR 时抛 ValidationError."""
        with pytest.raises(ValidationError):
            CriticOutput(verdict="REJECT")

    def test_extra_fields_ignored(self):
        """额外字段被忽略."""
        obj = CriticOutput(verdict="APPROVE", extra=123)
        assert obj.verdict == "APPROVE"


class TestCriticOutputV55:
    """v5.5 CriticOutput 扩展字段 — strengths + assessment."""

    def test_strengths_defaults_to_none(self):
        """strengths 默认值为 None (向后兼容)."""
        obj = CriticOutput()
        assert obj.strengths is None

    def test_strengths_accepts_list(self):
        """strengths 接受 list[dict] 格式."""
        obj = CriticOutput(
            verdict="APPROVE",
            strengths=[
                {"description": "Clean architecture", "location": "src/core.py"},
                {"description": "Good test coverage", "location": "tests/"},
            ],
        )
        assert len(obj.strengths) == 2
        assert obj.strengths[0]["description"] == "Clean architecture"
        assert obj.strengths[0]["location"] == "src/core.py"

    def test_assessment_defaults_to_none(self):
        """assessment 默认值为 None (向后兼容)."""
        obj = CriticOutput()
        assert obj.assessment is None

    def test_assessment_accepts_ready_to_merge(self):
        """assessment 接受 'Ready to merge'."""
        obj = CriticOutput(verdict="APPROVE", assessment="Ready to merge")
        assert obj.assessment == "Ready to merge"

    def test_assessment_accepts_ready_to_merge_with_fixes(self):
        """assessment 接受 'Ready to merge: With fixes'."""
        obj = CriticOutput(
            verdict="MAJOR",
            assessment="Ready to merge: With fixes",
        )
        assert obj.assessment == "Ready to merge: With fixes"

    def test_assessment_accepts_needs_rework(self):
        """assessment 接受 'Needs rework'."""
        obj = CriticOutput(verdict="MAJOR", assessment="Needs rework")
        assert obj.assessment == "Needs rework"

    def test_full_critic_output_with_v55_fields(self):
        """完整 CriticOutput 含 v5.5 新字段."""
        obj = CriticOutput(
            verdict="MAJOR",
            findings=[{"file": "x.py", "line": 1, "severity": "P0", "issue": "bug"}],
            critic_feedback="needs work",
            suggested_fix="diff --git ...",
            strengths=[
                {"description": "Good error handling", "location": "src/api.py:42-58"},
            ],
            assessment="Ready to merge: With fixes",
        )
        assert obj.verdict == "MAJOR"
        assert len(obj.findings) == 1
        assert obj.strengths[0]["description"] == "Good error handling"
        assert obj.assessment == "Ready to merge: With fixes"
