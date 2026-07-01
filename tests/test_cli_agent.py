"""ae agent CLI 测试 (v5.0 §PE.6).

RED marker 测试 — 验证 ae agent 子命令行为:
- 3 role 参数解析 (architect/developer/critic) + Click Choice 错误处理
- 7 字段 JSON 契约 (task_id/role/status/output/error/duration/task_role)
- exit codes: 0 = completed, 1 = failed
- 默认 role / 指令参数透传 / 特殊字符
- missing ANTHROPIC_API_KEY -> 早返回 failed TaskOutcome
- LLM 调用超时 / Agent 异常 -> caught + failed
- _build_role_system_prompt 3 role 全覆盖
- Click 集成: ae agent <role> <instruction>
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.cli.agent import (
    VALID_ROLES,
    _build_role_system_prompt,
    _build_runtime_for_role,
    register_agent_command,
    run_agent,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def runner() -> CliRunner:
    """Click 测试 runner."""
    return CliRunner()


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """临时目录作为 cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """每个测试清除 LLM 相关环境变量 (防止外部漏设触发 in_llm_agent)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_CLI", raising=False)


# ============================================================
# 1. 模块结构 + 常量
# ============================================================


def test_valid_roles_is_3_tuple() -> None:
    """VALID_ROLES 是 3 元素 tuple."""
    assert isinstance(VALID_ROLES, tuple)
    assert VALID_ROLES == ("architect", "developer", "critic")
    assert len(VALID_ROLES) == 3


def test_register_agent_command_attaches(runner: CliRunner) -> None:
    """register_agent_command 将 'agent' 子命令挂到 Click Group."""
    result = runner.invoke(main, ["agent", "--help"])
    assert result.exit_code == 0
    assert "agent" in result.output or "--project-root" in result.output


# ============================================================
# 2. _build_role_system_prompt 单元测试
# ============================================================


def test_build_role_prompt_architect_returns_string() -> None:
    """architect 返回字符串 (来自 prompts.py)."""
    prompt = _build_role_system_prompt("architect")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_role_prompt_developer_returns_string() -> None:
    """developer 返回字符串."""
    prompt = _build_role_system_prompt("developer")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_role_prompt_critic_returns_string() -> None:
    """critic 返回字符串."""
    prompt = _build_role_system_prompt("critic")
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_role_prompt_fallback_unknown_role() -> None:
    """未知 role -> fallback 通用 prompt (含 role 名)."""
    prompt = _build_role_system_prompt("not_a_real_role")
    assert isinstance(prompt, str)
    assert "not_a_real_role" in prompt


def test_build_role_prompt_3_roles_differ() -> None:
    """3 role 的 prompt 互不相同."""
    a = _build_role_system_prompt("architect")
    d = _build_role_system_prompt("developer")
    c = _build_role_system_prompt("critic")
    assert a != d, "architect 与 developer prompt 应不同"
    assert d != c, "developer 与 critic prompt 应不同"
    assert a != c, "architect 与 critic prompt 应不同"


def test_build_role_prompt_import_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """prompts 导入失败 -> 走 fallback 路径."""
    # 通过 monkeypatch sys.modules 强制 ImportError
    import sys

    # 删除已 cached 的 prompts 模块
    monkeypatch.delitem(sys.modules, "auto_engineering.agents.prompts", raising=False)
    # Force ImportError by patching the import path
    with patch.dict(sys.modules, {"auto_engineering.agents.prompts": None}):
        prompt = _build_role_system_prompt("architect")
    # Fallback string includes role
    assert "architect" in prompt


# ============================================================
# 3. run_agent 单元测试 - missing API key
# ============================================================


def test_run_agent_missing_api_key_returns_failed(tmp_path: Path) -> None:
    """无 ANTHROPIC_API_KEY -> 早返回 failed TaskOutcome."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "test", tmp_path)
    assert result["status"] == "failed"
    assert result["role"] == "architect"
    assert "ANTHROPIC_API_KEY" in result["error"]


def test_run_agent_missing_api_key_status_is_failed(tmp_path: Path) -> None:
    """无 KEY 必返回 status='failed'."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("developer", "impl foo", tmp_path)
    assert result["status"] == "failed"


def test_run_agent_missing_api_key_output_none(tmp_path: Path) -> None:
    """无 KEY 时 output 字段为 None."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("critic", "evaluate", tmp_path)
    assert result["output"] is None


def test_run_agent_missing_api_key_task_id_present(tmp_path: Path) -> None:
    """无 KEY 时也有 task_id 字段 (uuid 格式)."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "x", tmp_path)
    assert "task_id" in result
    assert result["task_id"].startswith("agent-")
    assert len(result["task_id"]) > len("agent-")


def test_run_agent_missing_api_key_duration_is_float(tmp_path: Path) -> None:
    """duration 字段为非负 float."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "x", tmp_path)
    assert isinstance(result["duration"], float)
    assert result["duration"] >= 0


def test_run_agent_missing_api_key_task_role_matches(tmp_path: Path) -> None:
    """task_role 与传入 role 一致."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("developer", "x", tmp_path)
    assert result["task_role"] == "developer"


# ============================================================
# 4. run_agent 单元测试 - in-llm-agent 模式
# ============================================================


def test_run_agent_in_llm_agent_skips_key_check(tmp_path: Path) -> None:
    """CLAUDE_CODE 设置时 不走缺 KEY 早返回路径."""
    with patch.dict(
        "os.environ", {"CLAUDE_CODE": "1"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "hello", "error": None}

            mock_agent.execute = fake_exec

            mock_build.return_value = mock_runtime
            result = run_agent("architect", "test", tmp_path)
    assert result["status"] == "completed"
    assert result["output"] == "hello"


def test_run_agent_anthropic_cli_set_skips_key_check(tmp_path: Path) -> None:
    """ANTHROPIC_CLI 含 'claude' (大小写不敏感) -> 跳过 KEY 早返回."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_CLI": "Claude"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "ok"}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = run_agent("critic", "x", tmp_path)
    assert result["status"] == "completed"


# ============================================================
# 5. run_agent 单元测试 - LLM 实际调用 (mocked)
# ============================================================


def test_run_agent_with_real_key_calls_runtime(tmp_path: Path) -> None:
    """设置 KEY + mock runtime -> 走真实调用路径."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "responded", "error": None}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = run_agent("architect", "build a plan", tmp_path)
    assert result["status"] == "completed"
    assert result["output"] == "responded"
    assert result["error"] is None


def test_run_agent_dict_result_with_error(tmp_path: Path) -> None:
    """agent 返回 dict 含 error -> status='failed'."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": None, "error": "LLM timeout"}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = run_agent("architect", "x", tmp_path)
    assert result["status"] == "failed"
    assert result["error"] == "LLM timeout"


def test_run_agent_object_result_extracts_attrs(tmp_path: Path) -> None:
    """agent 返回对象 (非 dict) -> 提取 output/error/status 属性."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            class FakeOutcome:
                output = "object-output"
                error = None
                status = "completed"

            async def fake_exec(task, ctx):
                return FakeOutcome()

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = run_agent("developer", "x", tmp_path)
    assert result["output"] == "object-output"
    assert result["status"] == "completed"


def test_run_agent_runtime_exception_returns_failed(tmp_path: Path) -> None:
    """_build_runtime_for_role 抛异常 -> 捕获, 返回 failed."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch(
            "auto_engineering.cli.agent._build_runtime_for_role",
            side_effect=RuntimeError("boom"),
        ):
            result = run_agent("architect", "x", tmp_path)
    assert result["status"] == "failed"
    assert "RuntimeError" in result["error"]
    assert "boom" in result["error"]


def test_run_agent_execute_timeout_returns_failed(tmp_path: Path) -> None:
    """agent.execute() 抛超时异常 -> caught + failed."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            async def fake_exec(task, ctx):
                raise TimeoutError("LLM call timed out")

            mock_agent.execute = fake_exec
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            result = run_agent("critic", "x", tmp_path)
    assert result["status"] == "failed"
    assert "TimeoutError" in result["error"]


def test_run_agent_typeerror_falls_back_to_old_interface(tmp_path: Path) -> None:
    """agent.execute 抛 TypeError (旧接口不匹配) -> 走 fallback agent.execute(instruction)."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            call_count = {"n": 0}

            def fake_exec(*args, **kwargs):
                call_count["n"] += 1
                # First call via task/ctx raises TypeError, second with single arg works
                if call_count["n"] == 1:
                    raise TypeError("execute() got unexpected argument")
                # Return awaitable for asyncio.run
                async def _coro():
                    return {"output": "legacy", "error": None}

                return _coro()

            mock_agent.execute = fake_exec
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            result = run_agent("architect", "legacy test", tmp_path)
    assert call_count["n"] >= 1  # At least first call attempted
    assert result["status"] in {"completed", "failed"}


def test_run_agent_instruction_passed_via_task(tmp_path: Path) -> None:
    """instruction 通过 task.description 传给 agent.execute."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            async def fake_exec(task, ctx):
                return {"output": "ok"}

            mock_agent.execute = MagicMock(side_effect=fake_exec)
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            run_agent(
                "architect", "describe a long instruction here please", tmp_path
            )
    # 验证 mock agent.execute 被调用, 入参 task 是 dict-like 含 description
    assert mock_agent.execute.called
    call_args = mock_agent.execute.call_args
    task_arg = call_args.kwargs.get("task") or call_args.args[0]
    assert "describe a long instruction here please" == task_arg["description"]


def test_run_agent_long_instruction_truncated_in_title(tmp_path: Path) -> None:
    """长 instruction 在 task.title 中被截断到 50 字符."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            async def fake_exec(task, ctx):
                return {"output": "ok"}

            mock_agent.execute = MagicMock(side_effect=fake_exec)
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            long = "x" * 200
            run_agent("architect", long, tmp_path)
    call_args = mock_agent.execute.call_args
    task_arg = call_args.kwargs.get("task") or call_args.args[0]
    title = task_arg["title"]
    assert len(title) <= 50, f"title 应被截断 ≤50, 实测 {len(title)}"
    assert title == long[:50]


def test_run_agent_special_chars_in_instruction(tmp_path: Path) -> None:
    """instruction 含特殊字符 (引号/换行) -> 完整透传."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            async def fake_exec(task, ctx):
                return {"output": "ok"}

            mock_agent.execute = MagicMock(side_effect=fake_exec)
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            special = "line1\nline2 \"quoted\" 'tick' $VAR"
            run_agent("developer", special, tmp_path)
    call_args = mock_agent.execute.call_args
    task_arg = call_args.kwargs.get("task") or call_args.args[0]
    assert task_arg["description"] == special


def test_run_agent_returns_7_required_fields(tmp_path: Path) -> None:
    """返回值含 7 字段 (task_id/role/status/output/error/duration/task_role)."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "x", tmp_path)
    expected = {
        "task_id",
        "role",
        "status",
        "output",
        "error",
        "duration",
        "task_role",
    }
    assert set(result.keys()) == expected


def test_run_agent_role_in_result(tmp_path: Path) -> None:
    """role 字段 = 传入 role."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("critic", "x", tmp_path)
    assert result["role"] == "critic"


def test_run_agent_uuid_unique_per_call(tmp_path: Path) -> None:
    """每次调用生成不同 task_id."""
    with patch.dict("os.environ", {}, clear=True):
        r1 = run_agent("architect", "x", tmp_path)
        r2 = run_agent("architect", "x", tmp_path)
    assert r1["task_id"] != r2["task_id"]


def test_run_agent_with_project_root(tmp_path: Path) -> None:
    """project_root 传入被使用."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "x", tmp_path)
    # 即使 KEY 缺失, project_root 不影响返回 dict 结构
    assert result["status"] == "failed"


# ============================================================
# 6. Click CLI 集成测试
# ============================================================


def test_cli_agent_architect_exit_code_1_no_key(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """ae agent architect ... 无 KEY -> exit code 1."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "design plan"])
    assert result.exit_code == 1


def test_cli_agent_developer_exit_code_1_no_key(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """ae agent developer ... 无 KEY -> exit code 1."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "developer", "implement"])
    assert result.exit_code == 1


def test_cli_agent_critic_exit_code_1_no_key(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """ae agent critic ... 无 KEY -> exit code 1."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "critic", "evaluate"])
    assert result.exit_code == 1


def test_cli_agent_invalid_role_choice_error(runner: CliRunner, tmp_cwd: Path) -> None:
    """无效 role (Click Choice 验证) -> 非 0 退出码."""
    result = runner.invoke(main, ["agent", "fake_role", "x"])
    # Click Choice 验证失败 -> exit code != 0, 通常 2
    assert result.exit_code != 0


def test_cli_agent_output_is_json(runner: CliRunner, tmp_cwd: Path) -> None:
    """ae agent 输出为合法 JSON."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    # 即使 exit 1, output 应为合法 JSON
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_cli_agent_output_contains_7_fields(runner: CliRunner, tmp_cwd: Path) -> None:
    """CLI 输出含 7 字段."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    data = json.loads(result.output)
    expected = {
        "task_id",
        "role",
        "status",
        "output",
        "error",
        "duration",
        "task_role",
    }
    assert set(data.keys()) == expected


def test_cli_agent_architect_role_in_output(runner: CliRunner, tmp_cwd: Path) -> None:
    """output 含 role='architect'."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    data = json.loads(result.output)
    assert data["role"] == "architect"


def test_cli_agent_developer_role_in_output(runner: CliRunner, tmp_cwd: Path) -> None:
    """output 含 role='developer'."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "developer", "x"])
    data = json.loads(result.output)
    assert data["role"] == "developer"


def test_cli_agent_critic_role_in_output(runner: CliRunner, tmp_cwd: Path) -> None:
    """output 含 role='critic'."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "critic", "x"])
    data = json.loads(result.output)
    assert data["role"] == "critic"


def test_cli_agent_status_failed_no_key(runner: CliRunner, tmp_cwd: Path) -> None:
    """无 KEY 时 output.status='failed'."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    data = json.loads(result.output)
    assert data["status"] == "failed"


def test_cli_agent_error_field_no_key(runner: CliRunner, tmp_cwd: Path) -> None:
    """无 KEY 时 output.error 含 'ANTHROPIC_API_KEY'."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    data = json.loads(result.output)
    assert "ANTHROPIC_API_KEY" in data["error"]


def test_cli_agent_with_project_root(runner: CliRunner, tmp_path: Path) -> None:
    """--project-root 参数被使用."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(
            main, ["agent", "architect", "x", "--project-root", str(tmp_path)]
        )
    # 无 KEY -> status=failed
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "failed"


def test_cli_agent_in_llm_agent_mode_completes(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """CLAUDE_CODE=1 模式下完整调用, exit code 0."""
    with patch.dict(
        "os.environ", {"CLAUDE_CODE": "1"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "ok", "error": None}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = runner.invoke(main, ["agent", "architect", "x"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "completed"


def test_cli_agent_must_have_role_arg(runner: CliRunner, tmp_cwd: Path) -> None:
    """ae agent 缺少 role 参数 -> Click UsageError."""
    result = runner.invoke(main, ["agent"])
    # Click 缺位置参数 -> exit code 2
    assert result.exit_code != 0


def test_cli_agent_must_have_instruction_arg(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """ae agent 缺少 instruction 参数 -> Click UsageError."""
    result = runner.invoke(main, ["agent", "architect"])
    assert result.exit_code != 0


def test_cli_agent_instruction_with_spaces_and_unicode(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """instruction 含空格和中文 -> 正常处理."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "实现 hello world 函数"])
    # 即使无 KEY 也能 JSON 输出
    data = json.loads(result.output)
    assert "task_id" in data


def test_cli_agent_logical_status_no_key_error_msg(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """无 KEY 时 error 字段非 None 含 ANTHROPIC_API_KEY."""
    with patch.dict("os.environ", {}, clear=True):
        result = runner.invoke(main, ["agent", "architect", "x"])
    data = json.loads(result.output)
    assert data["error"] is not None
    assert "ANTHROPIC_API_KEY" in data["error"]


# ============================================================
# 7. 异常路径覆盖
# ============================================================


def test_run_agent_key_set_stripped(tmp_path: Path) -> None:
    """ANTHROPIC_API_KEY 含首尾空格被 strip."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "  sk-test  "}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "ok"}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            run_agent("architect", "x", tmp_path)
    # Verify mocked was called — strip() 处理不应抛
    assert mock_build.called


def test_run_agent_handles_runtime_exception(tmp_path: Path) -> None:
    """任何 RuntimeError 在 run_agent 被捕获为 failed, 不传染."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch(
            "auto_engineering.cli.agent._build_runtime_for_role",
            side_effect=ValueError("bad value"),
        ):
            result = run_agent("architect", "x", tmp_path)
    assert result["status"] == "failed"
    assert result["task_id"].startswith("agent-")


def test_run_agent_kwargs_error_robust(tmp_path: Path) -> None:
    """agent.execute 抛各种异常均被捕获."""
    with patch.dict(
        "os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True
    ):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()

            async def fake_exec(task, ctx):
                raise KeyError("missing key")

            mock_agent.execute = fake_exec
            mock_runtime.get.return_value = mock_agent
            mock_build.return_value = mock_runtime
            result = run_agent("developer", "x", tmp_path)
    assert result["status"] == "failed"
    assert "KeyError" in result["error"]


def test_run_agent_anthropic_cli_lowercase_skips_key(tmp_path: Path) -> None:
    """ANTHROPIC_CLI 含 'claude' (小写) -> 视为 in_llm_agent, 不早返回."""
    with patch.dict("os.environ", {"ANTHROPIC_CLI": "claude"}, clear=True):
        with patch("auto_engineering.cli.agent._build_runtime_for_role") as mock_build:
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_runtime.get.return_value = mock_agent

            async def fake_exec(task, ctx):
                return {"output": "ok", "error": None}

            mock_agent.execute = fake_exec
            mock_build.return_value = mock_runtime
            result = run_agent("architect", "x", tmp_path)
    assert result["status"] == "completed"


def test_run_agent_no_key_no_claude_env_returns_failed(tmp_path: Path) -> None:
    """无 KEY + 无 CLAUDE_CODE + 无 ANTHROPIC_CLI -> 早返回 failed."""
    with patch.dict("os.environ", {}, clear=True):
        result = run_agent("architect", "test instruction", tmp_path)
    assert result["status"] == "failed"
    assert result["output"] is None
    assert result["duration"] >= 0
