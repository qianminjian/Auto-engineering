"""v5.5 — 3-agent 并行审计编排器.

设计来源: design/v5.0-Design-Loop.md §B6.5b

负责:
- 收集项目文件列表 (排除非代码目录)
- 按架构/代码质量/工程化 3 维度分配文件给 3 个 agent
  (Phase 1: 用 AuditGate 本地静态扫描作为基线; Phase 5+ LLM agent 增强)
- 合并 3 个 agent 的报告, 做 severity 归一化 (Critical→P0, Important→P1, Minor→P2)
- 返回合并后的 DeepAuditReport
"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.gates.audit import AuditFinding, AuditGate
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

    Phase 1: 用 AuditGate 的本地静态扫描能力提供基线审计.
    Phase 5+ 实现真实的 3-agent spawn 并行 LLM 审计增强.

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
        """Phase 1 基线审计: 调用 AuditGate 本地静态扫描.

        AuditGate 的 5 维度静态扫描 (regex pattern matching) 提供确定性基线.
        Phase 5+ 追加 3-agent LLM 并行审计增强深度.

        Returns:
            DeepAuditReport (含 AuditGate 的 AuditFinding 转换).
        """
        import time
        start = time.monotonic()

        gate = AuditGate()
        gate_result = gate.run(self._project_root)

        # 从 AuditGate 的 verdict.details 提取 findings 并转换为 DeepAuditFinding
        findings: list[DeepAuditFinding] = []
        raw_findings: list[dict] = gate_result.details.get("findings", []) if gate_result.details else []

        for f in raw_findings:
            findings.append(DeepAuditFinding(
                severity=f.get("severity", "P2"),
                dimension=f.get("dimension", "代码质量"),
                file=f.get("file", ""),
                line=f.get("line"),
                description=f.get("description", ""),
                evidence=f.get("evidence", ""),
                suggested_fix="",
                agent_source="audit-gate-static",
            ))

        p0_count = sum(1 for f in findings if f.severity == "P0")
        p1_count = sum(1 for f in findings if f.severity == "P1")
        p2_count = sum(1 for f in findings if f.severity == "P2")

        return DeepAuditReport(
            findings=findings,
            p0_count=p0_count,
            p1_count=p1_count,
            p2_count=p2_count,
            total_audited_files=gate_result.details.get("files_scanned", 0) if gate_result.details else 0,
            audit_duration_ms=int((time.monotonic() - start) * 1000),
        )
