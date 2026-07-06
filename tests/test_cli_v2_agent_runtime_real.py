"""test_cli_v2_agent_runtime_real.py — P0-B: RED test.

Verify that _build_v2_agent_runtime returns AgentRuntime with all 3 roles
registered as real Agent (BaseAgent) instances, not _MockRoleAgent adapter.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_engineering.agents.base import BaseAgent
from auto_engineering.cli import ProgressLogger, _build_v2_agent_runtime


class TestBuildV2AgentRuntimeReal:
    """P0-B: _build_v2_agent_runtime 必须注册真实 BaseAgent 实例."""

    def test_registers_real_agent_for_architect(self, tmp_path: Path) -> None:
        """architect role 注册的是 BaseAgent 实例, 不是 mock/local adapter."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            architect = runtime.get("architect")
            assert architect is not None, "architect agent not registered"
            assert isinstance(architect, BaseAgent), (
                f"architect should be BaseAgent, got {type(architect).__name__}"
            )
            # Explicitly NOT a local mock class (which would lack llm attribute)
            assert hasattr(architect, "llm"), (
                f"architect should have 'llm' attribute (real BaseAgent), "
                f"got {type(architect).__name__} with attrs {dir(architect)}"
            )
            assert architect.role == "architect", (
                f"architect role mismatch: {architect.role}"
            )

    def test_registers_real_agent_for_developer(self, tmp_path: Path) -> None:
        """developer role 注册的是 BaseAgent 实例, 不是 _DeveloperAgentAdapter."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            developer = runtime.get("developer")
            assert developer is not None, "developer agent not registered"
            assert isinstance(developer, BaseAgent), (
                f"developer should be BaseAgent, got {type(developer).__name__}"
            )
            assert hasattr(developer, "llm"), (
                f"developer should have 'llm' attribute (real BaseAgent), "
                f"got {type(developer).__name__}"
            )
            assert developer.role == "developer", (
                f"developer role mismatch: {developer.role}"
            )

    def test_registers_real_agent_for_critic(self, tmp_path: Path) -> None:
        """critic role 注册的是 BaseAgent 实例, 不是 mock/local adapter."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            critic = runtime.get("critic")
            assert critic is not None, "critic agent not registered"
            assert isinstance(critic, BaseAgent), (
                f"critic should be BaseAgent, got {type(critic).__name__}"
            )
            assert hasattr(critic, "llm"), (
                f"critic should have 'llm' attribute (real BaseAgent), "
                f"got {type(critic).__name__}"
            )
            assert critic.role == "critic", (
                f"critic role mismatch: {critic.role}"
            )

    def test_no_adapter_class_names_leaked(self, tmp_path: Path) -> None:
        """注册的 agent 类型名不含 'Mock' 或 'Adapter'."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            for role in ("architect", "developer", "critic"):
                agent = runtime.get(role)
                assert agent is not None, f"{role} agent not registered"
                agent_type_name = type(agent).__name__
                assert "Mock" not in agent_type_name, (
                    f"{role} agent type '{agent_type_name}' contains 'Mock'"
                )
                assert "Adapter" not in agent_type_name, (
                    f"{role} agent type '{agent_type_name}' contains 'Adapter'"
                )

    def test_all_three_roles_registered(self, tmp_path: Path) -> None:
        """3 个核心 role (architect, developer, critic) 全部注册."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            assert runtime.get("architect") is not None
            assert runtime.get("developer") is not None
            assert runtime.get("critic") is not None

    def test_reviewer_not_registered(self, tmp_path: Path) -> None:
        """reviewer 不应被注册 (v2.0 只有 3 个 role)."""
        with _mock_dependencies(tmp_path):
            progress = ProgressLogger(log_format="text")
            runtime = _build_v2_agent_runtime(tmp_path, progress)

            assert runtime.get("reviewer") is None, (
                "reviewer should not be registered in production path"
            )


# ── helpers ──────────────────────────────────────────────────────────


class _FakeLLM:
    """Fake AnthropicProvider for tests — 不调用真实 API."""

    def create_message(self, **kwargs):
        return MagicMock(
            content="{}",
            stop_reason="end_turn",
            tool_use_blocks=None,
        )


def _mock_dependencies(tmp_path: Path):
    """提供测试需要的 mock 环境: AnthropicProvider + API key + 工具构造.

    AnthropicProvider 在 _build_v2_agent_runtime 函数体内 import,
    因此 patch 必须在源模块 auto_engineering.llm.anthropic_provider.

    使用 start/stop 模式: patch.dict 的 __enter__ 返回的是 os.environ 而非
    patch 自身, 无法用于 multi-context 栈式 exit, 因此统一用 start()/stop().
    """
    patchers = [
        patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake-key"}, clear=False),
        patch(
            "auto_engineering.llm.anthropic_provider.AnthropicProvider",
            return_value=_FakeLLM(),
        ),
    ]
    return _MultiPatcher(patchers)


class _MultiPatcher:
    """Enter/exit multiple patch context managers with start/stop.

    使用 start()/stop() 替代 __enter__/__exit__ 模式,
    避免 patch.dict.__enter__ 返回 os.environ 造成的类型混乱.
    """

    def __init__(self, patchers):
        self._patchers = patchers

    def __enter__(self):
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *args):
        for p in reversed(self._patchers):
            p.stop()
