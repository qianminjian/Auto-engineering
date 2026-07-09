"""Pre-flight Design Gap Analysis — GapItem / GapReport (B10.2).

Loop 启动时 (--design-doc 模式) 在 T1 architect 之前扫描设计文档清晰度 → 分级 →
用户在开发开始前决策 (Fill/Research/Defer). 代价低 (尚未开发), 消化"启动时可预见的模糊".

分级由 gap_scan Agent (LLM) 判定 (需语义判断, Python 不承担):
  - grade (architectural/component/module): 模糊 scope, 驱动阻塞约束与解决顺序
  - clarity (missing/vague/partial): 模糊 kind (正交于 grade), 驱动 gap_review 建议路径

本模块只提供**确定性 Python**: 数据结构 + has_blocking 计算 + resolution 管理/校验
+ 序列化 (gap_report_json, EngineState #28).

参考: v5.6-Design-Loop.md §B10.2 / §B10.3 / §B10.5.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# 合法取值域
_VALID_GRADES = frozenset({"architectural", "component", "module"})
_VALID_CLARITY = frozenset({"missing", "vague", "partial"})
_VALID_RESOLUTIONS = frozenset({"pending", "fill", "research", "defer", "defer_research"})
# architectural gap 禁止的 resolution (B10.5: 不允许全部 defer, 须 Fill/Research 先解)
_BLOCKING_FORBIDDEN = frozenset({"defer", "defer_research"})


@dataclass
class GapItem:
    id: str                       # "gap-B6.2"
    design_section_ref: str       # "§B6.2"
    node_id: str | None           # 对应 ProgressTree 节点
    grade: str                    # "architectural" | "component" | "module"
    clarity: str                  # "missing" | "vague" | "partial"
    summary: str                  # 缺什么 (人类可读)
    depends_on: list[str] = field(default_factory=list)  # 依赖的其他 gap id (architectural 常级联)
    resolution: str = "pending"   # "pending"|"fill"|"research"|"defer"|"defer_research"
    user_note: str | None = None


@dataclass
class GapReport:
    gaps: list[GapItem]
    scanned_sections: int
    has_blocking: bool = field(default=False)  # __post_init__ 计算 (存在 architectural gap)

    def __post_init__(self) -> None:
        # has_blocking 恒由 gaps 派生 (grade 不随 resolution 变, 计算稳定)
        self.has_blocking = any(g.grade == "architectural" for g in self.gaps)

    # ---------- 查询 ----------

    def pending(self) -> list[GapItem]:
        return [g for g in self.gaps if g.resolution == "pending"]

    def blocking_gaps(self) -> list[GapItem]:
        return [g for g in self.gaps if g.grade == "architectural"]

    def has_pending(self) -> bool:
        return any(g.resolution == "pending" for g in self.gaps)

    def _get(self, gap_id: str) -> GapItem:
        for g in self.gaps:
            if g.id == gap_id:
                return g
        raise KeyError(f"未知 gap id: {gap_id}")

    # ---------- resolution 管理 ----------

    def set_resolution(self, gap_id: str, resolution: str, user_note: str | None = None) -> None:
        if resolution not in _VALID_RESOLUTIONS:
            raise ValueError(
                f"非法 resolution '{resolution}', 合法值: {sorted(_VALID_RESOLUTIONS)}"
            )
        g = self._get(gap_id)
        g.resolution = resolution
        if user_note is not None:
            g.user_note = user_note

    def validate_resolutions(self) -> list[str]:
        """返回违规 gap id: architectural gap 选 defer/defer_research (B10.5 约束).

        由 gap_review 后的 Guardrail 消费 (B3) —— architectural gap 若全部 defer,
        组件设计无契约依据.
        """
        return [
            g.id for g in self.gaps
            if g.grade == "architectural" and g.resolution in _BLOCKING_FORBIDDEN
        ]

    # ---------- 序列化 (gap_report_json, EngineState #28) ----------

    def to_dict(self) -> dict:
        return {
            "gaps": [asdict(g) for g in self.gaps],
            "scanned_sections": self.scanned_sections,
            "has_blocking": self.has_blocking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> GapReport:
        gaps = [GapItem(**gd) for gd in d.get("gaps", [])]
        return cls(gaps=gaps, scanned_sections=d.get("scanned_sections", 0))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> GapReport:
        return cls.from_dict(json.loads(s))
