"""Tests for Phase 06 — v2.0 多 Agent 并行前置工作.

覆盖:
- Task 5.1: Architect prompt 文件集预检指令
- Task 5.2: 契约确认机制骨架（two-green gate hook）
- Task 5.3: templates/app-service/.worktreeinclude.tmpl 恢复

设计: design/v1.1-Plan-Dev.md §三 Phase 5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_engineering.agents import ARCHITECT_SYSTEM_PROMPT
from auto_engineering.agents.base import BaseAgent
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.llm.anthropic_provider import (
    AnthropicProvider,
    LLMResponse,
    LLMUsage,
)
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task
from tests.conftest import run_async


def _make_ok_response(values: dict) -> LLMResponse:
    """Helper: 模拟 LLM 返回 JSON dict."""
    import json

    return LLMResponse(
        content=json.dumps(values),
        model="claude-test",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
        tool_use_blocks=[],
    )


class TestArchitectFilePrecheck:
    """Task 5.1: Architect prompt 必须包含文件集预检指令.

    验证 design/v1.1-Plan-Dev.md §三 Phase 5.1:
        Architect prompt 增加 "在分析前先输出文件集预检"指令
    """

    def test_prompt_includes_precheck_instruction(self):
        """Architect system prompt 必须显式要求文件集预检输出."""
        prompt = ARCHITECT_SYSTEM_PROMPT
        # 必须有预检相关关键词(中文或英文均可,但要明确指向"分析前")
        assert "文件集预检" in prompt or "file precheck" in prompt.lower(), (
            "Architect prompt 缺少文件集预检指令（Task 5.1）"
        )

    def test_prompt_requires_precheck_before_analysis(self):
        """文件集预检必须在分析/输出 plan 之前完成."""
        prompt = ARCHITECT_SYSTEM_PROMPT
        # 必须显式声明"先输出 X 再做 Y"的顺序
        assert "先输出" in prompt or "分析前" in prompt or "before analysis" in prompt.lower(), (
            "Architect prompt 缺少'预检 → 分析'的先后顺序约束"
        )

    def test_precheck_output_structure_is_documented(self):
        """预检输出结构（files_needed / files_to_create / files_to_modify）必须在 prompt 中定义."""
        prompt = ARCHITECT_SYSTEM_PROMPT
        # 三段式文件集结构（v2.0 多 Agent 并行前置需求）
        for keyword in ("files_needed", "files_to_create", "files_to_modify"):
            assert keyword in prompt, f"Architect prompt 缺少预检输出字段 '{keyword}'"

    def test_execute_with_precheck_output(self):
        """端到端: Architect 可输出含预检字段的 JSON plan."""
        from auto_engineering.agents import ArchitectAgent

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(
            return_value=_make_ok_response(
                {
                    "files_needed": ["src/auth.py", "tests/test_auth.py"],
                    "files_to_create": ["src/auth.py"],
                    "files_to_modify": ["src/middleware.py"],
                    "plan": "1. Add auth module\n2. Wire middleware",
                    "file_list": ["src/auth.py", "src/middleware.py"],
                }
            )
        )
        agent = ArchitectAgent(llm=llm)
        task = Task(
            id="architect",
            description="design user auth",
            expected_output="plan",
            output_channels=["plan", "file_list"],
        )
        ctx = TaskContext(state=LoopState(), requirement="design user auth")

        result = run_async(agent.execute(task, ctx))

        assert result.values["files_needed"] == ["src/auth.py", "tests/test_auth.py"]
        assert result.values["files_to_create"] == ["src/auth.py"]
        assert result.values["files_to_modify"] == ["src/middleware.py"]


class TestContractGateHook:
    """Task 5.2: 契约确认机制骨架（two-green gate hook）.

    设计目标: Agent execute 前先输出契约确认 gate,
    等用户(或 CI 自动化)签字才能继续.

    实现策略: 在 BaseAgent 上挂一个 contract_gate 钩子,
    默认实现 = 空操作（auto-approve），但用户/CI 可替换为交互式确认.
    """

    def test_base_agent_has_contract_gate_attribute(self):
        """BaseAgent 必须暴露 contract_gate 字段."""
        # 字段默认值不应为 None（auto-approve 行为）— 应该是某种 callable
        # 通过创建实例验证字段存在
        llm = MagicMock(spec=AnthropicProvider)
        agent = BaseAgent(llm=llm, system_prompt="test")
        assert hasattr(agent, "contract_gate"), "BaseAgent 缺少 contract_gate 字段"
        # 默认值可以是 callable 或 None（auto-approve），但不能缺失
        assert agent.contract_gate is None or callable(agent.contract_gate)

    def test_default_contract_gate_is_none(self):
        """默认 contract_gate = None (auto-approve,不阻塞执行)."""
        llm = MagicMock(spec=AnthropicProvider)
        agent = BaseAgent(llm=llm, system_prompt="test")
        assert agent.contract_gate is None

    def test_execute_invokes_contract_gate_before_llm(self):
        """execute() 必须在第一次 LLM 调用前触发 contract_gate."""
        invoked: list[str] = []

        def gate(task: Task, ctx: TaskContext) -> bool:
            invoked.append(task.id)
            return True  # approve

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(
            return_value=_make_ok_response({"plan": "ok", "file_list": []})
        )
        agent = BaseAgent(llm=llm, system_prompt="test", contract_gate=gate)
        task = Task(
            id="t1",
            description="x",
            expected_output="plan",
            output_channels=["plan"],
        )
        ctx = TaskContext(state=LoopState(), requirement="x")

        run_async(agent.execute(task, ctx))

        assert invoked == ["t1"], f"contract_gate 未在 LLM 调用前触发,实际触发顺序={invoked}"

    def test_contract_gate_rejection_aborts_execute(self):
        """contract_gate 返回 False 必须中止 execute,LLM 不被调用."""
        def rejecting_gate(task: Task, ctx: TaskContext) -> bool:
            return False

        llm = MagicMock(spec=AnthropicProvider)
        llm.create_message = AsyncMock(
            return_value=_make_ok_response({"plan": "should_not_run"})
        )
        agent = BaseAgent(
            llm=llm, system_prompt="test", contract_gate=rejecting_gate
        )
        task = Task(
            id="t1",
            description="x",
            expected_output="plan",
            output_channels=["plan"],
        )
        ctx = TaskContext(state=LoopState(), requirement="x")

        with pytest.raises(AEError) as exc_info:
            run_async(agent.execute(task, ctx))
        assert exc_info.value.code == ErrorCode.CONTRACT_REJECTED

        # LLM 必须没被调用（gate 在前）
        llm.create_message.assert_not_called()


class TestWorktreeIncludeTemplate:
    """Task 5.3: templates/app-service/.worktreeinclude.tmpl 恢复.

    用途: Claude Code worktree 多 Agent 并行运行时的文件 include 规则.
    设计来源: design/his_bak/v1.1-UNIFIED-DEV-PLAN.md §5.3 + multi-agent §3.5
    """

    def test_worktreeinclude_template_exists(self):
        """templates/app-service/.worktreeinclude.tmpl 必须存在."""
        import os

        path = (
            "/Users/minjianq/Documents/06-Mi-Model-Rule/Auto-engineering/"
            "auto_engineering/init/templates/app-service/.worktreeinclude.tmpl"
        )
        assert os.path.exists(path), f"模板缺失: {path}"

    def test_worktreeinclude_template_not_empty(self):
        """模板不能是空文件."""
        path = (
            "/Users/minjianq/Documents/06-Mi-Model-Rule/Auto-engineering/"
            "auto_engineering/init/templates/app-service/.worktreeinclude.tmpl"
        )
        with open(path) as f:
            content = f.read().strip()
        assert len(content) > 0, "模板不能为空"

    def test_worktreeinclude_documents_worktree_purpose(self):
        """模板应说明 worktree include 用途(注释或关键字)."""
        path = (
            "/Users/minjianq/Documents/06-Mi-Model-Rule/Auto-engineering/"
            "auto_engineering/init/templates/app-service/.worktreeinclude.tmpl"
        )
        with open(path) as f:
            content = f.read()
        # 必须提到 worktree 或 include（避免空模板通过）
        content_lower = content.lower()
        assert (
            "worktree" in content_lower or "include" in content_lower
        ), "模板内容应说明 worktree include 用途"