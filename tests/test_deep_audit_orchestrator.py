"""v5.5 — DeepAuditOrchestrator 单元测试.

测试 3-agent 并行审计编排器的文件收集、维度分配、报告合并.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from auto_engineering.loop.deep_audit import (
    AUDIT_DIMENSIONS,
    DeepAuditOrchestrator,
)


class TestDeepAuditOrchestratorInit:
    """初始化测试."""

    def test_init_with_valid_path(self):
        """应接受 Path 对象."""
        orch = DeepAuditOrchestrator(project_root=Path("/tmp"))
        assert orch is not None

    def test_init_with_str_path(self):
        """应接受字符串路径."""
        orch = DeepAuditOrchestrator(project_root="/tmp")
        assert orch is not None


class TestCollectFiles:
    """文件收集测试."""

    def test_collects_python_files(self):
        """应收集 .py 文件."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("# test")
            (root / "b.py").write_text("# test")
            (root / "sub").mkdir()
            (root / "sub" / "c.py").write_text("# test")

            orch = DeepAuditOrchestrator(project_root=root)
            files = orch.collect_files()

            py_files = [f for f in files if f.suffix == ".py"]
            assert len(py_files) == 3

    def test_excludes_common_dirs(self):
        """应排除 __pycache__, .git, .venv 等."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("# test")

            # 创建应被排除的目录及其文件
            for ex_dir in ["__pycache__", ".git", ".venv", "node_modules",
                           "_proc-use", "_scratch", ".phase-execution"]:
                (root / ex_dir).mkdir(exist_ok=True)
                (root / ex_dir / "x.py").write_text("# ignored")

            orch = DeepAuditOrchestrator(project_root=root)
            files = orch.collect_files()

            # 只应收集 a.py
            assert len(files) == 1
            assert files[0].name == "a.py"

    def test_excludes_design_and_docs(self):
        """应排除 design/ 和 docs/ 目录."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src.py").write_text("# main")
            (root / "design").mkdir()
            (root / "design" / "design_file.py").write_text("# design")
            (root / "docs").mkdir()
            (root / "docs" / "doc_file.py").write_text("# doc")

            orch = DeepAuditOrchestrator(project_root=root)
            files = orch.collect_files()

            assert len(files) == 1
            assert files[0].name == "src.py"

    def test_empty_project(self):
        """空项目应返回空列表."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = DeepAuditOrchestrator(project_root=root)
            files = orch.collect_files()
            assert files == []

    def test_returns_absolute_paths(self):
        """收集的文件路径应为相对路径的 Path 对象."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("# test")

            orch = DeepAuditOrchestrator(project_root=root)
            files = orch.collect_files()

            assert len(files) > 0
            assert isinstance(files[0], Path)


class TestRunAuditSkeleton:
    """Phase 1 骨架 run_audit() 测试."""

    def test_run_audit_returns_report(self):
        """run_audit() 应返回 DeepAuditReport."""
        from auto_engineering.gates.deep_audit import DeepAuditReport

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("print('hello')")

            orch = DeepAuditOrchestrator(project_root=root)
            report = orch.run_audit()

            assert isinstance(report, DeepAuditReport)
            assert report.total_audited_files >= 1
            assert report.findings == []  # Phase 1 骨架: 空 findings

    def test_run_audit_empty_project(self):
        """空项目 run_audit() 返回 total_audited_files=0."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = DeepAuditOrchestrator(project_root=root)
            report = orch.run_audit()

            assert report.total_audited_files == 0
            assert report.findings == []


class TestAuditDimensions:
    """审计维度定义测试."""

    def test_three_dimensions_defined(self):
        """应有 3 个审计维度."""
        assert len(AUDIT_DIMENSIONS) == 3
        assert "architecture" in AUDIT_DIMENSIONS
        assert "code_quality" in AUDIT_DIMENSIONS
        assert "engineering" in AUDIT_DIMENSIONS

    def test_dimensions_have_descriptions(self):
        """每个维度应有非空描述."""
        for key, desc in AUDIT_DIMENSIONS.items():
            assert isinstance(desc, str)
            assert len(desc) > 10
