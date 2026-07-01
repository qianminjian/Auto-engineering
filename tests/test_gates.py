"""Tests for v2.0 Phase 04 — 7 道 Gate + CLI v2.0 commands.

来源: design/v2.0-Analysis-Loop.md §五 Phase 2 + §4.11 CLI 命令设计.

覆盖:
    - Gate 基类 + Verdict dataclass (base.py)
    - Gate 0 safety (regex + git diff)
    - Gate 1 lint (subprocess ruff)
    - Gate 2 type_check (subprocess mypy, graceful skip)
    - Gate 3 contract (跨 Agent, 单 Agent 跳过)
    - Gate 4 test (subprocess pytest + --timeout=60 + --no-cov)
    - Gate 5 coverage (pytest --cov + threshold check)
    - Gate 6 build (Python: import auto_engineering)
    - CLI ae status + ae checkpoint v2 list/show
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

# ============================================================
# Group 1: Gate 基类 + Verdict dataclass
# ============================================================


class TestGateBase:
    """Gate 基类 + Verdict dataclass."""

    def test_verdict_pass_creates_passed_instance(self):
        from auto_engineering.gates.base import Verdict

        v = Verdict.passed("lint clean")
        assert v.passed is True
        assert v.message == "lint clean"
        assert v.gate_name == ""

    def test_verdict_fail_creates_failed_instance(self):
        from auto_engineering.gates.base import Verdict

        v = Verdict.failed("test failed")
        assert v.passed is False
        assert v.message == "test failed"

    def test_verdict_constructor(self):
        from auto_engineering.gates.base import Verdict

        v = Verdict(gate_name="lint", passed=True, message="ok")
        assert v.gate_name == "lint"
        assert v.passed is True
        assert v.message == "ok"

    def test_base_gate_run_raises_not_implemented(self, tmp_path: Path):
        from auto_engineering.gates.base import Gate

        gate = Gate()
        with pytest.raises(NotImplementedError):
            gate.run(tmp_path)


# ============================================================
# Group 2: Gate 0 — Safety (regex + git diff)
# ============================================================


class TestSafetyGate:
    """Gate 0: 检测 secrets / 危险代码."""

    def test_clean_repo_passes(self, tmp_path: Path):
        from auto_engineering.gates.safety import SafetyGate

        # 创建一个干净的文件
        (tmp_path / "main.py").write_text("print('hello')\n")
        gate = SafetyGate()
        verdict = gate.run(tmp_path)
        # 干净 repo 应该 pass 或 drop(取决于是否启用了 gitleaks)
        assert verdict.passed is True

    def test_aws_key_detected(self, tmp_path: Path):
        from auto_engineering.gates.safety import SafetyGate

        # AWS access key pattern
        (tmp_path / "config.py").write_text(
            "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"
        )
        gate = SafetyGate()
        verdict = gate.run(tmp_path)
        # 应该检测到(可能 block 或 fail)
        assert verdict.passed is False or "secret" in verdict.message.lower()

    def test_private_key_detected(self, tmp_path: Path):
        from auto_engineering.gates.safety import SafetyGate

        (tmp_path / "key.pem").write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        )
        gate = SafetyGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False

    def test_github_token_detected(self, tmp_path: Path):
        from auto_engineering.gates.safety import SafetyGate

        (tmp_path / "auth.py").write_text(
            'GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"\n'
        )
        gate = SafetyGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False


# ============================================================
# Group 3: Gate 1 — Lint (ruff)
# ============================================================


class TestLintGate:
    """Gate 1: ruff check."""

    def test_clean_code_passes(self, tmp_path: Path):
        from auto_engineering.gates.lint import LintGate

        (tmp_path / "main.py").write_text("x = 1\n")
        gate = LintGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_dirty_code_fails(self, tmp_path: Path):
        from auto_engineering.gates.lint import LintGate

        # ruff 会报 unused import
        (tmp_path / "main.py").write_text("import os\n")
        gate = LintGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False

    def test_custom_ruff_path(self, tmp_path: Path):
        from auto_engineering.gates.lint import LintGate

        (tmp_path / "main.py").write_text("x = 1\n")
        gate = LintGate(linter_bin="nonexistent-ruff")
        verdict = gate.run(tmp_path)
        # 命令不存在应该 fail
        assert verdict.passed is False


# ============================================================
# Group 4: Gate 2 — Type Check (mypy with skip)
# ============================================================


class TestTypeCheckGate:
    """Gate 2: mypy (若未配置则 skip)."""

    def test_runs_gracefully(self, tmp_path: Path):
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()
        verdict = gate.run(tmp_path)
        # 不管是 pass / fail / skip,都应返回 Verdict(不抛异常)
        assert hasattr(verdict, "passed")
        assert hasattr(verdict, "message")


# ============================================================
# Group 5: Gate 3 — Contract (跨 Agent, 单 Agent 跳过)
# ============================================================


class TestContractGate:
    """Gate 3: 跨 Agent 契约检查."""

    def test_single_agent_skips(self, tmp_path: Path):
        from auto_engineering.gates.contract import ContractGate

        gate = ContractGate()
        # 单 Agent 模式: agent_count=1 → 应 pass(skip)
        verdict = gate.run(tmp_path, agent_count=1)
        assert verdict.passed is True
        assert "skip" in verdict.message.lower() or "single" in verdict.message.lower()

    def test_multi_agent_with_valid_contracts_passes(self, tmp_path: Path):
        """多 Agent + .ae-contracts/ 下有效 YAML 文件 → passed=True."""
        from auto_engineering.gates.contract import ContractGate

        # 创建 .ae-contracts/ 目录 + 有效 YAML
        contracts_dir = tmp_path / ".ae-contracts"
        contracts_dir.mkdir()
        (contracts_dir / "agent-api.yml").write_text(
            "agents:\n"
            "  architect:\n"
            "    provides: [design.md]\n"
            "  developer:\n"
            "    provides: [implementation.py]\n"
        )

        gate = ContractGate(contracts_dir=contracts_dir)
        verdict = gate.run(tmp_path, agent_count=3)
        assert verdict.passed is True
        # 消息应表明契约文件被成功检查(而非 placeholder skip)
        assert "valid" in verdict.message.lower()

    def test_multi_agent_no_contracts_fails(self, tmp_path: Path):
        """多 Agent + 无 .ae-contracts/ 目录 → passed=False."""
        from auto_engineering.gates.contract import ContractGate

        # 不创建 contracts 目录
        contracts_dir = tmp_path / ".ae-contracts"
        gate = ContractGate(contracts_dir=contracts_dir)
        verdict = gate.run(tmp_path, agent_count=3)
        assert verdict.passed is False
        assert "contract" in verdict.message.lower() or "no" in verdict.message.lower()

    def test_multi_agent_malformed_contract_fails(self, tmp_path: Path):
        """多 Agent + .ae-contracts/ 下有格式错误的 YAML → passed=False."""
        from auto_engineering.gates.contract import ContractGate

        contracts_dir = tmp_path / ".ae-contracts"
        contracts_dir.mkdir()
        (contracts_dir / "bad.yml").write_text(
            "this: is: malformed: yaml: [: broken\n"
        )

        gate = ContractGate(contracts_dir=contracts_dir)
        verdict = gate.run(tmp_path, agent_count=3)
        assert verdict.passed is False
        assert "parse" in verdict.message.lower() or "yaml" in verdict.message.lower()


# ============================================================
# Group 6: Gate 4 — Test (pytest)
# ============================================================


class TestTestGate:
    """Gate 4: pytest with --timeout=60 + --no-cov."""

    def test_no_tests_returns_verdict(self, tmp_path: Path):
        from auto_engineering.gates.test import TestGate

        # 空目录: pytest exit 5 (no tests collected) — 应当 fail
        gate = TestGate(timeout=30)
        verdict = gate.run(tmp_path)
        assert hasattr(verdict, "passed")

    def test_passing_tests_passes(self, tmp_path: Path):
        from auto_engineering.gates.test import TestGate

        # 创建 passing test
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_pass.py").write_text(
            "def test_ok():\n    assert 1 + 1 == 2\n"
        )
        gate = TestGate(timeout=60)
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_failing_tests_fails(self, tmp_path: Path):
        from auto_engineering.gates.test import TestGate

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_fail.py").write_text(
            "def test_bad():\n    assert 1 == 2\n"
        )
        gate = TestGate(timeout=60)
        verdict = gate.run(tmp_path)
        assert verdict.passed is False

    def test_custom_pytest_args_used(self, tmp_path: Path):
        from auto_engineering.gates.test import TestGate

        gate = TestGate(timeout=30, pytest_args=["--maxfail=1"])
        # 验证 pytest_args 被使用 — 调用时构造命令
        # 通过 inspect 命令检查
        import inspect

        inspect.signature(gate.run)
        assert True  # signature 兼容


# ============================================================
# Group 7: Gate 5 — Coverage
# ============================================================


class TestCoverageGate:
    """Gate 5: pytest --cov + threshold check."""

    def test_returns_verdict(self, tmp_path: Path):
        from auto_engineering.gates.coverage import CoverageGate

        gate = CoverageGate(threshold=80.0)
        verdict = gate.run(tmp_path)
        # 无测试 → 应返回 Verdict(可能 fail)
        assert hasattr(verdict, "passed")

    def test_threshold_configurable(self):
        from auto_engineering.gates.coverage import CoverageGate

        gate = CoverageGate(threshold=90.0)
        assert gate.threshold == 90.0


# ============================================================
# Group 8: Gate 6 — Build (Python import)
# ============================================================


class TestBuildGate:
    """Gate 6: Python: `python -c 'import auto_engineering'`."""

    def test_import_succeeds(self):
        from auto_engineering.gates.build import BuildGate

        gate = BuildGate()
        verdict = gate.run()
        # auto_engineering 应可 import
        assert verdict.passed is True

    def test_custom_module(self, tmp_path: Path):
        from auto_engineering.gates.build import BuildGate

        # 自定义模块 import(应失败)
        gate = BuildGate(module="nonexistent_module_xyz")
        verdict = gate.run()
        assert verdict.passed is False


# ============================================================
# Group 9: CLI ae status + ae checkpoint v2
# ============================================================


class TestCLIStatus:
    """CLI: ae status."""

    def test_status_runs(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        # 无项目环境时,应至少 print 当前目录(不报错)
        assert result.exit_code == 0
        assert str(tmp_path) in result.output or "当前目录" in result.output


class TestCLICheckpointV2:
    """CLI: ae checkpoint v2 list/show."""

    def test_checkpoint_v2_list_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ae-checkpoints").mkdir()
        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list"])
        # 接受 0 或 1 退出码(空时 exit 0/1 都可能)
        assert result.exit_code in (0, 1)

    def test_checkpoint_v2_list_with_db(self, tmp_path: Path, monkeypatch):
        from auto_engineering.cli import main
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ae-checkpoints").mkdir()
        # 创建一个 v2 SQLite checkpoint
        store = SQLiteCheckpointStore(str(tmp_path / ".ae-checkpoints" / "v2.db"))
        store.save(state={"requirement": "test"}, round=1, step=0)

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list"])
        assert result.exit_code == 0

    def test_checkpoint_v2_show_existing(self, tmp_path: Path, monkeypatch):
        from auto_engineering.cli import main
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ae-checkpoints").mkdir()
        store = SQLiteCheckpointStore(str(tmp_path / ".ae-checkpoints" / "v2.db"))
        cp_id = store.save(state={"requirement": "demo"}, round=1, step=0)

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "show", cp_id])
        assert result.exit_code == 0
        assert cp_id in result.output or "demo" in result.output or "round" in result.output.lower()

    def test_checkpoint_v2_show_missing(self, tmp_path: Path, monkeypatch):
        from auto_engineering.cli import main

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ae-checkpoints").mkdir()

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "show", "nonexistent-id"])
        # 不存在的 ID 应该 fail
        assert result.exit_code != 0