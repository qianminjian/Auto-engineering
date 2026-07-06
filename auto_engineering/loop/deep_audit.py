"""v5.5 — 3-agent 并行审计编排器.

设计来源: design/v5.0-Design-Loop.md §B6.5b

负责:
- 收集项目文件列表 (排除非代码目录)
- 按架构/代码质量/工程化 3 维度分配文件给 3 个 agent
  (当前 Phase 1 骨架: 用串行模拟并行, 返回结构化占位报告)
- 合并 3 个 agent 的报告, 做 severity 归一化 (Critical→P0, Important→P1, Minor→P2)
- 返回合并后的 DeepAuditReport
"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.gates.deep_audit import DeepAuditFinding, DeepAuditReport

# 3 个审计维度 → agent role 映射
AUDIT_DIMENSIONS = {
    "architecture": "架构合理性审计: 模块边界、循环依赖、God Class、设计vs实现",
    "code_quality": "代码质量审计: 异常处理、边界条件、竞态条件、资源泄漏",
    "engineering": "工程化规范审计: 命名一致性、类型安全、测试分层、dead code",
}

# Phase 1 骨架: 不扫描这些目录
_EXCLUDE_DIRS = {
    "__pycache__", ".git", "node_modules", "_proc-use", "_scratch",
    ".phase-execution", ".venv", "design", "docs",
}


class DeepAuditOrchestrator:
    """编排 3 个 agent 并行审计, 合并结果.

    Phase 1 骨架: 收集文件列表, 返回空报告.
    Phase 5+ 实现真实的 3-agent spawn 并行审计.

    Args:
        project_root: 项目根目录路径.
    """

    def __init__(self, project_root: Path | str):
        self._project_root = Path(project_root)

    def collect_files(self) -> list[Path]:
        """收集项目源文件 (排除非代码目录).

        Returns:
            项目根目录下所有 .py 文件的 Path 列表 (排除 __pycache__, .git 等).
        """
        files: list[Path] = []
        for py_file in self._project_root.rglob("*.py"):
            if not any(ex in py_file.parts for ex in _EXCLUDE_DIRS):
                files.append(py_file)
        return files

    def run_audit(self) -> DeepAuditReport:
        """Phase 1 骨架: 收集文件但返回空结果.

        Phase 5+ 实现真实的 3-agent spawn 并行审计.

        Returns:
            DeepAuditReport (Phase 1: findings 为空, total_audited_files 为文件数).
        """
        files = self.collect_files()
        return DeepAuditReport(
            findings=[],
            total_audited_files=len(files),
        )
