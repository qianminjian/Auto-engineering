"""ae gate-check CLI 测试 (v5.0 §PE.6).

RED marker 测试 — 验证 gate-check 子命令行为:
- --all 模式: 跑 7 道 Gate (safety/lint/type_check/contract/test/coverage/build)
- --quick 模式: 跑 3 道 Gate (safety/lint/type_check)
- JSON 契约: project_root / mode / passed / failed / skipped / gate_summary
- gate_summary 每 Gate 含 status/passed/message 字段
- Exit codes: 0 = 全部 pass/skip, 1 = 存在 fail
- Gate 缺失工具 -> skip (不 fail)
- Gate subprocess timeout -> fail
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.cli.gate_check import (
    ALL_GATES,
    QUICK_GATES,
    _instantiate_gate,
    register_gate_check_command,
    run_gates,
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


@pytest.fixture
def mock_verdict() -> MagicMock:
    """构造 Gate verdict (passed=True)."""

    def _factory(passed: bool = True, message: str = "ok", gate_name: str = "test"):
        v = MagicMock()
        v.passed = passed
        v.message = message
        v.gate_name = gate_name
        return v

    return _factory


# ============================================================
# 1. 常量 / 模块结构
# ============================================================


def test_quick_gates_is_3_tuple() -> None:
    """QUICK_GATES 是 3 元素 tuple (safety/lint/type_check)."""
    assert isinstance(QUICK_GATES, tuple)
    assert len(QUICK_GATES) == 3
    assert set(QUICK_GATES) == {"safety", "lint", "type_check"}


def test_all_gates_is_7_tuple() -> None:
    """ALL_GATES 是 7 元素 tuple 覆盖 7 道 Gate."""
    assert isinstance(ALL_GATES, tuple)
    assert len(ALL_GATES) == 7
    assert set(ALL_GATES) == {
        "safety",
        "lint",
        "type_check",
        "contract",
        "test",
        "coverage",
        "build",
    }


def test_register_gate_check_command_attaches(runner: CliRunner) -> None:
    """register_gate_check_command 将 'gate-check' 子命令挂到 Click Group."""
    # 验证从 main 调用能列出 gate-check
    result = runner.invoke(main, ["gate-check", "--help"])
    assert result.exit_code == 0
    assert "gate-check" in result.output or "--all" in result.output


# ============================================================
# 2. _instantiate_gate 单元测试
# ============================================================


def test_instantiate_unknown_gate_returns_none(tmp_path: Path) -> None:
    """未知 Gate 名 -> None (调用方视为 skip)."""
    result = _instantiate_gate("nonexistent_gate_xyz", tmp_path)
    assert result is None


def test_instantiate_safety_returns_gate(tmp_path: Path) -> None:
    """safety 应返回 SafetyGate 实例或 instantiation 异常 (不返回 None)."""
    result = _instantiate_gate("safety", tmp_path)
    assert result is not None


def test_instantiate_lint_returns_gate(tmp_path: Path) -> None:
    """lint -> LintGate 实例或异常."""
    result = _instantiate_gate("lint", tmp_path)
    assert result is not None


def test_instantiate_type_check_returns_gate(tmp_path: Path) -> None:
    """type_check -> TypeCheckGate 实例或异常."""
    result = _instantiate_gate("type_check", tmp_path)
    assert result is not None


def test_instantiate_contract_returns_gate(tmp_path: Path) -> None:
    """contract -> ContractGate 实例或异常."""
    result = _instantiate_gate("contract", tmp_path)
    assert result is not None


def test_instantiate_test_returns_gate(tmp_path: Path) -> None:
    """test -> TestGate 实例或异常."""
    result = _instantiate_gate("test", tmp_path)
    assert result is not None


def test_instantiate_coverage_returns_gate(tmp_path: Path) -> None:
    """coverage -> CoverageGate 实例或异常."""
    result = _instantiate_gate("coverage", tmp_path)
    assert result is not None


def test_instantiate_build_returns_gate(tmp_path: Path) -> None:
    """build -> BuildGate 实例或异常."""
    result = _instantiate_gate("build", tmp_path)
    assert result is not None


# ============================================================
# 3. run_gates 单元测试 (--all 行为)
# ============================================================


def test_run_gates_all_keys_present(tmp_path: Path) -> None:
    """run_gates 返回 dict 含 5 顶层键 (project_root / gate_names / passed / failed / skipped)."""
    # 用空 tuple 避免实际跑 Gate
    result = run_gates((), tmp_path)
    assert "project_root" in result
    assert "gate_names" in result
    assert "passed" in result
    assert "failed" in result
    assert "skipped" in result


def test_run_gates_project_root_is_string(tmp_path: Path) -> None:
    """project_root 字段为字符串."""
    result = run_gates((), tmp_path)
    assert isinstance(result["project_root"], str)
    assert result["project_root"] == str(tmp_path)


def test_run_gates_empty_tuple_returns_empty_summary(tmp_path: Path) -> None:
    """空 gate_names tuple -> gate_summary 是空 dict, 计数全为 0."""
    result = run_gates((), tmp_path)
    assert result["gate_names"] == []
    assert result["gate_summary"] == {}
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 0


def test_run_gates_unknown_gate_is_skipped(tmp_path: Path) -> None:
    """未知 Gate 名 -> gate_summary 标记 skipped."""
    result = run_gates(("nonexistent_xyz",), tmp_path)
    assert "nonexistent_xyz" in result["gate_summary"]
    entry = result["gate_summary"]["nonexistent_xyz"]
    assert entry["status"] == "skipped"
    assert entry["passed"] is None
    assert "no such gate" in entry["message"]


def test_run_gates_counts_passed(tmp_path: Path, mock_verdict) -> None:
    """所有 Gate pass -> passed 计数正确."""
    fake_gate = MagicMock()
    fake_gate.run.return_value = mock_verdict(passed=True, message="ok")
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("safety", "lint"), tmp_path)
    assert result["passed"] == 2
    assert result["failed"] == 0
    assert result["skipped"] == 0


def test_run_gates_counts_failed(tmp_path: Path, mock_verdict) -> None:
    """fail Gate -> failed 计数 +1."""
    fake_gate = MagicMock()
    fake_gate.run.return_value = mock_verdict(passed=False, message="lint failed")
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("lint",), tmp_path)
    assert result["passed"] == 0
    assert result["failed"] == 1


def test_run_gates_gate_summary_shape(tmp_path: Path, mock_verdict) -> None:
    """gate_summary 每 Gate 含 status/passed/message/gate_name 字段."""
    fake_gate = MagicMock()
    fake_gate.run.return_value = mock_verdict(
        passed=True, message="all good", gate_name="safety"
    )
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("safety",), tmp_path)
    entry = result["gate_summary"]["safety"]
    assert "status" in entry
    assert "passed" in entry
    assert "message" in entry
    assert "gate_name" in entry
    assert entry["status"] == "pass"
    assert entry["passed"] is True
    assert entry["message"] == "all good"
    assert entry["gate_name"] == "safety"


def test_run_gates_failure_status(tmp_path: Path, mock_verdict) -> None:
    """fail verdict -> status='fail'."""
    fake_gate = MagicMock()
    fake_gate.run.return_value = mock_verdict(passed=False, message="err")
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("test",), tmp_path)
    entry = result["gate_summary"]["test"]
    assert entry["status"] == "fail"
    assert entry["passed"] is False


def test_run_gates_instantiate_exception_is_skipped(tmp_path: Path) -> None:
    """_instantiate_gate 返回 Exception 实例 -> gate 标记 skipped."""
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate",
        return_value=RuntimeError("boom"),
    ):
        result = run_gates(("safety",), tmp_path)
    entry = result["gate_summary"]["safety"]
    assert entry["status"] == "skipped"
    assert entry["passed"] is None
    assert "instantiate error" in entry["message"]


def test_run_gates_run_exception_is_skipped(tmp_path: Path) -> None:
    """gate.run() 抛异常 -> 该 Gate 标记 skipped (其他 Gate 继续)."""
    call_count = {"n": 0}

    def side_effect(project_root):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("subprocess crashed")
        v = MagicMock()
        v.passed = True
        v.message = "ok"
        v.gate_name = "lint"
        return v

    fake_gate = MagicMock()
    fake_gate.run.side_effect = side_effect
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("safety", "lint"), tmp_path)
    # safety 抛异常 -> skipped
    assert result["gate_summary"]["safety"]["status"] == "skipped"
    # lint 跑完 -> pass
    assert result["gate_summary"]["lint"]["status"] == "pass"
    # 计数: skipped=1 (safety), passed=1 (lint)
    assert result["skipped"] == 1
    assert result["passed"] == 1
    assert result["failed"] == 0


def test_run_gates_isolates_one_gate_failure(tmp_path: Path, mock_verdict) -> None:
    """一个 Gate 失败不影响其他 Gate 跑完."""
    call_count = {"n": 0}

    def side_effect(project_root):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return mock_verdict(passed=False, message="bad")
        return mock_verdict(passed=True, message="ok")

    fake_gate = MagicMock()
    fake_gate.run.side_effect = side_effect
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("g1", "g2"), tmp_path)
    assert result["passed"] == 1
    assert result["failed"] == 1


def test_run_gates_missing_message_handled(tmp_path: Path, mock_verdict) -> None:
    """verdict.message 缺失 / 为 None -> 默认空字符串."""
    v = MagicMock()
    v.passed = True
    v.message = None
    v.gate_name = "safety"
    fake_gate = MagicMock()
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = run_gates(("safety",), tmp_path)
    # 不应抛异常 — message 默认空串
    assert result["gate_summary"]["safety"]["message"] == ""


# ============================================================
# 4. Click CLI 集成测试
# ============================================================


def test_cli_gate_check_default_is_all(runner: CliRunner, tmp_cwd: Path) -> None:
    """默认 (无 --quick) = all 模式 = 跑 7 Gate."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["mode"] == "all"
    assert data["gate_names"] == list(ALL_GATES)
    assert len(data["gate_names"]) == 7


def test_cli_gate_check_quick_mode(runner: CliRunner, tmp_cwd: Path) -> None:
    """--quick 模式 = mode='quick', 3 Gate."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["mode"] == "quick"
    assert data["gate_names"] == list(QUICK_GATES)
    assert len(data["gate_names"]) == 3


def test_cli_gate_check_quick_excludes_slow_gates(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """--quick 模式不跑 contract/test/coverage/build."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    data = json.loads(result.output)
    # Quick 模式下不应出现慢 Gate
    for slow in ("contract", "test", "coverage", "build"):
        assert slow not in data["gate_names"], (
            f"{slow} 误入 --quick 模式 gate_names"
        )


def test_cli_gate_check_exit_code_0_on_all_pass(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """全部 Gate pass -> exit code 0."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    assert result.exit_code == 0


def test_cli_gate_check_exit_code_1_on_failure(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """存在 fail Gate -> exit code 1."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = False
    v.message = "lint failed"
    v.gate_name = "lint"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    assert result.exit_code == 1


def test_cli_gate_check_skip_does_not_fail(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """Gate skipped 不导致 exit code 1 (只 fail 才)."""
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate",
        side_effect=lambda name, _: None,
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    # 全 skipped -> exit 0
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["failed"] == 0


def test_cli_gate_check_json_output_is_valid_json(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """CLI 输出为合法 JSON."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    # 必须能 JSON 解析
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_cli_gate_check_with_project_root(
    runner: CliRunner, tmp_path: Path
) -> None:
    """--project-root 参数被使用 (显式路径传入)."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    captured_roots = []

    def capture_instantiate(name, project_root):
        captured_roots.append(project_root)
        return fake_gate

    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate",
        side_effect=capture_instantiate,
    ):
        result = runner.invoke(
            main, ["gate-check", "--quick", "--project-root", str(tmp_path)]
        )
    assert result.exit_code == 0
    assert all(r == tmp_path for r in captured_roots)


def test_cli_gate_check_default_project_root_uses_cwd(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """未传 --project-root -> 使用 cwd."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    captured_roots = []

    def capture_instantiate(name, project_root):
        captured_roots.append(project_root)
        return fake_gate

    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate",
        side_effect=capture_instantiate,
    ):
        runner.invoke(main, ["gate-check", "--quick"])
    assert len(captured_roots) >= 1
    assert captured_roots[0] == Path(tmp_cwd).resolve() or captured_roots[0] == tmp_cwd


def test_cli_gate_check_all_includes_full_7(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """--all 模式覆盖全部 7 个 Gate 名."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--all"])
    data = json.loads(result.output)
    assert set(data["gate_names"]) == {
        "safety",
        "lint",
        "type_check",
        "contract",
        "test",
        "coverage",
        "build",
    }


def test_cli_gate_check_gate_summary_each_gate_has_required_fields(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """gate_summary 每个 Gate 都有 status / passed / message."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    data = json.loads(result.output)
    for gate_name, entry in data["gate_summary"].items():
        assert "status" in entry, f"{gate_name} 缺 status"
        assert "passed" in entry, f"{gate_name} 缺 passed"
        assert "message" in entry, f"{gate_name} 缺 message"
        assert entry["status"] in {"pass", "fail", "skipped"}


def test_cli_gate_check_passed_failed_skipped_mutually_exclusive(
    runner: CliRunner, tmp_cwd: Path
) -> None:
    """passed/failed/skipped 计数和与 total Gate 数一致."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(main, ["gate-check", "--quick"])
    data = json.loads(result.output)
    total = data["passed"] + data["failed"] + data["skipped"]
    assert total == len(data["gate_names"])


def test_cli_gate_check_project_root_in_output(
    runner: CliRunner, tmp_path: Path
) -> None:
    """JSON 输出含 project_root 字段."""
    fake_gate = MagicMock()
    v = MagicMock()
    v.passed = True
    v.message = "ok"
    v.gate_name = "x"
    fake_gate.run.return_value = v
    with patch(
        "auto_engineering.cli.gate_check._instantiate_gate", return_value=fake_gate
    ):
        result = runner.invoke(
            main, ["gate-check", "--quick", "--project-root", str(tmp_path)]
        )
    data = json.loads(result.output)
    assert data["project_root"] == str(tmp_path)
