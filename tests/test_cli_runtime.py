"""P1.2 — dev-loop CLI 默认真接 LLM (API key 检测 + runtime 构造).

验收:
- ANTHROPIC_API_KEY 设置时,runtime 是 AgentRuntime(非 ScriptedMockRuntime)
- ANTHROPIC_API_KEY 未设置时,fallback 到 ScriptedMockRuntime
- ae dev-loop --dry-run "x" 只跑 architect stage 后退出
"""

from __future__ import annotations

import os
from unittest.mock import patch

from auto_engineering.cli import _build_v1_runtime
from auto_engineering.runtime.mock import ScriptedMockRuntime


class TestRuntimeSelection:
    """runtime 类型选择逻辑."""

    def test_api_key_set_uses_agent_runtime(self):
        """ANTHROPIC_API_KEY 设置时 → AgentRuntime."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            runtime = _build_v1_runtime("test requirement")
            # AgentRuntime 有 register 方法,ScriptedMockRuntime 没有
            assert hasattr(runtime, "register")

    def test_api_key_not_set_uses_mock_runtime(self):
        """ANTHROPIC_API_KEY 未设置时 → ScriptedMockRuntime."""
        with patch.dict(os.environ, {}, clear=False):
            # 确保没有 ANTHROPIC_API_KEY
            env_without = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            with patch.dict(os.environ, env_without, clear=True):
                runtime = _build_v1_runtime("test requirement")
                assert isinstance(runtime, ScriptedMockRuntime)

    def test_agent_runtime_has_3_agents_registered(self):
        """AgentRuntime 注册了 architect/developer/critic 三个 Agent."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            runtime = _build_v1_runtime("test requirement")
            # 检查 _factories 包含这 3 个 key
            assert "architect" in runtime._factories
            assert "developer" in runtime._factories
            assert "critic" in runtime._factories

    def test_agent_runtime_architect_agent_is_callable(self):
        """architect factory 可调用,返回 Agent 对象."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            runtime = _build_v1_runtime("test requirement")
            architect = runtime._factories["architect"]()
            assert hasattr(architect, "execute")
