"""Plugin-Engine stdout JSON 契约 + 子命令契约测试 (v5.6).

Phase 07+ 所有模块已实现, 测试验证 CLI 契约而非 ImportError。

覆盖范围 (v5.6 CLI 子命令全集 + JSON 契约):
    - ae doctor         环境预检 (7 行 ✓/✗)
    - ae gate-check     Gate 检查 (--all / --quick)
    - ae agent          单 Agent 调用 (architect/developer/critic)
    - ae dev-loop       stdout JSON 契约 (6 字段)
    - ae status         JSON recent_history (7 字段)
    - exit codes        0=completed, 1=config_error, 2=gate_unrecoverable, 130=SIGINT
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ============================================================
# 辅助工具: subprocess 调用 CLI (不污染 cwd, 隔离 state)
# ============================================================


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_shared_skill_describes_multi_worker_prompt_and_receipt_protocol() -> None:
    text = (
        REPO_ROOT / "skills" / "auto-engineering" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "spawn.agents[i].prompt" in text
    assert "spawn.agents[i].receipt_path" in text
    assert "workers must not write the shared total proof" in text
    assert "action.subagent_prompt` 原样传递给每个子代理" not in text


def test_claude_command_uses_same_multi_worker_protocol() -> None:
    text = (REPO_ROOT / "commands" / "dev-loop.md").read_text(encoding="utf-8")

    assert "spawn.agents[i].prompt" in text
    assert "spawn.agents[i].receipt_path" in text


def _run_cli(*args: str, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """运行 ae CLI 子进程 — 通过 ae 入口点.

    Returns:
        CompletedProcess (capture stdout/stderr, returncode).
    """
    import shutil

    # 优先项目 .venv/bin/ae (当前开发版), 避免命中全局旧版安装 (~/.local/bin/ae) —
    # which("ae") 会解析到 PATH 中的陈旧全局 ae, 导致契约测试实际测旧版而非当前代码。
    venv_ae = REPO_ROOT / ".venv" / "bin" / "ae"
    ae_bin = str(venv_ae) if venv_ae.exists() else (shutil.which("ae") or sys.executable)
    return subprocess.run(
        [ae_bin, *args],
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

    def test_ae_doctor_project_profile_setup_required(self, tmp_path: Path) -> None:
        """空项目应报告 setup_required，而不是缺失 Init 安装故障。"""
        result = _run_cli("doctor", cwd=tmp_path)
        assert "ProjectProfile setup_required" in result.stdout
        assert "请先运行 Init Engineering" not in result.stdout

    def test_ae_doctor_init_manifest_present(self, tmp_path: Path) -> None:
        """当 .ae-state/init-manifest.json 存在 (完整 schema) → 应报 ✓ (mock)."""
        ae_state = tmp_path / ".ae-state"
        ae_state.mkdir()
        manifest = ae_state / "init-manifest.json"
        # v5.0 §IL.2 完整 manifest (含 structure + conventions 必需字段)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "project_type": "app-service",
                    "language": "python",
                    "structure": {
                        "source_root": "src/",
                        "test_root": "tests/",
                        "config_files": ["pyproject.toml"],
                        "entry_point": "src/main.py",
                    },
                    "conventions": {
                        "linter": "ruff",
                        "type_checker": "pyright",
                        "test_runner": "pytest",
                    },
                }
            )
        )
        result = _run_cli("doctor", cwd=tmp_path)
        profile_line = [ln for ln in result.stdout.splitlines() if "ProjectProfile legacy" in ln]
        assert len(profile_line) == 1
        assert profile_line[0].startswith("✓"), f"profile line should be ✓: {profile_line[0]}"


# ============================================================
# ae gate-check 测试
# ============================================================


# Phase 40: ae gate-check 和 ae agent 已删除 — 测试已移除


# ============================================================
# ae dev-loop stdout JSON 契约
# ============================================================


class TestDevLoopJSON:
    """ae dev-loop --init — v6 tick action JSON 契约 (BEACON #39/#2)."""

    def test_ae_dev_loop_init_action_json_schema(self) -> None:
        """--init 输出首个 action JSON, 含 v6 tick 契约字段.

        v5.6 起 dev-loop 为离散 tick 调用 (BEACON #39 替换 v5.5 一次性
        --format json; CLAUDE.md v5.1 起 CLI 子进程模式废弃)。--init 由 Python
        构造首 action, 不调 LLM, 无需 API key。
        """
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            subprocess.run(["git", "init"], cwd=tdir, capture_output=True, timeout=10)
            result = _run_cli(
                "dev-loop", "noop", "--init", "--max-rounds", "1",
                cwd=tdir, timeout=60,
            )
        # --init 输出单行 compact action JSON。逐行找含 thread_id+action 的 dict。
        data = None
        for ln in result.stdout.splitlines():
            ln = ln.strip()
            if not (ln.startswith("{") and ln.endswith("}")):
                continue
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "thread_id" in obj and "action" in obj:
                data = obj
                break
        if data is None:
            pytest.fail(
                f"no action JSON with thread_id+action in stdout:\n"
                f"{result.stdout[:500]}\nstderr={result.stderr[:300]}"
            )
        required = {"tick", "stage", "thread_id", "action", "gate_summary"}
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
        # 准备完整环境 (有完整 manifest, 有 api_key, ...)
        ae_state = tmp_path / ".ae-state"
        ae_state.mkdir()
        (ae_state / "init-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "project_type": "app-service",
                    "language": "python",
                    "structure": {
                        "source_root": "src/",
                        "test_root": "tests/",
                        "config_files": [],
                        "entry_point": "src/main.py",
                    },
                    "conventions": {
                        "linter": "ruff",
                        "type_checker": "pyright",
                        "test_runner": "pytest",
                    },
                }
            )
        )
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
        assert result.returncode == 1, (
            f"expected 1 (preflight fail), got {result.returncode}:\nstderr={result.stderr[:200]}"
        )

    def test_exit_code_130_sigint(self) -> None:
        """SIGINT 退出码契约: 验证 classify_error 映射 (TASK_CANCELLED → 130)."""
        # 间接验证: classify_error 对 TASK_CANCELLED 应返回 exit 130
        from auto_engineering.cli.helpers import classify_error
        from auto_engineering.errors import AEError, ErrorCode

        err = AEError(ErrorCode.TASK_CANCELLED, "用户取消")
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

    def test_ae_gate_check_not_registered(self) -> None:
        """Phase 40: ae gate-check 已删除 — 确认不可用."""
        from click.testing import CliRunner

        from auto_engineering.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["gate-check", "--help"])
        assert result.exit_code != 0, f"ae gate-check should NOT be registered: {result.output}"

    def test_ae_agent_not_registered(self) -> None:
        """Phase 40: ae agent 已删除 — 确认不可用."""
        from click.testing import CliRunner

        from auto_engineering.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["agent", "--help"])
        assert result.exit_code != 0, f"ae agent should NOT be registered: {result.output}"

    def test_ae_status_registered(self) -> None:
        """Phase 40: ae status 必须保留."""
        from click.testing import CliRunner

        from auto_engineering.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0, f"ae status not registered: {result.output}"


# ============================================================
# T28: /auto-engineering:audit 命令内化 (B14 零外部运行时依赖)
# ============================================================


class TestAuditCommandInternalized:
    """T28/B14: commands/audit.md 不得依赖外部通用 /audit 运行时 (自含 AuditGate)."""

    def _audit_md(self) -> str:
        p = REPO_ROOT / "commands" / "audit.md"
        assert p.exists(), "commands/audit.md 缺失"
        return p.read_text(encoding="utf-8")

    def test_no_superpowers_generic_audit_delegation(self) -> None:
        """不得含 '执行通用 /audit' 委托 (Superpowers 运行时依赖, 违反 B14)."""
        text = self._audit_md()
        assert "执行通用" not in text, "audit.md 仍委托外部通用 /audit (运行时依赖未移除)"
        assert "通用 `/audit` 的 Phase" not in text

    def test_delegates_to_own_gate_and_stage(self) -> None:
        """内化: 委托项目自有 AuditGate + system_deep_audit 方法论."""
        text = self._audit_md()
        assert "AuditGate" in text
        assert "system_deep_audit" in text
        assert "recount_findings" in text  # Python 侧确定性求值 (§B6.7a)

    def test_declares_zero_external_runtime_dependency(self) -> None:
        """显式声明自含 / 不依赖外部 /audit 运行时."""
        text = self._audit_md()
        assert "不依赖任何外部 `/audit` 运行时" in text or "自含" in text
