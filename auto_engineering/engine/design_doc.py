"""DesignDoc 数据模型与 Markdown 解析入口。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DesignItem:
    """最细粒度设计条目 — 供 component_verifier 做设计→代码映射。"""

    item_id: str
    design_section: str
    title: str
    key_claims: list[str]
    source_marker: str


@dataclass
class Component:
    """组件 — name 须等于 batch_plan[].component。"""

    name: str
    design_section: str
    design_items: list[DesignItem] = field(default_factory=list)
    source_marker: str = "heading"

    def design_spec_summary(self) -> str:
        """组件设计条目摘要。"""

        lines = []
        for item in self.design_items:
            claims = "; ".join(item.key_claims)
            lines.append(f"{item.title}: {claims}" if claims else item.title)
        return "\n".join(lines)


@dataclass
class Plate:
    """板块 — 含跨组件契约声明。"""

    name: str
    design_section: str
    components: list[Component] = field(default_factory=list)
    cross_component_contracts_raw: list[str] = field(default_factory=list)

    def cross_component_contracts(self) -> list[str]:
        return self.cross_component_contracts_raw

    def components_summary(self) -> list[dict]:
        """板块内组件清单。"""

        return [
            {
                "name": component.name,
                "design_section": component.design_section,
                "design_items": len(component.design_items),
            }
            for component in self.components
        ]


@dataclass
class Supplement:
    """gap 解决产出 — architect 在 design-doc 模式下填充。"""

    gap_id: str
    design_section_ref: str
    content: str
    source: str
    source_tier: str | None = None
    confidence: str = "medium"
    created_at: str = ""


_ADVISORY_SCOPE_RE = re.compile(
    r"(?:未来(?:改进|版本|规划)|后续改进|future\s+improvement|advisory)",
    re.IGNORECASE,
)


@dataclass
class DesignDoc:
    plates: list[Plate]
    supplements: dict[str, Supplement]
    parse_warnings: list[str] = field(default_factory=list)
    path: str | None = None

    @classmethod
    def parse(cls, path: str | Path) -> DesignDoc:
        """读取 Markdown 并交给唯一的确定性解析器。"""

        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"设计文档不存在: {p}")
        text = p.read_text(encoding="utf-8")
        from auto_engineering.engine.design_doc_parser import DesignDocParser

        doc = DesignDocParser(text).run()
        doc.path = str(p)
        return doc

    def sections_summary(self) -> list[dict]:
        """全量设计章节清单，展平 plate→component。"""

        return [
            {
                "plate": plate.name,
                "component": component.name,
                "design_section": component.design_section,
            }
            for plate in self.plates
            for component in plate.components
        ]

    def advisory_section_refs(self) -> frozenset[str]:
        """返回标题明确标注为未来/咨询性质的组件章节引用。"""

        refs: set[str] = set()
        for plate in self.plates:
            for component in plate.components:
                if _ADVISORY_SCOPE_RE.search(component.name):
                    refs.add(component.design_section)
        return frozenset(refs)


__all__ = ["Component", "DesignDoc", "DesignItem", "Plate", "Supplement"]
