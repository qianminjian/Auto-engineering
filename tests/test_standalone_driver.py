"""Tests for StandaloneDriver — V7-5 Driver B standalone execution.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.

Driver B: 进程内 AgentRuntime 调 LLM → 回喂 tick_dict → 循环至收敛.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
        task = driver._action_to_task({
            "action": "critic",
            "stage": "critic",
            "role": "critic",
            "context": {"files_changed": ["x.py"]},
        })
        assert task is not None
