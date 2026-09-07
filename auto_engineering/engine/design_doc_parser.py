"""Markdown 设计文档到 DesignDoc 层次模型的确定性解析器。"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt

from auto_engineering.engine.design_doc import (
    Component,
    DesignDoc,
    DesignItem,
    Plate,
)

# 前导章节编号: "B6." / "B6.1 " / "§B6.1 " / "6.1 " 等
_SECTION_RE = re.compile(r"^§?([A-Za-z]*\d+(?:\.\d+)*)[.、]?\s+(.*)$")
# ae 标记: <!-- ae:plate name="X" contracts="a; b" -->
_MARKER_RE = re.compile(
    r"<!--\s*ae:(plate|component|design-item)\b(.*?)-->", re.DOTALL
)
_ATTR_RE = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
# key_claims 断言关键词
_CLAIM_KEYWORDS = ("必须", "禁止", "shall", "≤", "≥", "==", "def ", "dataclass")


def _split_semi(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(";") if s.strip()]


def _extract_section(heading_text: str) -> tuple[str | None, str]:
    """标题 → (bare_section_num | None, name). 'B6.1 X' → ('B6.1', 'X')."""
    match = _SECTION_RE.match(heading_text.strip())
    if match:
        return match.group(1), match.group(2).strip()
    return None, heading_text.strip()


class DesignDocParser:
    """Markdown 设计文档解析器。

    方法分组:
      [入口]     __init__ + run                    — 初始化和主循环
      [层次]     _on_heading / _new_plate / _new_component / _new_item / _make_item
      [标记]     _on_marker / _apply_plate_marker / _apply_component_marker / _apply_item_marker
      [内容]     _on_table / _on_list / _on_paragraph
    """

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
            token = toks[i]
            if token.type == "heading_open":
                text = toks[i + 1].content if i + 1 < n else ""
                self._on_heading(int(token.tag[1]), text)
                i += 3  # heading_open, inline, heading_close
                continue
            if token.type == "html_block":
                self._on_marker(token.content)
                i += 1
                continue
            if token.type == "table_open":
                i = self._on_table(i)
                continue
            if token.type in ("bullet_list_open", "ordered_list_open"):
                i = self._on_list(i, token.type)
                continue
            if token.type == "paragraph_open":
                content = toks[i + 1].content if i + 1 < n else ""
                self._on_paragraph(content)
                i += 3
                continue
            # DS-14 (T150): capture fenced code blocks as DesignItems
            if token.type == "fence":
                info = token.info.strip() if hasattr(token, "info") else ""
                self._on_fence(info, token.content)
                i += 1
                continue
            i += 1

        if not self.plates and not self.warnings:
            self.warnings.append(
                "设计文档无可识别层次 (无 H2/H3 结构且无 ae 标记), "
                "请加 <!-- ae:* --> 标记或用 vague-requirement 模式"
            )
        return DesignDoc(plates=self.plates, supplements={}, parse_warnings=self.warnings)

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
        # _new_plate() 已赋值 cur_plate, 但 mypy 无法跨方法调用追踪属性窄化
        self.cur_plate.components.append(comp)  # type: ignore[union-attr]
        self.cur_component, self.cur_item = comp, None
        self.last_node = ("component", comp)

    def _new_item(self, text: str) -> None:
        if self.cur_component is None:  # H2→H4 跳级 → 合成 component
            self.warnings.append(f"标题跳级: H4 '{text}' 无 H3 组件祖先, 合成隐式 Component")
            if self.cur_plate is None:
                self._new_plate("(implicit)")
            comp = Component(name="(implicit)", design_section="(implicit)")
            # _new_plate() 已赋值 cur_plate, 但 mypy 无法跨方法调用追踪属性窄化
            self.cur_plate.components.append(comp)  # type: ignore[union-attr]
            self.cur_component = comp
        item = self._make_item(title=text, source_marker="heading", key_claims=[])
        self.cur_component.design_items.append(item)
        self.cur_item = item
        self.last_node = ("item", item)

    def _make_item(
        self, title: str, source_marker: str, key_claims: list[str]
    ) -> DesignItem:
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

    def _on_marker(self, content: str) -> None:
        match = _MARKER_RE.search(content)
        if not match:
            return
        kind = match.group(1)
        attrs = dict(_ATTR_RE.findall(match.group(2)))
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

    def _on_table(self, start: int) -> int:
        """收集 tbody 数据行. 有 cur_item → 并入 key_claims; 否则每行成 DesignItem."""
        toks = self.tokens
        i = start
        in_tbody = False
        row: list[str] = []
        rows: list[list[str]] = []
        while i < len(toks):
            token_type = toks[i].type
            if token_type == "tbody_open":
                in_tbody = True
            elif token_type == "tbody_close":
                in_tbody = False
            elif token_type == "tr_open" and in_tbody:
                row = []
            elif token_type == "inline" and in_tbody:
                row.append(toks[i].content.strip())
            elif token_type == "tr_close" and in_tbody and row:
                rows.append(row)
            elif token_type == "table_close":
                i += 1
                break
            i += 1

        if self.cur_component is None:
            return i  # 表格无组件归属 → 跳过 (结构外)
        for raw_row in rows:
            cells = [cell for cell in raw_row if cell]
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

    def _on_list(self, start: int, open_type: str) -> int:
        close_type = open_type.replace("_open", "_close")
        toks = self.tokens
        i = start
        depth = 0
        texts: list[str] = []
        while i < len(toks):
            token_type = toks[i].type
            if token_type == open_type:
                depth += 1
            elif token_type == close_type:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif token_type == "inline":
                content = toks[i].content.strip()
                if content:
                    texts.append(content)
            i += 1

        if self.cur_component is None:
            return i
        for text in texts:
            if self.cur_item is not None:
                self.cur_item.key_claims.append(text)
            else:
                item = self._make_item(
                    title=text, source_marker="list_item", key_claims=[text]
                )
                self.cur_component.design_items.append(item)
        return i

    def _on_paragraph(self, content: str) -> None:
        content = content.strip()
        if not content:
            return
        # Fix A: when paragraph under H3 component without H4 heading,
        # auto-create a DesignItem from the paragraph text.
        if self.cur_item is None and self.cur_component is not None:
            # Use first sentence (up to 80 chars) as title
            title = content[:80] + ("..." if len(content) > 80 else "")
            item = self._make_item(
                title, source_marker="paragraph", key_claims=[content]
            )
            self.cur_component.design_items.append(item)
            self.cur_item = item
            self.last_node = ("item", item)
            return
        if self.cur_item is not None and any(
            keyword in content for keyword in _CLAIM_KEYWORDS
        ):
            self.cur_item.key_claims.append(content)

    def _on_fence(self, info: str, content: str) -> None:
        """捕获 fenced code block 内容作为 DesignItem。"""
        content = content.strip()
        if not content or self.cur_component is None:
            return
        lang = info.strip() if info else ""
        title = f"[{lang} code]" if lang else "[code block]"
        if len(content) <= 80:
            title = content[:80]
        item = self._make_item(title, source_marker="fence", key_claims=[content])
        self.cur_component.design_items.append(item)
        self.cur_item = item
        self.last_node = ("item", item)


__all__ = ["DesignDocParser"]
