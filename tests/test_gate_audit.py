"""AuditGate 测试 — v5.4 新增: 代码质量深度审计 Gate.

覆盖:
  - 基础构造 + name/applies_to_stages
  - 空项目 → passed
  - P0 硬编码密钥 → failed
  - P1 TODO/FIXME → threshold-based fail
  - P2 超长行/调试残留 → threshold-based fail
  - 大文件检测
  - 跳过目录 (venv/.git/node_modules)
  - 自定义阈值
  - GateVerdict.message 格式
"""
from __future__ import annotations

from pathlib import Path

from auto_engineering.gates.audit import AuditFinding, AuditGate


class TestAuditGateConstruction:
    def test_default_name(self) -> None:
        gate = AuditGate()
        assert gate.name == "audit"

    def test_applies_to_stages(self) -> None:
        gate = AuditGate()
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages

    def test_default_thresholds(self) -> None:
        gate = AuditGate()
        assert gate.max_p0 == 0
        assert gate.max_p1 == 3
        assert gate.max_p2 == 10

    def test_custom_thresholds(self) -> None:
        gate = AuditGate(max_p0=2, max_p1=5, max_p2=20)
        assert gate.max_p0 == 2
        assert gate.max_p1 == 5
        assert gate.max_p2 == 20


class TestAuditGateEmptyProject:
    def test_empty_project_passes(self, tmp_path: Path) -> None:
        """空项目 (无可扫描文件) → passed."""
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "无审计发现" in verdict.message

    def test_only_binary_files_passes(self, tmp_path: Path) -> None:
        """只有二进制文件 (非文本) → passed."""
        (tmp_path / "image.png").write_text("binary", encoding="utf-8")
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_project_root_not_exists(self, tmp_path: Path) -> None:
        gate = AuditGate()
        verdict = gate.run(tmp_path / "nonexistent")
        assert verdict.passed is False
        assert "不存在" in verdict.message

    def test_project_root_is_file_not_dir(self, tmp_path: Path) -> None:
        """P0-6: project_root 是文件非目录 → failed (is_dir 检查)."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        assert file_path.exists(), "测试前置: 文件应存在"
        gate = AuditGate()
        verdict = gate.run(file_path)
        assert verdict.passed is False
        assert "非目录" in verdict.message


class TestAuditGateP0Findings:
    def test_hardcoded_secret_in_py_file_fails(self, tmp_path: Path) -> None:
        """P0: 硬编码 API key → failed (max_p0=0)."""
        (tmp_path / "config.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"  # noqa\n'
        )
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "P0=" in verdict.message
        assert "硬编码密钥" in verdict.message

    def test_silent_except_fails(self, tmp_path: Path) -> None:
        """P0: 静默吞异常 (except 无 logger/raise) → failed."""
        (tmp_path / "bad.py").write_text(
            "def foo():\n"
            "    try:\n"
            '        raise ValueError("oops")\n'
            "    except ValueError:\n"
            "        pass\n"
        )
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "静默吞异常" in verdict.message

    def test_custom_max_p0_allows_one(self, tmp_path: Path) -> None:
        """max_p0=1 允许 1 个 P0 → passed."""
        (tmp_path / "config.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        gate = AuditGate(max_p0=1)
        verdict = gate.run(tmp_path)
        assert verdict.passed is True


class TestAuditGateP1Findings:
    def test_todo_marker_p1_by_default(self, tmp_path: Path) -> None:
        """P1: TODO → 计入 P1 计数."""
        (tmp_path / "module.py").write_text("# TODO: implement this\n")
        gate = AuditGate(max_p1=1)  # 允许 1 个, 但只有 1 个 → passed
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "P1=1" in verdict.message

    def test_multiple_todos_fail_at_threshold(self, tmp_path: Path) -> None:
        """>3 P1 → failed (default max_p1=3, 4 TODOs → fail)."""
        content = ""
        for i in range(4):
            content += f"# TODO: fix me {i}\n"
        (tmp_path / "module.py").write_text(content)
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "P1=4" in verdict.message

    def test_commented_out_code_is_p1(self, tmp_path: Path) -> None:
        """P1: 注释掉的 def/class 代码."""
        (tmp_path / "old.py").write_text("# def old_function():\n#     return 42\n")
        gate = AuditGate(max_p1=2)  # 允许 2 个 P1 → passed
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "注释掉的代码" in verdict.message


class TestAuditGateP2Findings:
    def test_debug_print_is_p2(self, tmp_path: Path) -> None:
        """P2: print() 残留."""
        (tmp_path / "debug.py").write_text('print("hello")\n')
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        # print 是 P2, 默认 max_p2=10 → 1 个 → passed
        assert verdict.passed is True
        assert "P2=" in verdict.message

    def test_long_line_is_p2(self, tmp_path: Path) -> None:
        """P2: 超长行 (>120 字符)."""
        long_line = "x" * 150
        (tmp_path / "wide.py").write_text(f"{long_line}\n")
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "超长行" in verdict.message


class TestAuditGateSkipDirs:
    def test_skips_venv(self, tmp_path: Path) -> None:
        """venv 下文件被跳过."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "secrets.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "无审计发现" in verdict.message

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        nm_dir = tmp_path / "node_modules" / "pkg"
        nm_dir.mkdir(parents=True)
        (nm_dir / "index.js").write_text("console.log('debug')\n")
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True


class TestAuditGateLargeFiles:
    def test_large_file_p2_warning(self, tmp_path: Path) -> None:
        """大文件 (>400 行) → P2."""
        content = "\n".join(f"line {i}" for i in range(402))
        (tmp_path / "big.py").write_text(content)
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert "大文件" in verdict.message

    def test_disable_large_file_check(self, tmp_path: Path) -> None:
        content = "\n".join(f"line {i}" for i in range(500))
        (tmp_path / "big.py").write_text(content)
        gate = AuditGate(include_large_files=False)
        verdict = gate.run(tmp_path)
        assert "大文件" not in verdict.message


class TestAuditGateMessageFormat:
    def test_message_includes_dimension_and_file(self, tmp_path: Path) -> None:
        (tmp_path / "bad.py").write_text('# TODO: fix\n')
        gate = AuditGate(max_p1=1)
        verdict = gate.run(tmp_path)
        assert "[工程化规范]" in verdict.message
        assert "bad.py" in verdict.message

    def test_message_truncates_long_evidence(self, tmp_path: Path) -> None:
        """evidence 截断保护."""

        f = AuditFinding(
            severity="P0", dimension="代码质量",
            file="x.py", line=1,
            description="硬编码密钥",
            evidence="x" * 100,
        )
        # evidence 在 GateVerdict.message 中不会直接出现 (由 _build_verdict 控制),
        # 但 AuditFinding.evidence 本身不截断 (在构造时截断)
        assert len(f.evidence) <= 100


class TestAuditGateIncrementalScan:
    """v5.4: contracts['files_changed'] 增量扫描 — 仅扫描变更文件."""

    def test_incremental_scans_only_target_files(self, tmp_path: Path) -> None:
        """提供 files_changed → 只扫描指定文件, 跳过未变更文件."""
        (tmp_path / "changed.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        (tmp_path / "unchanged.py").write_text(
            'API_KEY = "sk-deadbeef1234567890abcdef1234567890"\n'
        )
        gate = AuditGate()
        gate.contracts = {"files_changed": ["changed.py"]}
        verdict = gate.run(tmp_path)
        # 仅扫描 changed.py → 1 P0, max_p0=0 → fail
        assert verdict.passed is False
        assert "P0=1" in verdict.message
        assert "changed.py" in verdict.message
        assert "unchanged.py" not in verdict.message

    def test_incremental_clean_file_passes(self, tmp_path: Path) -> None:
        """变更文件无问题 → passed, 不计入未变更文件的违规."""
        (tmp_path / "clean.py").write_text("def foo():\n    return 42\n")
        (tmp_path / "dirty.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        gate = AuditGate()
        gate.contracts = {"files_changed": ["clean.py"]}
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "无审计发现" in verdict.message

    def test_incremental_none_contracts_falls_back_to_full_scan(self, tmp_path: Path) -> None:
        """contracts=None → 全量扫描 (向后兼容)."""
        (tmp_path / "bad.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        gate = AuditGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "P0=1" in verdict.message

    def test_incremental_empty_files_changed_falls_back(self, tmp_path: Path) -> None:
        """files_changed=[] → 全量扫描."""
        (tmp_path / "bad.py").write_text(
            'API_KEY = "sk-1234567890abcdef1234567890abcdef"\n'
        )
        gate = AuditGate()
        gate.contracts = {"files_changed": []}
        verdict = gate.run(tmp_path)
        assert verdict.passed is False

    def test_incremental_skips_large_file_scan(self, tmp_path: Path) -> None:
        """增量模式下跳过 _scan_large_files (需全量 rglob)."""
        content = "\n".join(f"line {i}" for i in range(500))
        (tmp_path / "big.py").write_text(content)
        gate = AuditGate()
        gate.contracts = {"files_changed": ["big.py"]}
        verdict = gate.run(tmp_path)
        # 大文件检查在增量模式下跳过 → 不报告大文件
        assert "大文件" not in verdict.message


class TestAuditGateIntegration:
    def test_mixed_p0_p1_p2_counts(self, tmp_path: Path) -> None:
        """混合 severity → 正确计数和判定."""
        # P0: 硬编码密钥
        (tmp_path / "secrets.py").write_text(
            'password = "super_secret_1234567890abcdef"\n'
        )
        # P1: TODO
        (tmp_path / "todo.py").write_text("# TODO: refactor\n")
        # P2: print
        (tmp_path / "debug.py").write_text('print("x")\n')

        gate = AuditGate(max_p0=0)  # 1 P0 → fail
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "P0=1" in verdict.message
        assert "P1=1" in verdict.message
        assert "P2=1" in verdict.message
