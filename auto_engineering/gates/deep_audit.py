"""v5.5 — DeepAuditGate: 全量代码深度审计 Gate.

触发时机: Orchestrator 在 critic APPROVE + gates passed 后调 DeepAuditGate.run() (B7.1 步2j)
输出: GateVerdict 含 P0/P1/P2 分类 findings.

设计来源: design/v5.6-Design-Loop.md §B6.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict

__all__ = [
    "DeepAuditFinding", "DeepAuditGate", "DeepAuditReport", "recount_findings",
]

# B6.7a 去重: severity 排序 (值越小越严重, 合并时保留最严重)
_SEV_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _normalize_agent_source(raw: object) -> list[str]:
    """入参 agent_source (单 Agent str / 已是 list / 空) 归一化为去空元素的 list[str]."""
    if isinstance(raw, list):
        return [str(s) for s in raw if str(s)]
    if isinstance(raw, str):
        return [raw] if raw else []
    return []


def _dedup_key(f: DeepAuditFinding) -> tuple[str, int | None, str]:
    """去重键 = (file, line, description[:40] 归一化小写去空白) — B6.7a."""
    norm_desc = "".join(f.description[:40].split()).lower()
    return (f.file, f.line, norm_desc)


def _merge_sources(existing: list[str], incoming: list[str]) -> list[str]:
    """按首次出现顺序合并两个 agent_source 列表, 去重."""
    merged = list(existing)
    for s in incoming:
        if s not in merged:
            merged.append(s)
    return merged


def _dedup_findings(findings: list[DeepAuditFinding]) -> list[DeepAuditFinding]:
    """确定性去重 (B6.7a): 同键碰撞保留最高 severity, 合并 agent_source, 保持首现顺序.

    Agent 报的 p0/p1/p2 count 仅供参考 — 调用方基于本函数返回值重算为准.
    """
    by_key: dict[tuple[str, int | None, str], DeepAuditFinding] = {}
    for f in findings:
        key = _dedup_key(f)
        kept = by_key.get(key)
        if kept is None:
            by_key[key] = f
            continue
        # 碰撞: 合并 agent_source; severity 取更严重者 (连带其 dimension/evidence/fix)
        merged_src = _merge_sources(kept.agent_source, f.agent_source)
        if _SEV_RANK.get(f.severity, 9) < _SEV_RANK.get(kept.severity, 9):
            f.agent_source = merged_src
            by_key[key] = f
        else:
            kept.agent_source = merged_src
    return list(by_key.values())


def _finding_from_dict(d: dict) -> DeepAuditFinding:
    """原始 finding dict → DeepAuditFinding (缺字段给默认, agent_source 归一化)."""
    return DeepAuditFinding(
        severity=d.get("severity", "P2"),
        dimension=d.get("dimension", ""),
        file=d.get("file", ""),
        line=d.get("line"),
        description=d.get("description", ""),
        evidence=d.get("evidence", ""),
        suggested_fix=d.get("suggested_fix", ""),
        agent_source=_normalize_agent_source(d.get("agent_source")),
    )


def _finding_to_dict(f: DeepAuditFinding) -> dict:
    return {
        "severity": f.severity, "dimension": f.dimension, "file": f.file,
        "line": f.line, "description": f.description, "evidence": f.evidence,
        "suggested_fix": f.suggested_fix, "agent_source": f.agent_source,
    }


def recount_findings(raw_findings: list) -> tuple[list[dict], int, int, int]:
    """B6.7a 权威求值入口: 原始 findings → (去重后 dict 列表, p0, p1, p2).

    Agent 报的 p0/p1/p2 count 仅供参考 — 本函数去重后重算为权威计数.
    DeepAuditGate.run() 与 tick 编排 (plate/system_deep_audit 路由) 共用此入口,
    消解 '路由信任 Agent 自报计数' 的静默失效 (§B6.7a line 1068)。
    """
    parsed: list[DeepAuditFinding] = []
    for f in raw_findings or []:
        if isinstance(f, DeepAuditFinding):
            f.agent_source = _normalize_agent_source(f.agent_source)
            parsed.append(f)
        elif isinstance(f, dict):
            parsed.append(_finding_from_dict(f))
    deduped = _dedup_findings(parsed)
    p0 = sum(1 for f in deduped if f.severity == "P0")
    p1 = sum(1 for f in deduped if f.severity == "P1")
    p2 = sum(1 for f in deduped if f.severity == "P2")
    return [_finding_to_dict(f) for f in deduped], p0, p1, p2


@dataclass
class DeepAuditFinding:
    """单条深度审计发现.

    B6.7a: agent_source 为 list[str] — 一条问题被多个并行子 Agent
    (architecture/code_quality/engineering) 命中时合并为多元素列表 (命中越多置信越高).
    """

    severity: str  # P0 | P1 | P2
    dimension: str  # 架构合理性 | 代码质量 | 工程化规范 | 代码逻辑虚化度 | 团队协作友好度
    file: str  # 相对路径
    line: int | None
    description: str
    evidence: str
    suggested_fix: str
    agent_source: list[str] = field(default_factory=list)  # 命中的 agent role 列表


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

    def __init__(self, p1_threshold: int = 6):
        self._p1_threshold = p1_threshold

    def run(self, project_root: Path) -> GateVerdict:
        """执行 DeepAudit, 返回 GateVerdict.

        v5.5 P1-9: contracts 改为实例属性 (self.contracts).
        v5.5 audit P0-2: Orchestrator 通过 contracts 回填真实 findings.

        Returns:
            GateVerdict (passed + details + suggestions).
        """
        report = DeepAuditReport()
        findings_raw = self.contracts.get("findings", []) if self.contracts else []
        # B6.7a: 去重 + 重算为权威计数 (与 tick 编排共用同一入口, 见 recount_findings)
        deduped, p0, p1, p2 = recount_findings(findings_raw)
        report.findings = [_finding_from_dict(d) for d in deduped]
        report.p0_count, report.p1_count, report.p2_count = p0, p1, p2

        passed = p0 == 0 and p1 <= self._p1_threshold

        details = {
            "p0_count": p0,
            "p1_count": p1,
            "p2_count": p2,
            "p1_threshold": self._p1_threshold,
            "total_audited_files": report.total_audited_files,
            "findings": [
                {
                    "severity": d["severity"],
                    "dimension": d["dimension"],
                    "file": d["file"],
                    "line": d["line"],
                    "description": d["description"],
                    "agent_source": d["agent_source"],
                }
                for d in deduped
            ],
        }

        suggestions = (
            [d["suggested_fix"] for d in deduped if d["suggested_fix"]]
            if not passed
            else []
        )

        message = (
            f"DeepAuditGate: {'PASS' if passed else 'FAIL'} "
            f"(P0={p0}, P1={p1}/{self._p1_threshold}, P2={p2})"
        )

        return GateVerdict(
            gate_name=self.name,
            passed=passed,
            message=message,
            details=details,
            suggestions=suggestions,
        )
