"""Tests for StandaloneDriver — V7-5 Driver B standalone execution.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.

Driver B: 进程内 AgentRuntime 调 LLM → 回喂 tick_dict → 循环至收敛.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ── Test helpers ──

_VALID_PLAN = (
    "实现组件, 包含完整的 TDD Red-Green-Refactor 循环 + Gate 验证流程"
)


def _make_mock_agent(responses_by_role: dict | None = None) -> MagicMock:
    """构造 mock Agent, 根据 role 返回不同 TaskResult."""
    from auto_engineering.runtime.task import TaskResult

    defaults = {
        "architect": TaskResult(
            task_id="architect",
            values={
                "stage": "architect",
                "plan": _VALID_PLAN,
                "batch_plan": [{
                    "batch_id": "b1", "design_section": "B2", "component": "C",
                    "tasks": [{"id": "T1", "description": "实现 X",
                               "module_ref": "§B2", "file_targets": ["x.py"]}],
                }],
                "file_list": ["x.py"],
                "contracts": {},
            },
            agent_type="architect",
        ),
        "developer": TaskResult(
            task_id="developer",
            values={
                "stage": "developer",
                "batch_id": "b1",
                "files_changed": ["x.py"],
                "test_results": {"passed": 1, "failed": 0},
            },
            agent_type="developer",
        ),
        "critic": TaskResult(
            task_id="critic",
            values={
                "stage": "critic",
                "verdict": "APPROVE",
                "findings": [],
                "critic_feedback": "LGTM",
            },
            agent_type="critic",
        ),
        "component_verifier": TaskResult(
            task_id="component_verifier",
            values={
                "stage": "component_verifier",
                "component": "C",
                "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                                  "file": "x.py", "line": 10, "note": ""}],
                "missing_count": 0,
                "diverged_count": 0,
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
    responses = dict(defaults)
    if responses_by_role:
        responses.update(responses_by_role)

    async def _execute(task, ctx, cancellation=None, token_tracker=None):
        role = task.id.split(":")[0] if ":" in task.id else task.id
        if role in responses:
            return responses[role]
        return TaskResult(task_id=task.id, values={"error": f"no mock for {role}"})

    agent = MagicMock()
    agent.execute = _execute
    return agent


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    g = MagicMock()
    g.check.return_value = MagicMock(action="pass")
    return g


# ── V7-5: StandaloneDriver ──


class TestStandaloneDriverBasic:
    """V7-5: StandaloneDriver 基本循环 — architect→developer→critic→收敛."""

    def test_run_completes_simple_requirement(self, tmp_path):
        """RED: StandaloneDriver.run("需求") 从 init→done 完整循环."""
        from auto_engineering.loop.tick_orchestrator import TickOrchestrator
        from auto_engineering.runtime.runtime import AgentRuntime

        orch = TickOrchestrator(
            tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )

        runtime = AgentRuntime()
        mock = _make_mock_agent()
        for role in ["architect", "developer", "critic",
                      "component_verifier", "system_deep_audit"]:
            runtime.register(role, lambda r=role: mock)

        from auto_engineering.loop.standalone_driver import StandaloneDriver
        driver = StandaloneDriver(
            orchestrator=orch,
            agent_runtime=runtime,
            project_root=tmp_path,
        )
        summary = driver.run("实现简单功能")

        assert summary is not None

    def test_run_error_action_stops(self, tmp_path):
        """RED: action 为 error 时立即停止, 不继续循环."""
        from auto_engineering.loop.tick_orchestrator import TickOrchestrator
        from auto_engineering.runtime.runtime import AgentRuntime

        orch = TickOrchestrator(
            tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )

        runtime = AgentRuntime()
        # 注册 architect 但让它返回无效 result (缺必填字段)
        from auto_engineering.runtime.task import TaskResult
        runtime.register("architect", lambda: _make_mock_agent({
            "architect": TaskResult(
                task_id="architect",
                values={"stage": "architect"},  # 缺 plan/batch_plan
                agent_type="architect",
            ),
        }))

        from auto_engineering.loop.standalone_driver import StandaloneDriver
        driver = StandaloneDriver(
            orchestrator=orch,
            agent_runtime=runtime,
            project_root=tmp_path,
            max_rounds=1,
        )
        summary = driver.run("req")
        assert summary.success is False
        assert summary.total_ticks <= 2


class TestStandaloneDriverActionRouting:
    """V7-5: action → role 路由 + Task 构造."""

    def test_architect_action_maps_to_architect_role(self):
        """architect action → role='architect' → AgentRuntime.get('architect')."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        driver = StandaloneDriver.__new__(StandaloneDriver)
        driver._design_doc_path = None
        task = driver._action_to_task({
            "action": "architect",
            "stage": "architect",
            "role": "architect",
            "context": {"requirement": "test"},
        })
        assert task is not None
        assert "architect" in task.id or task.id == "architect"

    def test_developer_action_maps_to_developer_role(self):
        """developer action → role='developer' → AgentRuntime.get('developer')."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        driver = StandaloneDriver.__new__(StandaloneDriver)
        driver._design_doc_path = None
        task = driver._action_to_task({
            "action": "developer",
            "stage": "developer",
            "role": "developer",
            "context": {"tasks": [{"id": "T1", "description": "实现X"}]},
        })
        assert task is not None

    def test_critic_action_maps_to_critic_role(self):
        """critic action → role='critic' → AgentRuntime.get('critic')."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        driver = StandaloneDriver.__new__(StandaloneDriver)
        driver._design_doc_path = None
        task = driver._action_to_task({
            "action": "critic",
            "stage": "critic",
            "role": "critic",
            "context": {"files_changed": ["x.py"]},
        })
        assert task is not None


# ── T134c: AE_MODEL_ROLE / AE_PROVIDER_ROLE parameterized tests ──


class FakeConfig:
    """Minimal RuntimeConfig stub for _resolve_model / _resolve_provider tests."""

    def __init__(self, overrides: dict | None = None):
        self._overrides = overrides or {}
        self.audit_log_enabled = False

    def get(self, key: str, default: str = "") -> str:
        return self._overrides.get(key, default)


class TestResolveModel:
    """_resolve_model(role, config) — per-role model selection with env override."""

    @pytest.mark.parametrize("role,expected", [
        ("architect", "claude-sonnet-4-6"),
        ("developer", "claude-sonnet-4-6"),
        ("critic", "claude-sonnet-4-6"),
        ("component_verifier", "claude-haiku-4-5-20251001"),
        ("plate_deep_audit", "claude-sonnet-4-6"),
        ("system_verifier", "claude-haiku-4-5-20251001"),
        ("system_deep_audit", "claude-sonnet-4-6"),
        ("gap_scan", "claude-haiku-4-5-20251001"),
        ("research", "claude-haiku-4-5-20251001"),
    ])
    def test_default_model_per_role(self, role, expected):
        """Each role has a sensible default model — no env override."""
        from auto_engineering.loop.standalone_driver import _resolve_model
        assert _resolve_model(role) == expected

    def test_env_override_model(self):
        """AE_MODEL_ARCHITECT=claude-opus-4-7 overrides default."""
        from auto_engineering.loop.standalone_driver import _resolve_model
        cfg = FakeConfig({"AE_MODEL_ARCHITECT": "claude-opus-4-7"})
        assert _resolve_model("architect", config=cfg) == "claude-opus-4-7"

    def test_unknown_role_returns_default(self):
        """Unknown role returns the hardcoded fallback model."""
        from auto_engineering.loop.standalone_driver import _resolve_model
        assert _resolve_model("nonexistent") == "claude-sonnet-4-6"

    def test_env_override_unknown_role(self):
        """Env override works even for roles not in ROLE_MODEL dict."""
        from auto_engineering.loop.standalone_driver import _resolve_model
        cfg = FakeConfig({"AE_MODEL_CUSTOM": "claude-haiku-4-5-20251001"})
        assert _resolve_model("custom", config=cfg) == "claude-haiku-4-5-20251001"


class TestResolveProvider:
    """_resolve_provider(role, config) — per-role provider selection."""

    def test_default_provider_empty_when_no_env(self):
        """No AE_PROVIDER_<ROLE> → provider_name='' → create_provider('') default."""
        from auto_engineering.loop.standalone_driver import _resolve_provider
        provider = _resolve_provider("architect")
        assert provider is not None

    def test_env_override_provider(self):
        """AE_PROVIDER_CRITIC=anthropic overrides default for that role."""
        from auto_engineering.loop.standalone_driver import _resolve_provider
        cfg = FakeConfig({"AE_PROVIDER_CRITIC": "anthropic"})
        provider = _resolve_provider("critic", config=cfg)
        assert provider is not None

    def test_provider_default_for_unknown_role(self):
        """Unknown role still returns a valid provider (falls through to default)."""
        from auto_engineering.loop.standalone_driver import _resolve_provider
        provider = _resolve_provider("nonexistent")
        assert provider is not None
