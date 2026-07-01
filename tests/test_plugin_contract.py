"""Plugin-Engine stdout JSON 契约 + 子命令契约测试 (v5.0 M8).

RED marker: 以下模块/函数在 Phase 07 之前不存在, 测试应全部 FAIL (ImportError).

覆盖范围 (v5.0 §PE.6 CLI 子命令全集 + §B13.2 CLI JSON 契约):
    - ae doctor         环境预检 (7 行 ✓/✗)
    - ae gate-check     Gate 检查 (--all / --quick)
    - ae agent          单 Agent 调用 (architect/developer/critic)
    - ae dev-loop       stdout JSON 契约 (6 字段)
    - ae status         JSON recent_history (7 字段)
    - exit codes        0=completed, 1=config_error, 2=gate_unrecoverable, 130=SIGINT
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


# ============================================================
# 辅助工具: subprocess 调用 CLI (不污染 cwd, 隔离 state)
# ============================================================


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """运行 ae CLI 子进程 — 用 sys.executable 走 .venv.

    Returns:
        CompletedProcess (capture stdout/stderr, returncode).
    """
    return subprocess.run(
        [sys.executable, "-m", "auto_engineering", *args],
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ============================================================
# ae doctor 测试
# ============================================================


class TestDoctor:
    """ae doctor — 7 行 ✓/✗ 格式 + init-manifest 检查 (IL-AC-01)."""

    def test_ae_doctor_output_format(self, tmp_path: Path) -> None:
        """ae doctor 输出应包含 7 行 ✓ 或 ✗ 标记."""
        result = _run_cli("doctor", cwd=tmp_path)
        # 退出码 0 或 1 都允许 (取决于环境)
        assert result.returncode in (0, 1), f"unexpected exit: {result.returncode}\n{result.stderr}"
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        # 7 项检查: python/uv/git/sqlite3/api_key/ae_state/init_manifest
        assert len(lines) >= 7, f"expected ≥7 lines, got {len(lines)}:\n{result.stdout}"
        # 每行必须以 ✓ 或 ✗ 开头
        for ln in lines[:7]:
            assert ln.startswith("✓") or ln.startswith("✗"), f"bad line: {ln!r}"

    def test_ae_doctor_init_manifest_check(self, tmp_path: Path) -> None:
        """tmp_path 无 .ae-state/init-manifest.json → 应报 ✗ (IL-AC-01)."""
        result = _run_cli("doctor", cwd=tmp_path)
        # 至少应有一行提到 init-manifest
        assert "init-manifest" in result.stdout or "init_manifest" in result.stdout
        # 缺少 manifest → 退出码应为 1
        assert result.returncode == 1, f"expected exit 1 (missing init-manifest), got {result.returncode}"

    def test_ae_doctor_init_manifest_present(self, tmp_path: Path) -> None:
        """当 .ae-state/init-manifest.json 存在 → 应报 ✓ (mock)."""
        ae_state = tmp_path / ".ae-state"
        ae_state.mkdir()
        manifest = ae_state / "init-manifest.json"
        manifest.write_text(json.dumps({"schema_version": "1.0", "project_type": "app-service", "language": "python"}))
        result = _run_cli("doctor", cwd=tmp_path)
        # 找 init-manifest 行
        manifest_line = [ln for ln in result.stdout.splitlines() if "init-manifest" in ln]
        assert len(manifest_line) == 1
        assert manifest_line[0].startswith("✓"), f"manifest line should be ✓: {manifest_line[0]}"


# ============================================================
# ae gate-check 测试
# ============================================================


class TestGateCheck:
    """ae gate-check --all | --quick — 跑 Gate 集合, 输出 JSON gate_summary."""

    def test_ae_gate_check_all(self, tmp_path: Path) -> None:
        """ae gate-check --all 跑 7 道 Gate, 输出 JSON 含 gate_summary."""
        result = _run_cli("gate-check", "--all", cwd=tmp_path)
        # 退出码 0/1 都允许 (Gate 可能失败)
        assert result.returncode in (0, 1), f"unexpected exit: {result.returncode}"
        # 输出必须为有效 JSON
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"stdout not valid JSON: {e}\n{result.stdout[:200]}")
        # 必须含 gate_summary 字段
        assert "gate_summary" in data, f"missing gate_summary: {data}"
        # gate_summary 应含 safety/lint/type_check 三个核心 gate
        summary = data["gate_summary"]
        for gate in ("safety", "lint", "type_check"):
            assert gate in summary, f"missing gate {gate} in summary: {summary}"

    def test_ae_gate_check_quick(self, tmp_path: Path) -> None:
        """ae gate-check --quick 只跑 3 道 Gate (safety + lint + type_check)."""
        result = _run_cli("gate-check", "--quick", cwd=tmp_path)
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        summary = data["gate_summary"]
        # 至少 3 道
        assert len(summary) >= 3
        # 必须含 safety/lint/type_check
        for gate in ("safety", "lint", "type_check"):
            assert gate in summary
        # 排除项: coverage/build 不应出现
        assert "coverage" not in summary or summary.get("coverage", {}).get("status") == "skipped"
        assert "build" not in summary or summary.get("build", {}).get("status") == "skipped"


# ============================================================
# ae agent 测试
# ============================================================


class TestAgent:
    """ae agent <role> — 单 Agent 调用, 输出 TaskOutcome JSON."""

    def test_ae_agent_architect_call(self, tmp_path: Path) -> None:
        """ae agent architect <指令> 输出 TaskOutcome JSON."""
        result = _run_cli("agent", "architect", "分析需求", cwd=tmp_path)
        # 由于没真 LLM, 可能失败但 stdout 应为 JSON
        # 至少 JSON 解析应成功
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            # 没 stdout 也行, 但若有 stdout 必须是 JSON
            pytest.fail(f"stdout not JSON: {result.stdout[:200]}")
        # 期望字段
        expected_fields = {"task_id", "status", "role"}
        assert expected_fields.issubset(set(data.keys())), f"missing fields: {expected_fields - set(data.keys())}"


# ============================================================
# ae dev-loop stdout JSON 契约
# ============================================================


class TestDevLoopJSON:
    """ae dev-loop --log-format json — 6 字段 JSON 契约."""

    def test_ae_dev_loop_stdout_json_schema(self) -> None:
        """--log-format json 输出必须含 6 字段: status/thread_id/rounds/verdict/duration_sec/gate_summary."""
        result = _run_cli(
            "dev-loop",
            "noop",
            "--log-format", "json",
            "--max-rounds", "1",
        )
        # 即使 LLM 不可达, JSON 契约必须被尊重
        # 尝试解析最后一行 JSON
        json_lines = [ln for ln in result.stdout.splitlines() if ln.strip().startswith("{")]
        if not json_lines:
            pytest.fail(f"no JSON in stdout:\n{result.stdout[:500]}")
        # 找最后一行 JSON
        last = json_lines[-1]
        try:
            data = json.loads(last)
        except json.JSONDecodeError as e:
            pytest.fail(f"final line not valid JSON: {e}\n{last[:200]}")
        # 6 字段验证
        required = {"status", "thread_id", "rounds", "verdict", "duration_sec", "gate_summary"}
        missing = required - set(data.keys())
        assert not missing, f"missing fields: {missing}, got: {set(data.keys())}"


# ============================================================
# ae status JSON recent_history
# ============================================================


class TestStatusJSON:
    """ae status --format json — 7 字段 + recent_history × 5."""

    def test_ae_status_json_recent_history_5(self, tmp_path: Path) -> None:
        """ae status --format json 输出含 7 字段, recent_history ≤5 条."""
        result = _run_cli("status", "--format", "json", cwd=tmp_path)
        # 退出码 0 (无 checkpoint 时)
        try:
            data = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            pytest.fail(f"stdout not JSON: {result.stdout[:200]}")
        # 7 字段
        required = {
            "thread_id", "round", "stage", "verdict",
            "majors_in_a_row", "total_majors", "recent_history",
        }
        missing = required - set(data.keys())
        assert not missing, f"missing fields: {missing}, got: {set(data.keys())}"
        # recent_history 必须是 list 且长度 ≤ 5
        assert isinstance(data["recent_history"], list)
        assert len(data["recent_history"]) <= 5


# ============================================================
# exit codes 契约
# ============================================================


class TestExitCodes:
    """exit codes: 0=completed, 1=config_error, 2=gate_unrecoverable, 130=SIGINT."""

    def test_exit_code_0_completed(self, tmp_path: Path) -> None:
        """doctor 全 ✓ → exit 0."""
        # 准备完整环境 (有 manifest, 有 api_key, ...)
        ae_state = tmp_path / ".ae-state"
        ae_state.mkdir()
        (ae_state / "init-manifest.json").write_text(json.dumps({"schema_version": "1.0"}))
        # doctor 通常会检查 .ae-state 目录存在, 写一下保证可读写
        result = _run_cli("doctor", cwd=tmp_path, timeout=10)
        # 至少有 ✓ 标记
        if "✗" in result.stdout:
            # 缺关键检查项 (如 ANTHROPIC_API_KEY), 不算 0
            pytest.skip(f"environment not fully satisfied:\n{result.stdout}")
        assert result.returncode == 0, f"expected 0, got {result.returncode}:\n{result.stdout}"

    def test_exit_code_1_config_error(self, tmp_path: Path) -> None:
        """ae dev-loop 在非 git 仓库 → exit 1 (config_error / preflight fail)."""
        # tmp_path 不在 git 仓库内
        result = _run_cli("dev-loop", "test", "--max-rounds", "1", cwd=tmp_path, timeout=20)
        # preflight 失败 → SystemExit(1)
        assert result.returncode == 1, f"expected 1 (preflight fail), got {result.returncode}:\nstderr={result.stderr[:200]}"

    def test_exit_code_130_sigint(self) -> None:
        """SIGINT 退出码契约: 验证 classify_error 映射 (TASK_CANCELLED → 130)."""
        # 间接验证: classify_error 对 TASK_CANCELLED 应返回 exit 130
        from auto_engineering.cli.helpers import classify_error
        from auto_engineering.errors import AEError, ErrorCode

        err = AEError("用户取消", code=ErrorCode.TASK_CANCELLED)
        _category, exit_code = classify_error(err)
        assert exit_code == 130, f"expected 130 (SIGINT), got {exit_code}"


# ============================================================
# 子命令注册契约
# ============================================================


class TestSubcommandRegistration:
    """所有 6 个子命令必须注册到 ae CLI group."""

    def test_ae_doctor_registered(self) -> None:
        """ae doctor 子命令必须存在."""
        from click.testing import CliRunner

        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0, f"ae doctor not registered: {result.output}"
        assert "doctor" in result.output.lower()

    def test_ae_gate_check_registered(self) -> None:
        """ae gate-check 子命令必须存在."""
        from click.testing import CliRunner

        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["gate-check", "--help"])
        assert result.exit_code == 0, f"ae gate-check not registered: {result.output}"

    def test_ae_agent_registered(self) -> None:
        """ae agent 子命令必须存在."""
        from click.testing import CliRunner

        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["agent", "--help"])
        assert result.exit_code == 0, f"ae agent not registered: {result.output}"
