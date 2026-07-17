"""Tests for V7-2/3/4 + V7-5 StandaloneDriver integration.

V7-2: Execution Context (STAGE_TO_ROLE, ROLE_MODEL)
V7-3: Auth Source (AuthProvider)
V7-4: Checkpoint Decoupling (resume, close)
V7-5: Mock LLM integration tests (control flow without real API keys)

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ── V7-2: STAGE_TO_ROLE + ROLE_MODEL ──


class TestV7_2_StageToRoleMapping:
    """V7-2: STAGE_TO_ROLE — 10 stage 到 role 的映射."""

    def test_stage_to_role_exists(self) -> None:
        """STAGE_TO_ROLE 字典已定义."""
        from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE

        assert isinstance(STAGE_TO_ROLE, dict)

    def test_stage_to_role_covers_all_10_stages(self) -> None:
        """STAGE_TO_ROLE 覆盖所有 10 个 stage."""
        from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE

        expected_stages = {
            "gap_scan", "gap_review", "research",
            "architect", "developer", "critic",
            "component_verifier", "plate_deep_audit",
            "system_verifier", "system_deep_audit",
        }
        assert set(STAGE_TO_ROLE.keys()) == expected_stages

    def test_gap_review_maps_to_none(self) -> None:
        """gap_review → None (无 LLM role, headless auto-Defer)."""
        from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE

        assert STAGE_TO_ROLE["gap_review"] is None

    def test_architect_maps_to_architect(self) -> None:
        """architect → architect."""
        from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE

        assert STAGE_TO_ROLE["architect"] == "architect"

    def test_developer_maps_to_developer(self) -> None:
        """developer → developer."""
        from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE

        assert STAGE_TO_ROLE["developer"] == "developer"


class TestV7_2_RoleModelMapping:
    """V7-2: ROLE_MODEL — role 到模型名的映射, 支持环境变量覆盖."""

    def test_role_model_exists(self) -> None:
        """ROLE_MODEL 字典已定义."""
        from auto_engineering.loop.standalone_driver import ROLE_MODEL

        assert isinstance(ROLE_MODEL, dict)

    def test_role_model_covers_all_roles(self) -> None:
        """ROLE_MODEL 覆盖所有 LLM role (不含 gap_review)."""
        from auto_engineering.loop.standalone_driver import ROLE_MODEL

        expected_roles = {
            "gap_scan", "research", "architect", "developer", "critic",
            "component_verifier", "plate_deep_audit",
            "system_verifier", "system_deep_audit",
        }
        assert set(ROLE_MODEL.keys()) == expected_roles

    def test_env_var_override(self, monkeypatch) -> None:
        """AE_MODEL_ARCHITECT 环境变量覆盖默认模型."""
        from auto_engineering.loop.standalone_driver import _resolve_model

        monkeypatch.setenv("AE_MODEL_ARCHITECT", "claude-opus-4-7")
        model = _resolve_model("architect")
        assert model == "claude-opus-4-7"

    def test_env_var_not_set_uses_default(self, monkeypatch) -> None:
        """环境变量未设置时使用 ROLE_MODEL 默认值."""
        from auto_engineering.loop.standalone_driver import _resolve_model, ROLE_MODEL

        monkeypatch.delenv("AE_MODEL_ARCHITECT", raising=False)
        model = _resolve_model("architect")
        assert model == ROLE_MODEL["architect"]


# ── V7-3: AuthProvider ──


class TestV7_3_AuthProvider:
    """V7-3: AuthProvider 类型别名 + _resolve_auth_provider()."""

    def test_auth_provider_type_exists(self) -> None:
        """AuthProvider 类型别名已定义."""
        from auto_engineering.loop.standalone_driver import AuthProvider

        assert AuthProvider is not None

    def test_resolve_auth_returns_callable(self) -> None:
        """_resolve_auth_provider() 返回可调用对象."""
        from auto_engineering.loop.standalone_driver import _resolve_auth_provider

        provider = _resolve_auth_provider()
        assert callable(provider)

    def test_resolve_auth_returns_key(self, monkeypatch) -> None:
        """返回的 AuthProvider 调用后返回 API key."""
        from auto_engineering.loop.standalone_driver import _resolve_auth_provider

        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        provider = _resolve_auth_provider()
        assert provider() == "sk-ant-test"

    def test_auth_token_priority_over_api_key(self, monkeypatch) -> None:
        """ANTHROPIC_AUTH_TOKEN 优先于 ANTHROPIC_API_KEY."""
        from auto_engineering.loop.standalone_driver import _resolve_auth_provider

        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-123")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key-456")
        provider = _resolve_auth_provider()
        assert provider() == "token-123"

    def test_no_key_raises_aeeerror(self, monkeypatch) -> None:
        """无任何 key 时抛出 AEError."""
        from auto_engineering.loop.standalone_driver import _resolve_auth_provider

        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(Exception):
            _resolve_auth_provider()


# ── V7-4: Checkpoint/Resume Decoupling ──


class TestV7_4_StandaloneDriverResume:
    """V7-4: StandaloneDriver.resume() + close() + restore() driver-agnostic."""

    def test_standalone_driver_has_resume_method(self) -> None:
        """StandaloneDriver 有 resume 方法."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        assert hasattr(StandaloneDriver, "resume")
        assert callable(StandaloneDriver.resume)

    def test_standalone_driver_has_close_method(self) -> None:
        """StandaloneDriver 有 close 方法."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        assert hasattr(StandaloneDriver, "close")
        assert callable(StandaloneDriver.close)

    def test_restore_is_driver_agnostic(self) -> None:
        """TickOrchestrator.restore() 不依赖驱动类型 (无 driver 参数)."""
        import inspect

        from auto_engineering.loop.tick_orchestrator import TickOrchestrator

        sig = inspect.signature(TickOrchestrator.restore)
        params = list(sig.parameters.keys())
        # restore 参数不应包含任何 driver 相关概念
        assert "driver" not in str(params).lower()
        # restore 是 classmethod, inspect.signature 展开后无 cls 参数
        assert "project_root" in params

    def test_resume_accepts_checkpoint_id(self) -> None:
        """resume() 接受 checkpoint_id 参数."""
        import inspect

        from auto_engineering.loop.standalone_driver import StandaloneDriver

        sig = inspect.signature(StandaloneDriver.resume)
        assert "checkpoint_id" in sig.parameters

    def test_standalone_driver_init_stores_project_root(self) -> None:
        """StandaloneDriver.__init__ 存储 project_root."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from auto_engineering.loop.standalone_driver import StandaloneDriver

        mock_orch = MagicMock()
        mock_runtime = MagicMock()
        driver = StandaloneDriver(
            orchestrator=mock_orch,
            agent_runtime=mock_runtime,
            project_root=Path("/tmp/test"),
        )
        assert driver.project_root == Path("/tmp/test")


# ── V7-5: StandaloneDriver mock LLM integration tests ──


def _make_mock_agent(response_values: dict):
    """构造返回预定义 TaskResult 的 mock Agent."""
    from auto_engineering.runtime.task import TaskResult

    agent = MagicMock()
    agent.values = response_values

    async def _execute(task, ctx, cancellation=None, token_tracker=None):
        return TaskResult(
            task_id=task.id,
            values=response_values,
            agent_type="mock",
        )

    agent.execute = _execute
    return agent


def _make_mock_orch(actions: list[dict]):
    """构造返回预定义 action 序列的 mock TickOrchestrator.

    init() 返回第一个 action, tick_dict() 依次返回后续 action.
    """
    orch = MagicMock()
    call_count = {"count": 0}

    orch.init = MagicMock(return_value=actions[0])

    def _tick_dict(result):
        idx = min(call_count["count"] + 1, len(actions) - 1)
        call_count["count"] += 1
        return actions[idx]

    orch.tick_dict = _tick_dict
    orch._state = None
    return orch


class TestV7_5_RunLoopFromAction:
    """V7-5: _run_loop_from_action 控制流测试."""

    def test_done_action_returns_success(self) -> None:
        """done action 立即返回 success RunSummary."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        orch.tick_dict = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        import asyncio
        action = {"action": "done", "stage": "critic", "verdict": "APPROVE"}
        summary = asyncio.run(driver._run_loop_from_action(action))

        assert summary.success is True
        assert summary.total_ticks == 1
        assert summary.verdict == "APPROVE"
        assert summary.final_stage == "critic"

    def test_error_action_returns_failure(self) -> None:
        """error action 立即返回 failure RunSummary."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        import asyncio
        action = {"action": "error", "stage": "developer", "message": "test error"}
        summary = asyncio.run(driver._run_loop_from_action(action))

        assert summary.success is False
        assert "test error" in summary.error_message

    def test_max_iterations_stops(self) -> None:
        """超过 max_rounds*10 时停止循环."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        # tick_dict 永远返回非 done/error action
        orch.tick_dict = MagicMock(return_value={"action": "architect", "stage": "architect"})
        runtime = MagicMock()
        runtime.get = MagicMock(return_value=None)  # 没有注册 agent → auto-pass

        driver = StandaloneDriver(orch, runtime, Path("/tmp"), max_rounds=1)
        # max_rounds=1 → ceiling=10

        import asyncio
        action = {"action": "architect", "stage": "architect"}
        summary = asyncio.run(driver._run_loop_from_action(action))

        assert summary.success is False
        assert summary.total_ticks == 10
        assert "max iterations" in summary.error_message


class TestV7_5_ExecuteAction:
    """V7-5: _execute_action 任务构造 + Agent 调度测试."""

    def test_execute_action_with_mock_agent(self) -> None:
        """注册 mock architect agent, verify 任务构造与结果返回."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        orch._state = None
        runtime = MagicMock()

        mock_agent = _make_mock_agent({
            "stage": "architect",
            "plan": "## T1: Implement login\n- `src/login.py`\n- `tests/test_login.py`",
            "batch_plan": [
                {"batch_id": "T1", "file_targets": ["src/login.py", "tests/test_login.py"]}
            ],
            "file_list": ["src/login.py", "tests/test_login.py"],
            "contracts": [],
        })
        runtime.get = MagicMock(return_value=mock_agent)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "architect", "stage": "architect", "tick": 0,
            "context": {"requirement": "Implement login"},
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert "stage" in result
        assert result["stage"] == "architect"

    def test_execute_action_no_agent_returns_auto_pass(self) -> None:
        """未注册 agent 时返回 auto-pass stub."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        runtime.get = MagicMock(return_value=None)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "component_verifier", "stage": "component_verifier",
            "tick": 0, "context": {"component": "auth"},
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert result["stage"] == "component_verifier"
        assert "coverage_map" in result
        assert result["missing_count"] == 0

    def test_execute_critic_action_with_mock_agent(self) -> None:
        """critic action 构造正确的审查 prompt + output_schema."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()

        mock_agent = _make_mock_agent({
            "stage": "critic",
            "verdict": "APPROVE",
            "findings": [],
        })
        runtime.get = MagicMock(return_value=mock_agent)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "critic", "stage": "critic", "tick": 1,
            "context": {"files_changed": ["src/login.py"]},
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert result["stage"] == "critic"
        assert result["verdict"] == "APPROVE"
        assert result["findings"] == []


class TestV7_5_ExecuteDeveloperSerial:
    """V7-5: _execute_developer_serial 串行 TDD 执行."""

    def test_developer_serial_multiple_tasks(self) -> None:
        """多个 task 串行执行, 聚合 files_changed + test_results."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()

        call_log = []

        async def _execute_side_effect(task, ctx, cancellation=None, token_tracker=None):
            call_log.append(task.id)
            from auto_engineering.runtime.task import TaskResult
            return TaskResult(
                task_id=task.id,
                values={
                    "task_id": task.id,
                    "files_changed": [f"src/{task.id}.py"],
                    "test_results": {"passed": 2, "failed": 0},
                    "commit_hash": "a" * 40,
                },
                agent_type="developer",
            )

        mock_agent = MagicMock()
        mock_agent.execute = _execute_side_effect
        runtime.get = MagicMock(return_value=mock_agent)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "developer", "stage": "developer", "tick": 0,
            "batch_id": "T1",
            "context": {
                "tasks": [
                    {"id": "t1", "description": "Task 1", "file_targets": ["src/t1.py"]},
                    {"id": "t2", "description": "Task 2", "file_targets": ["src/t2.py"]},
                ],
            },
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        # 两个 task 都被执行
        assert len(call_log) == 2
        # 结果聚合
        assert result["stage"] == "developer"
        assert len(result["files_changed"]) == 2
        assert result["test_results"]["passed"] == 4
        assert result["test_results"]["failed"] == 0

    def test_developer_serial_stops_on_test_failure(self) -> None:
        """第一个 task 测试失败时停止后续 task."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()

        call_log = []

        async def _execute_side_effect(task, ctx, cancellation=None, token_tracker=None):
            call_log.append(task.id)
            from auto_engineering.runtime.task import TaskResult
            return TaskResult(
                task_id=task.id,
                values={
                    "task_id": task.id,
                    "files_changed": ["src/t1.py"],
                    "test_results": {"passed": 0, "failed": 1},
                },
                agent_type="developer",
            )

        mock_agent = MagicMock()
        mock_agent.execute = _execute_side_effect
        runtime.get = MagicMock(return_value=mock_agent)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "developer", "stage": "developer", "tick": 0,
            "batch_id": "T1",
            "context": {
                "tasks": [
                    {"id": "t1", "description": "Task 1"},
                    {"id": "t2", "description": "Task 2"},
                ],
            },
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        # 只有第一个 task 被执行 (第二个因 test failed 被 stop)
        assert len(call_log) == 1
        assert result["test_results"]["failed"] == 1


class TestV7_5_ExecuteGapReviewHeadless:
    """V7-5: _execute_gap_review_headless 无头自动 Defer."""

    def test_gap_review_headless_auto_defer(self) -> None:
        """无 research findings 时全部 gap 自动 Defer."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {
            "action": "gap_review", "stage": "gap_review",
            "gaps": [
                {"id": "gap-1", "grade": "major", "summary": "Missing auth spec"},
                {"id": "gap-2", "grade": "minor", "summary": "Missing error handling spec"},
            ],
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert result["stage"] == "gap_review"
        assert len(result["decisions"]) == 2
        assert all(d["resolution"] == "defer" for d in result["decisions"])

    def test_gap_review_with_research_fill(self) -> None:
        """有 research findings 时自动 Fill 对应的 gap."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {
            "action": "gap_review", "stage": "gap_review",
            "is_rereview": True,
            "gaps": [{"id": "gap-1", "grade": "major", "summary": "Missing auth spec"}],
            "research_findings": {
                "gap-1": {"recommended_design": "Use JWT with refresh tokens"},
            },
        }

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["resolution"] == "fill"
        assert "JWT" in result["decisions"][0]["fill_content"]

    def test_gap_review_empty_gaps(self) -> None:
        """空 gaps 返回空 decisions."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {"action": "gap_review", "stage": "gap_review", "gaps": []}

        import asyncio
        result = asyncio.run(driver._execute_action(action))

        assert result["stage"] == "gap_review"
        assert len(result["decisions"]) == 0


class TestV7_5_RunAsyncFullFlow:
    """V7-5: run_async 完整流程测试 (mock orchestrator + mock agent)."""

    def test_run_async_simple_architect_approve(self) -> None:
        """architect → critic APPROVE → done (最小 E2E)."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        orch.init = MagicMock(return_value={
            "action": "architect", "stage": "architect", "tick": 0,
            "context": {"requirement": "Add hello world tool"},
        })
        tick_calls = []

        def _tick_dict(result):
            tick_calls.append(result.get("stage"))
            stage = result.get("stage", "")
            if stage == "architect":
                return {"action": "critic", "stage": "critic", "tick": 1,
                        "context": {"files_changed": ["src/hello.py"]}}
            elif stage == "critic":
                return {"action": "done", "stage": "critic", "verdict": "APPROVE"}
            return {"action": "done", "stage": stage}

        orch.tick_dict = _tick_dict
        orch._state = None

        runtime = MagicMock()

        architect_agent = _make_mock_agent({
            "stage": "architect",
            "plan": "## Architecture Plan\n\n### T1: Hello World Tool\n"
                    "Implement a simple hello world tool that returns a greeting.\n"
                    "- `src/hello.py`: Core implementation\n"
                    "- `tests/test_hello.py`: Unit tests\n\n"
                    "### Architecture\n- Module: hello\n- Dependencies: none\n",
            "batch_plan": [{"batch_id": "T1", "file_targets": ["src/hello.py"]}],
            "file_list": ["src/hello.py"],
            "contracts": [],
        })
        critic_agent = _make_mock_agent({
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        })

        def _get(agent_type):
            if agent_type == "architect":
                return architect_agent
            elif agent_type == "critic":
                return critic_agent
            return None

        runtime.get = _get

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        import asyncio
        summary = asyncio.run(driver.run_async("Add hello world tool"))

        assert summary.success is True
        assert summary.verdict == "APPROVE"
        assert summary.final_stage == "critic"
        # architect (tick 1) → critic (tick 2) → done (tick 3)
        assert summary.total_ticks == 3

    def test_run_async_init_failure(self) -> None:
        """TickOrchestrator.init() 失败时返回 failure RunSummary."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        orch.init = MagicMock(side_effect=RuntimeError("init failed"))
        runtime = MagicMock()

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        import asyncio
        summary = asyncio.run(driver.run_async("test"))

        assert summary.success is False
        assert "init" in summary.error_message.lower()

    def test_run_async_with_verifier_pipeline(self) -> None:
        """architect → developer → critic → component_verifier → done (含验证层)."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        orch.init = MagicMock(return_value={
            "action": "architect", "stage": "architect", "tick": 0,
            "context": {"requirement": "Add hello tool"},
        })

        tick_calls = []

        def _tick_dict(result):
            tick_calls.append(result.get("stage"))
            stage = result.get("stage", "")
            next_map = {
                "architect": {"action": "developer", "stage": "developer", "tick": 1,
                              "batch_id": "T1", "context": {
                                  "tasks": [{"id": "t1", "description": "Implement",
                                             "file_targets": ["src/hello.py"]}],
                              }},
                "developer": {"action": "critic", "stage": "critic", "tick": 2,
                              "context": {"files_changed": ["src/hello.py"]}},
                "critic": {"action": "component_verifier", "stage": "component_verifier",
                           "tick": 3, "context": {"component": "hello"}},
                "component_verifier": {"action": "done", "stage": "component_verifier",
                                       "verdict": "GOAL_ACHIEVED"},
            }
            return next_map.get(stage, {"action": "done", "stage": stage})

        orch.tick_dict = _tick_dict
        orch._state = None

        runtime = MagicMock()

        architect_agent = _make_mock_agent({
            "stage": "architect",
            "plan": "## T1: Hello\n- `src/hello.py`",
            "batch_plan": [{"batch_id": "T1", "file_targets": ["src/hello.py"]}],
            "file_list": ["src/hello.py"], "contracts": [],
        })
        dev_agent = MagicMock()

        async def _dev_execute(task, ctx, cancellation=None, token_tracker=None):
            from auto_engineering.runtime.task import TaskResult
            return TaskResult(
                task_id=task.id,
                values={
                    "task_id": task.id, "batch_id": "T1",
                    "files_changed": ["src/hello.py"],
                    "test_results": {"passed": 2, "failed": 0},
                    "commit_hash": "b" * 40,
                },
                agent_type="developer",
            )

        dev_agent.execute = _dev_execute
        critic_agent = _make_mock_agent({
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        })

        def _get(agent_type):
            agents = {
                "architect": architect_agent,
                "developer": dev_agent,
                "critic": critic_agent,
            }
            return agents.get(agent_type)

        runtime.get = _get

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        import asyncio
        summary = asyncio.run(driver.run_async("Add hello tool"))

        assert summary.success is True
        assert summary.verdict == "GOAL_ACHIEVED"
        assert "architect" in tick_calls
        assert "developer" in tick_calls
        assert "critic" in tick_calls
        assert "component_verifier" in tick_calls


class TestV7_5_ExecuteSafeErrorHandling:
    """V7-5: _execute_action_safe 错误处理."""

    def test_execute_safe_catches_exception(self) -> None:
        """Agent execute 抛异常时 _execute_action_safe 优雅降级."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()

        async def _failing_execute(task, ctx, cancellation=None, token_tracker=None):
            raise RuntimeError("LLM API error")

        mock_agent = MagicMock()
        mock_agent.execute = _failing_execute
        runtime.get = MagicMock(return_value=mock_agent)

        driver = StandaloneDriver(orch, runtime, Path("/tmp"))
        action = {
            "action": "architect", "stage": "architect", "tick": 0,
            "context": {"requirement": "test"},
        }

        import asyncio
        result = asyncio.run(driver._execute_action_safe(action, []))

        # 不应抛异常, 应返回 error result
        assert isinstance(result, dict)
        assert result is not None


class TestV7_5_ActionToTask:
    """V7-5: _action_to_task 正确构造 Task."""

    def test_architect_action_to_task(self) -> None:
        """architect action → Task 含 requirement prompt."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {
            "action": "architect", "stage": "architect", "tick": 0,
            "context": {"requirement": "Implement login"},
        }

        task = driver._action_to_task(action)
        assert "Implement login" in task.description
        assert "architect" in task.id
        assert task.expected_output

    def test_critic_action_to_task_with_files(self) -> None:
        """critic action → Task 含文件列表."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {
            "action": "critic", "stage": "critic", "tick": 1,
            "context": {"files_changed": ["src/login.py", "tests/test_login.py"]},
        }

        task = driver._action_to_task(action)
        assert "src/login.py" in task.description
        assert task.output_schema is not None
        assert "verdict" in task.output_schema["required"]

    def test_unknown_action_uses_fallback(self) -> None:
        """未知 action type 使用 fallback task description."""
        from auto_engineering.loop.standalone_driver import StandaloneDriver

        orch = MagicMock()
        runtime = MagicMock()
        driver = StandaloneDriver(orch, runtime, Path("/tmp"))

        action = {
            "action": "unknown_stage", "stage": "unknown_stage", "tick": 0,
            "context": {},
        }

        task = driver._action_to_task(action)
        assert task.description  # 至少不是空
        assert task.expected_output
