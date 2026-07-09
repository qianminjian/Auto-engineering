"""DesignDoc.parse() — markdown 设计文档 → 层次结构 (B10.4a, DS-6 权威定义).

层次识别混合策略:
  ① 标题层级启发 (默认): H2→Plate, H3→Component, H4/表格行/列表项→DesignItem
  ② <!-- ae:* --> HTML 注释标记消歧 (优先于启发, 冲突时 marker 赢)
  ③ 解析不确定 → parse_warnings (喂 Phase 0 gap_scan)

parse() 只做**结构识别** (确定性 Python), 不做语义充分性判定 (那是 gap_scan Agent
的职责). 用成熟库 markdown-it-py 解析, 不自造正则遍历 markdown 语法树.

参考: v5.6-Design-Loop.md §B10.4a.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt

# ============================================================
# 层级数据模型 (§B10.4a)
# ============================================================


@dataclass
class DesignItem:
    """最细粒度设计条目 — 供 component_verifier 做设计→代码映射."""
    item_id: str              # 稳定 id: f"{section}-{seq}", 如 "B2-1"
    design_section: str       # 章节 ref, 如 "§B2"
    title: str
    key_claims: list[str]     # 可验证断言
    source_marker: str        # "explicit_marker" | "heading" | "table_row" | "list_item"


@dataclass
class Component:
    """组件 — name 须等于 batch_plan[].component (验证层裁剪/BatchState)."""
    name: str
    design_section: str       # 如 "§B6.1"
    design_items: list[DesignItem] = field(default_factory=list)
    source_marker: str = "heading"

    def design_spec_summary(self) -> str:
        """组件设计条目摘要 (component_verifier action context).

        每条设计条目一行: "title: claim1; claim2". 无 design_items → "".
        """
        lines = []
        for item in self.design_items:
            claims = "; ".join(item.key_claims)
            lines.append(f"{item.title}: {claims}" if claims else item.title)
        return "\n".join(lines)


@dataclass
class Plate:
    """板块 — 含跨组件契约声明 (供 plate_deep_audit action)."""
    name: str
    design_section: str
    components: list[Component] = field(default_factory=list)
    cross_component_contracts_raw: list[str] = field(default_factory=list)

    def cross_component_contracts(self) -> list[str]:
        return self.cross_component_contracts_raw

    def components_summary(self) -> list[dict]:
        """板块内组件清单 (plate_deep_audit action context)."""
        return [
            {"name": c.name, "design_section": c.design_section,
             "design_items": len(c.design_items)}
            for c in self.components
        ]


@dataclass
class Supplement:
    """gap 解决产出 — architect (design-doc 模式) 的细化依据 (§B10.6).

    随 EngineState 持久化 (跨 tick, C.10 #29). parse() 不产出 Supplement
    (由 gap_review/research 流程填充), 此处仅定义类型供 DesignDoc.supplements 引用.
    """
    gap_id: str
    design_section_ref: str
    content: str
    source: str                      # "user" | "research_agent" | "architect_sub_design"
    source_tier: str | None = None   # research 来源层 (B10.6), 非 research 为 None
    confidence: str = "medium"       # "high" | "medium" | "low"
    created_at: str = ""


@dataclass
class DesignDoc:
    plates: list[Plate]
    supplements: dict[str, Supplement]                       # gap_id → Supplement
    parse_warnings: list[str] = field(default_factory=list)  # 结构不确定项 → 喂 gap_scan
    path: str | None = None                                  # 源文档路径 (parse 时设置)

    @classmethod
    def parse(cls, path: str | Path) -> DesignDoc:
        """markdown 设计文档 → DesignDoc(plates=[...], supplements={})."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"设计文档不存在: {p}")
        text = p.read_text(encoding="utf-8")
        doc = _Parser(text).run()
        doc.path = str(p)
        return doc

    def sections_summary(self) -> list[dict]:
        """全量设计章节清单 (system_verifier action context).

        展平 plate→component: 每组件一条 {plate, component, design_section}.
        """
        return [
            {"plate": plate.name, "component": comp.name,
             "design_section": comp.design_section}
            for plate in self.plates
            for comp in plate.components
        ]


# ============================================================
# 内部解析器
# ============================================================

# 前导章节编号: "B6." / "B6.1 " / "6.1 " 等
_SECTION_RE = re.compile(r"^([A-Za-z]*\d+(?:\.\d+)*)[.、]?\s+(.*)$")
# ae 标记: <!-- ae:plate name="X" contracts="a; b" -->
_MARKER_RE = re.compile(r"<!--\s*ae:(plate|component|design-item)\b(.*?)-->", re.DOTALL)
_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
# key_claims 断言关键词
_CLAIM_KEYWORDS = ("必须", "禁止", "shall", "≤", "≥", "==", "def ", "dataclass")


def _split_semi(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(";") if s.strip()]


def _extract_section(heading_text: str) -> tuple[str | None, str]:
    """标题 → (bare_section_num | None, name). 'B6.1 X' → ('B6.1', 'X')."""
    m = _SECTION_RE.match(heading_text.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, heading_text.strip()


class _Parser:
    def __init__(self, text: str) -> None:
        md = MarkdownIt("commonmark").enable("table")
        self.tokens = md.parse(text)
        self.plates: list[Plate] = []
        self.warnings: list[str] = []
        self.cur_plate: Plate | None = None
        self.cur_component: Component | None = None
        self.cur_item: DesignItem | None = None
        # 最近创建的层级节点 (供 marker 覆盖): ("plate"|"component"|"item", obj)
        self.last_node: tuple[str, object] | None = None

    def run(self) -> DesignDoc:
        toks = self.tokens
        i, n = 0, len(toks)
        while i < n:
            t = toks[i]
            if t.type == "heading_open":
                text = toks[i + 1].content if i + 1 < n else ""
                self._on_heading(int(t.tag[1]), text)
                i += 3  # heading_open, inline, heading_close
                continue
            if t.type == "html_block":
                self._on_marker(t.content)
                i += 1
                continue
            if t.type == "table_open":
                i = self._on_table(i)
                continue
            if t.type in ("bullet_list_open", "ordered_list_open"):
                i = self._on_list(i, t.type)
                continue
            if t.type == "paragraph_open":
                content = toks[i + 1].content if i + 1 < n else ""
                self._on_paragraph(content)
                i += 3
                continue
            i += 1

        if not self.plates and not self.warnings:
            self.warnings.append(
                "设计文档无可识别层次 (无 H2/H3 结构且无 ae 标记), "
                "请加 <!-- ae:* --> 标记或用 vague-requirement 模式"
            )
        return DesignDoc(plates=self.plates, supplements={}, parse_warnings=self.warnings)

    # ---------- 标题 ----------

    def _on_heading(self, level: int, text: str) -> None:
        if level == 1 or text.strip().upper().startswith("PART"):
            return  # 文档/分区标题, 非层次单元
        if level == 2:
            self._new_plate(text)
        elif level == 3:
            self._new_component(text)
        else:  # H4+ → DesignItem
            self._new_item(text)

    def _new_plate(self, text: str) -> None:
        num, name = _extract_section(text)
        plate = Plate(name=name, design_section=f"§{num}" if num else name)
        self.plates.append(plate)
        self.cur_plate, self.cur_component, self.cur_item = plate, None, None
        self.last_node = ("plate", plate)

    def _new_component(self, text: str) -> None:
        if self.cur_plate is None:  # H3 无 H2 祖先 → 合成 plate
            self.warnings.append(f"标题跳级: H3 '{text}' 无 H2 祖先, 合成隐式 Plate")
            self._new_plate("(implicit)")
        num, name = _extract_section(text)
        comp = Component(name=name, design_section=f"§{num}" if num else name)
        self.cur_plate.components.append(comp)  # type: ignore[union-attr]
        self.cur_component, self.cur_item = comp, None
        self.last_node = ("component", comp)

    def _new_item(self, text: str) -> None:
        if self.cur_component is None:  # H2→H4 跳级 → 合成 component
            self.warnings.append(f"标题跳级: H4 '{text}' 无 H3 组件祖先, 合成隐式 Component")
            if self.cur_plate is None:
                self._new_plate("(implicit)")
            comp = Component(name="(implicit)", design_section="(implicit)")
            self.cur_plate.components.append(comp)  # type: ignore[union-attr]
            self.cur_component = comp
        item = self._make_item(title=text, source_marker="heading", key_claims=[])
        self.cur_component.design_items.append(item)
        self.cur_item = item
        self.last_node = ("item", item)

    def _make_item(self, title: str, source_marker: str, key_claims: list[str]) -> DesignItem:
        comp = self.cur_component
        assert comp is not None
        bare = comp.design_section.lstrip("§")
        seq = len(comp.design_items) + 1
        return DesignItem(
            item_id=f"{bare}-{seq}",
            design_section=comp.design_section,
            title=title,
            key_claims=key_claims,
            source_marker=source_marker,
        )

    # ---------- ae 标记覆盖 ----------

    def _on_marker(self, content: str) -> None:
        m = _MARKER_RE.search(content)
        if not m:
            return
        kind = m.group(1)
        attrs = dict(_ATTR_RE.findall(m.group(2)))
        if kind == "plate":
            self._apply_plate_marker(attrs)
        elif kind == "component":
            self._apply_component_marker(attrs)
        elif kind == "design-item":
            self._apply_item_marker(attrs)

    def _apply_plate_marker(self, attrs: dict[str, str]) -> None:
        contracts = _split_semi(attrs.get("contracts", ""))
        node = self.last_node
        if node and node[0] == "plate":
            plate = node[1]
            if attrs.get("name"):
                plate.name = attrs["name"]  # type: ignore[attr-defined]
            if contracts:
                plate.cross_component_contracts_raw = contracts  # type: ignore[attr-defined]
        elif node and node[0] == "component":
            # 类型冲突: marker 赢 → 组件重分类为 Plate
            comp: Component = node[1]  # type: ignore[assignment]
            if self.cur_plate and comp in self.cur_plate.components:
                self.cur_plate.components.remove(comp)
            plate = Plate(
                name=attrs.get("name") or comp.name,
                design_section=comp.design_section,
                cross_component_contracts_raw=contracts,
            )
            self.plates.append(plate)
            self.cur_plate, self.cur_component, self.cur_item = plate, None, None
            self.last_node = ("plate", plate)

    def _apply_component_marker(self, attrs: dict[str, str]) -> None:
        node = self.last_node
        if node and node[0] == "component" and attrs.get("name"):
            node[1].name = attrs["name"]  # type: ignore[attr-defined]
            node[1].source_marker = "explicit_marker"  # type: ignore[attr-defined]

    def _apply_item_marker(self, attrs: dict[str, str]) -> None:
        node = self.last_node
        claims = _split_semi(attrs.get("claims", ""))
        if node and node[0] == "item":
            item: DesignItem = node[1]  # type: ignore[assignment]
            if attrs.get("title"):
                item.title = attrs["title"]
            if claims:
                item.key_claims = claims
            item.source_marker = "explicit_marker"
        elif self.cur_component is not None and attrs.get("title"):
            item = self._make_item(
                title=attrs["title"], source_marker="explicit_marker", key_claims=claims
            )
            self.cur_component.design_items.append(item)
            self.cur_item = item
            self.last_node = ("item", item)

    # ---------- 表格 ----------

    def _on_table(self, start: int) -> int:
        """收集 tbody 数据行. 有 cur_item → 并入 key_claims; 否则每行成 DesignItem."""
        toks = self.tokens
        i = start
        in_tbody = False
        row: list[str] = []
        rows: list[list[str]] = []
        while i < len(toks):
            tt = toks[i].type
            if tt == "tbody_open":
                in_tbody = True
            elif tt == "tbody_close":
                in_tbody = False
            elif tt == "tr_open" and in_tbody:
                row = []
            elif tt == "inline" and in_tbody:
                row.append(toks[i].content.strip())
            elif tt == "tr_close" and in_tbody and row:
                rows.append(row)
            elif tt == "table_close":
                i += 1
                break
            i += 1

        if self.cur_component is None:
            return i  # 表格无组件归属 → 跳过 (结构外)
        for r in rows:
            cells = [c for c in r if c]
            if self.cur_item is not None:
                self.cur_item.key_claims.extend(cells)
            else:
                item = self._make_item(
                    title=cells[0] if cells else "",
                    source_marker="table_row",
                    key_claims=list(cells),
                )
                self.cur_component.design_items.append(item)
        return i

    # ---------- 列表 ----------

    def _on_list(self, start: int, open_type: str) -> int:
        close_type = open_type.replace("_open", "_close")
        toks = self.tokens
        i = start
        depth = 0
        texts: list[str] = []
        while i < len(toks):
            tt = toks[i].type
            if tt == open_type:
                depth += 1
            elif tt == close_type:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif tt == "inline":
                c = toks[i].content.strip()
                if c:
                    texts.append(c)
            i += 1

        if self.cur_component is None:
            return i
        for txt in texts:
            if self.cur_item is not None:
                self.cur_item.key_claims.append(txt)
            else:
                item = self._make_item(
                    title=txt, source_marker="list_item", key_claims=[txt]
                )
                self.cur_component.design_items.append(item)
        return i

    # ---------- 段落 ----------

    def _on_paragraph(self, content: str) -> None:
        if self.cur_item is None:
            return
        if any(k in content for k in _CLAIM_KEYWORDS):
            self.cur_item.key_claims.append(content.strip())
