"""refine.py — B6.10/DS-7 plan_refine 输入契约 (RefineRequest 归一).

4 个回源 (component_verifier / plate_deep_audit / system_verifier /
system_deep_audit) 路由回 architect 重规划时, 把两类信号 —— 验证覆盖缺口
(coverage_map MISSING/DIVERGED) 与审计发现 (deep_audit P0/P1 finding) —— 归一为
统一结构 RefineRequest(gaps=[RefineGap]), 供 architect PLAN-REFINE 模式消费.

确定性纯函数 (无 LLM/IO). 序列化为 EngineState.refine_request_json (#35) 跨 tick
持久化. 归一映射与过滤规则见设计 §B6.10 line 1163-1171.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 归一映射建议动作 (设计 §B6.10 映射表, line 1167-1169)
_MISSING_ACTION = "补充实现：新增覆盖该设计条目的 batch/task"
_DIVERGED_ACTION = "判定方向：修正代码回归设计意图，或（若代码更优）更新设计文档（走 C.11）"
_AUDIT_ACTION_DEFAULT = "修复该 finding"

_COVERAGE_SOURCES = frozenset({"component_verifier", "system_verifier"})
_AUDIT_SOURCES = frozenset({"plate_deep_audit", "system_deep_audit"})

# audit finding 只有 P0/P1 触发 plan_refine (P2 仅记录, 呼应 B6.7a 阈值)
_SEVERITY_RANK = {"P0": 2, "P1": 1, "P2": 0}


@dataclass
class RefineGap:
    """单条重规划缺口 (覆盖缺口 / 审计发现归一后的统一条目)."""
    kind: str                     # "MISSING" | "DIVERGED" | "AUDIT_FINDING"
    design_ref: str               # 设计定位 (design_item/§X.Y; finding 关联章节, 无则 "")
    detail: str                   # coverage note / audit description
    suggested_action: str         # 建议动作 (见归一映射表)
    severity: str | None = None   # audit: P0/P1/P2; coverage gap = None (视为必修)
    location: str | None = None   # DIVERGED/finding = "file:line"; MISSING = None


@dataclass
class RefineRequest:
    """plan_refine 统一输入 (跨 tick 持久化为 refine_request_json #35)."""
    source: str                   # 4 回源之一
    trigger_tick: int
    scope_plate: str | None       # 重规划范围 (system 级 = None 全局)
    scope_component: str | None   # component_verifier 源 = 具体组件; 更高层 = None
    gaps: list[RefineGap] = field(default_factory=list)  # ≥1 (空则不该路由回 architect)


def _fmt_location(file: str | None, line: int | None) -> str | None:
    """(file, line) → 'file:line'; 无 file → None."""
    if not file:
        return None
    return f"{file}:{line}" if line else file


def _dedup_findings(findings: list[dict]) -> list[dict]:
    """去重 (B6.7a): 键=(file, line, description[:40] 归一化). 碰撞保留最高 severity.

    一条问题被多 Agent 命中 = 更高置信. 保序 (首次出现位置).
    """
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    for f in findings:
        key = (
            f.get("file", ""),
            f.get("line", 0),
            (f.get("description", "")[:40]).strip().lower(),
        )
        if key not in best:
            best[key] = f
            order.append(key)
        else:
            cur = best[key]
            if _SEVERITY_RANK.get(f.get("severity", ""), -1) > _SEVERITY_RANK.get(
                    cur.get("severity", ""), -1):
                best[key] = f
    return [best[k] for k in order]


def build_refine_request(
    *,
    source: str,
    trigger_tick: int,
    scope_plate: str | None,
    scope_component: str | None,
    coverage_map: list[dict] | None = None,
    audit_findings: list[dict] | None = None,
) -> RefineRequest:
    """按源确定性归一 coverage_map / audit_findings → RefineRequest.

    coverage 源取所有 MISSING+DIVERGED; audit 源取去重后 P0 全部 + P1 (P2 跳过);
    IMPLEMENTED 条目不进. 见设计 §B6.10 line 1171 过滤规则.
    """
    gaps: list[RefineGap] = []

    if source in _COVERAGE_SOURCES:
        for item in coverage_map or []:
            status = item.get("status")
            design_ref = item.get("design_item") or item.get("design_section") or ""
            if status == "MISSING":
                gaps.append(RefineGap(
                    kind="MISSING", design_ref=design_ref,
                    detail=item.get("note", ""),
                    suggested_action=_MISSING_ACTION,
                    severity=None, location=None))
            elif status == "DIVERGED":
                gaps.append(RefineGap(
                    kind="DIVERGED", design_ref=design_ref,
                    detail=item.get("note", ""),
                    suggested_action=_DIVERGED_ACTION,
                    severity=None,
                    location=_fmt_location(item.get("file"), item.get("line"))))
            # IMPLEMENTED → 跳过

    elif source in _AUDIT_SOURCES:
        for f in _dedup_findings(audit_findings or []):
            severity = f.get("severity")
            if severity not in ("P0", "P1"):
                continue  # P2 仅记录, 不触发 plan_refine
            gaps.append(RefineGap(
                kind="AUDIT_FINDING",
                design_ref=f.get("design_section") or f.get("section") or "",
                detail=f.get("description", ""),
                suggested_action=f.get("suggested_fix") or _AUDIT_ACTION_DEFAULT,
                severity=severity,
                location=_fmt_location(f.get("file"), f.get("line"))))

    return RefineRequest(
        source=source, trigger_tick=trigger_tick,
        scope_plate=scope_plate, scope_component=scope_component, gaps=gaps)
