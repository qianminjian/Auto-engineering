"""v5.5 — DeepAuditGate: 全量代码深度审计 Gate.

触发时机: Orchestrator 在 critic APPROVE + gates passed 后调 DeepAuditGate.run() (B7.1 步2j)
输出: GateVerdict 含 P0/P1/P2 分类 findings.

设计来源: design/v5.0-Design-Loop.md §B6.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict


@dataclass
class DeepAuditFinding:
    """单条深度审计发现."""

    severity: str  # P0 | P1 | P2
    dimension: str  # 架构合理性 | 代码质量 | 工程化规范 | 代码逻辑虚化度 | 团队协作友好度
    file: str  # 相对路径
    line: int | None
    description: str
    evidence: str
    suggested_fix: str
    agent_source: str = ""  # 来源 agent (architecture/code_quality/engineering)


@dataclass
class DeepAuditReport:
    """深度审计汇总报告."""

    findings: list[DeepAuditFinding] = field(default_factory=list)
    p0_count: int = 0
    p1_count: int = 0
    p2_count: int = 0
    total_audited_files: int = 0
    audit_duration_ms: int = 0


class DeepAuditGate(Gate):
    """全量代码深度审计 Gate — LLM 3-agent 并行审计.

    当前 Phase 1 为骨架实现: 创建 DeepAuditReport 结构, 但不实际 spawn agent.
    Phase 2 集成到 Orchestrator 后, _run_deep_audit() 调用实际的 3-agent 编排器.

    Args:
        project_root: 项目根目录路径.
        p1_threshold: P1 数量上限 (默认 6). P0 任何数量都 fail.
    """

    name = "DeepAuditGate"
    # v5.5 §B6.5: DeepAuditGate 在 critic APPROVE 后运行, 仅 critic stage
    applies_to_stages = ("critic",)

    def __init__(self, project_root: Path | None = None, p1_threshold: int = 6):
        self._project_root = Path(project_root) if project_root else None
        self._p1_threshold = p1_threshold

    def run(
        self, project_root: Path | None = None, contracts: dict | None = None
    ) -> GateVerdict:
        """执行 DeepAudit, 返回 GateVerdict.

        兼容 Gate ABC 签名: run(project_root, contracts=None).
        project_root 可从参数传入或从 __init__ 获取.

        Args:
            project_root: 项目根目录 (Gate ABC 签名). 若 __init__ 也有, 参数优先.
            contracts: 可选上下文字典, 可包含 "findings" key (list[dict]).

        Returns:
            GateVerdict (passed + details + suggestions).
        """
        root = project_root if project_root is not None else self._project_root
        if root is not None:
            root = Path(root)
        report = DeepAuditReport()
        findings_raw = contracts.get("findings", []) if contracts else []
        for f in findings_raw:
            if isinstance(f, dict):
                finding = DeepAuditFinding(**f)
            else:
                finding = f
            report.findings.append(finding)

        report.p0_count = sum(1 for f in report.findings if f.severity == "P0")
        report.p1_count = sum(1 for f in report.findings if f.severity == "P1")
        report.p2_count = sum(1 for f in report.findings if f.severity == "P2")

        passed = report.p0_count == 0 and report.p1_count <= self._p1_threshold

        details = {
            "p0_count": report.p0_count,
            "p1_count": report.p1_count,
            "p2_count": report.p2_count,
            "p1_threshold": self._p1_threshold,
            "total_audited_files": report.total_audited_files,
            "findings": [
                {
                    "severity": f.severity,
                    "dimension": f.dimension,
                    "file": f.file,
                    "line": f.line,
                    "description": f.description,
                }
                for f in report.findings
            ],
        }

        suggestions = (
            [f.suggested_fix for f in report.findings if f.suggested_fix]
            if not passed
            else []
        )

        message = (
            f"DeepAuditGate: {'PASS' if passed else 'FAIL'} "
            f"(P0={report.p0_count}, P1={report.p1_count}/{self._p1_threshold}, "
            f"P2={report.p2_count})"
        )

        return GateVerdict(
            gate_name=self.name,
            passed=passed,
            message=message,
            details=details,
            suggestions=suggestions,
        )
