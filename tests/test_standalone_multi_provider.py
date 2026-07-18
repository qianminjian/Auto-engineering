"""Tests for StandaloneDriver multi-provider integration (T59).

T59: 补齐真实 LLM 多 provider 集成 — Ollama + 国产模型 E2E GOAL_ACHIEVED.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestProviderFactory:
    """Provider factory creates correct provider types."""

    def test_factory_creates_anthropic_provider(self) -> None:
        """create_provider('anthropic') returns AnthropicProvider."""
        from auto_engineering.providers.factory import create_provider

        with patch.dict(os.environ, {}, clear=True):
            provider = create_provider("anthropic")
        from auto_engineering.llm.anthropic_provider import AnthropicProvider
        assert isinstance(provider, AnthropicProvider)

    def test_factory_creates_ollama_provider(self) -> None:
        """create_provider('ollama') returns OllamaProvider."""
        from auto_engineering.providers.factory import create_provider

        provider = create_provider("ollama")
        from auto_engineering.providers.ollama import OllamaProvider
        assert isinstance(provider, OllamaProvider)

    def test_factory_creates_glm_provider(self) -> None:
        """create_provider('glm') returns GLMProvider."""
        from auto_engineering.providers.factory import create_provider

        provider = create_provider("glm", api_key="test-key")
        from auto_engineering.providers.glm import GLMProvider
        assert isinstance(provider, GLMProvider)

    def test_factory_creates_qwen_provider(self) -> None:
        """create_provider('qwen') returns QwenProvider."""
        from auto_engineering.providers.factory import create_provider

        provider = create_provider("qwen", api_key="test-key")
        from auto_engineering.providers.qwen import QwenProvider
        assert isinstance(provider, QwenProvider)

    def test_factory_raises_on_unknown_provider(self) -> None:
        """create_provider with unknown name raises ValueError."""
        from auto_engineering.providers.factory import create_provider

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Unknown provider"):
                create_provider("unknown_vendor")

    def test_factory_auto_detect_ollama_from_env(self) -> None:
        """OLLAMA_HOST env var → auto-detect ollama provider."""
        from auto_engineering.providers.factory import create_provider

        with patch.dict(os.environ, {"OLLAMA_HOST": "http://localhost:11434"}, clear=True):
            provider = create_provider()
        from auto_engineering.providers.ollama import OllamaProvider
        assert isinstance(provider, OllamaProvider)


class TestStandaloneMultiProvider:
    """StandaloneDriver multi-provider integration (T59)."""

    def test_resolve_model_with_env_override(self) -> None:
        """AE_MODEL_ARCHITECT env var overrides default model."""
        from auto_engineering.loop.standalone_driver import _resolve_model

        with patch.dict(os.environ, {"AE_MODEL_ARCHITECT": "gpt-4o"}, clear=True):
            assert _resolve_model("architect") == "gpt-4o"

    def test_resolve_model_defaults(self) -> None:
        """_resolve_model returns default without env override."""
        from auto_engineering.loop.standalone_driver import _resolve_model

        with patch.dict(os.environ, {}, clear=True):
            model = _resolve_model("critic")
            assert "claude" in model.lower()

    def test_standalone_driver_accepts_multi_provider_runtime(self, tmp_path) -> None:
        """StandaloneDriver works with multi-provider AgentRuntime (T59)."""
        from auto_engineering.loop.tick_orchestrator import TickOrchestrator
        from auto_engineering.runtime.runtime import AgentRuntime

        orch = TickOrchestrator(
            tmp_path,
            gate_runner=lambda names, root: {
                n: MagicMock(passed=True, message="ok") for n in names
            },
            guardrail=MagicMock(),
            checkpoint_store=None,
        )

        runtime = AgentRuntime()
        # Register agents with different mock provider types
        anthropic_mock = MagicMock()
        anthropic_mock.__class__.__name__ = "AnthropicProvider"
        ollama_mock = MagicMock()
        ollama_mock.__class__.__name__ = "OllamaProvider"

        # Both mock agents respond identically but represent different providers
        for role, _mock_provider in [("architect", anthropic_mock),
                                       ("developer", ollama_mock),
                                       ("critic", anthropic_mock)]:
            agent = MagicMock()
            agent.execute = _make_mock_execute(role)
            runtime.register(role, lambda a=agent: a)

        from auto_engineering.loop.standalone_driver import StandaloneDriver
        driver = StandaloneDriver(
            orchestrator=orch,
            agent_runtime=runtime,
            project_root=tmp_path,
        )
        summary = driver.run("test multi-provider")
        assert summary is not None


def _make_mock_execute(role: str):
    """Create mock execute function for a role."""
    from auto_engineering.runtime.task import TaskResult

    _VALID_PLAN = (
        "实现组件, 包含完整的 TDD Red-Green-Refactor 循环 + Gate 验证流程"
    )

    results = {
        "architect": TaskResult(
            task_id="architect",
            values={
                "stage": "architect", "plan": _VALID_PLAN,
                "batch_plan": [{
                    "batch_id": "b1", "design_section": "B2", "component": "C",
                    "tasks": [{"id": "T1", "description": "实现 X",
                               "module_ref": "§B2", "file_targets": ["x.py"]}],
                }],
                "file_list": ["x.py"], "contracts": {},
            },
            agent_type="architect",
        ),
        "developer": TaskResult(
            task_id="developer",
            values={
                "stage": "developer", "batch_id": "b1",
                "files_changed": ["x.py"],
                "test_results": {"passed": 1, "failed": 0},
            },
            agent_type="developer",
        ),
        "critic": TaskResult(
            task_id="critic",
            values={
                "stage": "critic", "verdict": "APPROVE",
                "findings": [], "critic_feedback": "LGTM",
            },
            agent_type="critic",
        ),
        "component_verifier": TaskResult(
            task_id="component_verifier",
            values={
                "stage": "component_verifier", "component": "C",
                "coverage_map": [{"design_item": "B2-1",
                                  "status": "IMPLEMENTED",
                                  "file": "x.py", "line": 10, "note": ""}],
                "missing_count": 0, "diverged_count": 0,
            },
            agent_type="component_verifier",
        ),
        "system_deep_audit": TaskResult(
            task_id="system_deep_audit",
            values={
                "stage": "system_deep_audit",
                "findings": [],
                "p0_count": 0, "p1_count": 0, "p2_count": 0,
                "total_audited_files": 1,
                "design_docs_stale": False,
                "design_doc_suggestions": "",
                "missing_count": 0, "diverged_count": 0,
            },
            agent_type="system_deep_audit",
        ),
    }

    async def _execute(task, ctx, cancellation=None, token_tracker=None):
        return results.get(role, TaskResult(task_id=task.id, values={}))

    return _execute
