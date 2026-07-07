"""测试 loop/_self_refine.py — Self-Refine 反馈注入."""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.orchestrator import _inject_self_refine_context
from auto_engineering.loop.plan import Task


def _make_task(task_id: str = "T1", description: str = "Implement X") -> Task:
    return Task(id=task_id, description=description)


def _make_tasks(n: int = 2) -> list[Task]:
    return [_make_task(f"T{i}") for i in range(1, n + 1)]


class TestInjectSelfRefineContext:
    """_inject_self_refine_context 单元测试."""

    def test_architect_stage_no_injection(self):
        """architect stage: 不做任何注入, 原样返回 tasks."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            critic_feedback="bad code",
            findings=[{"file": "a.py", "severity": "P0", "issue": "crash"}],
        )
        result = _inject_self_refine_context(tasks, state, "architect", {})
        # architect stage 直接返回原 list (不做任何注入, 无需复制)
        for orig, res in zip(tasks, result):
            assert res.description == orig.description
        assert result is tasks  # 同一引用, 不做无谓复制

    def test_empty_feedback_no_injection(self):
        """无 feedback/findings/gate_results 时不注入, 原样返回."""
        tasks = _make_tasks()
        state = EngineState(requirement="test")
        result = _inject_self_refine_context(tasks, state, "developer", {})
        for orig, res in zip(tasks, result):
            assert res.description == orig.description

    def test_developer_stage_injects_critic_feedback(self):
        """developer stage: 有 critic_feedback 时注入到 task.description."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            critic_feedback="P0: null deref in main.py",
        )
        result = _inject_self_refine_context(tasks, state, "developer", {})
        assert result is not tasks
        for task in result:
            assert "Self-Refine 反馈" in task.description
            assert "P0: null deref in main.py" in task.description
            assert "优先修复 P0" in task.description

    def test_developer_stage_injects_findings(self):
        """developer stage: 有 findings 时注入具体问题清单."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            findings=[
                {"file": "a.py", "line": 42, "severity": "P0", "issue": "null deref"},
                {"file": "b.py", "line": 10, "severity": "P1", "issue": "missing type"},
            ],
        )
        result = _inject_self_refine_context(tasks, state, "developer", {})
        for task in result:
            assert "Self-Refine findings" in task.description
            assert "a.py:42" in task.description
            assert "[P0]" in task.description
            assert "null deref" in task.description

    def test_developer_stage_injects_gate_results(self):
        """developer stage: 有 gate_results 时注入非 LLM 信号."""
        tasks = _make_tasks()
        state = EngineState(requirement="test")
        from auto_engineering.gates.base import GateVerdict

        gates = {
            "lint": GateVerdict.ok(msg="no issues", gate_name="lint"),
            "test": GateVerdict.failed(msg="3 tests failed", gate_name="test"),
        }
        result = _inject_self_refine_context(tasks, state, "developer", gates)
        for task in result:
            assert "Self-Refine gate_results" in task.description
            assert "lint" in task.description
            assert "test" in task.description
            assert "真实执行结果" in task.description

    def test_developer_stage_injects_suggested_fix(self):
        """developer stage: suggested_fix 随 feedback/findings/gates 一起注入."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            critic_feedback="needs fix",  # 需要至少一个触发条件 (feedback/findings/gates)
            suggested_fix="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x=1\n+x=2",
        )
        result = _inject_self_refine_context(tasks, state, "developer", {})
        for task in result:
            assert "Self-Refine suggested_fix" in task.description
            assert "x=2" in task.description
            assert "unified diff" in task.description

    def test_critic_stage_also_injects(self):
        """critic stage: 同 developer, 也会注入反馈上下文."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            critic_feedback="needs more tests",
        )
        result = _inject_self_refine_context(tasks, state, "critic", {})
        for task in result:
            assert "Self-Refine 反馈" in task.description

    def test_findings_with_non_dict_entries(self):
        """findings 条目可能不是 dict, 仍能正确处理."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            findings=["some string finding", {"file": "c.py", "severity": "P2", "issue": "style"}],
        )
        result = _inject_self_refine_context(tasks, state, "developer", {})
        for task in result:
            assert "some string finding" in task.description
            assert "c.py" in task.description

    def test_no_suggested_fix_when_empty(self):
        """suggested_fix 为空时不下标题."""
        tasks = _make_tasks()
        state = EngineState(
            requirement="test",
            critic_feedback="fix it",
            suggested_fix="",
        )
        result = _inject_self_refine_context(tasks, state, "developer", {})
        for task in result:
            assert "Self-Refine suggested_fix" not in task.description
