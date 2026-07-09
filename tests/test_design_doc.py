"""T4 — engine/design_doc.py (DesignDoc.parse 层次识别) 测试.

设计参考: v5.6-Design-Loop.md §B10.4a (DesignDoc.parse 契约与层次识别, DS-6 权威定义).

层次识别混合策略:
  ① 标题层级启发: H2→Plate, H3→Component, H4/表格行/列表项→DesignItem
  ② <!-- ae:* --> HTML 注释标记消歧 (优先于启发, 冲突时 marker 赢)
  ③ 解析不确定 → parse_warnings (喂 gap_scan)

parse() 只做结构识别 (确定性 Python), 不做语义充分性判定 (那是 gap_scan Agent).

测试原则 (per pytest-memory-management.md): 单文件 pytest --timeout=60.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.design_doc import (
    Component,
    DesignDoc,
    DesignItem,
    Plate,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "design.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------- 数据模型字段 ----------


class TestDataModels:
    """DesignItem / Component / Plate / DesignDoc 数据类字段 (§B10.4a)."""

    def test_design_item_fields(self) -> None:
        item = DesignItem(
            item_id="B2-1",
            design_section="§B2",
            title="StageRouter.next",
            key_claims=["23 转换", "refine_allowed"],
            source_marker="heading",
        )
        assert item.item_id == "B2-1"
        assert item.design_section == "§B2"
        assert item.title == "StageRouter.next"
        assert item.key_claims == ["23 转换", "refine_allowed"]
        assert item.source_marker == "heading"

    def test_component_fields(self) -> None:
        comp = Component(
            name="StageRouter",
            design_section="§B2",
            design_items=[],
            source_marker="heading",
        )
        assert comp.name == "StageRouter"
        assert comp.design_section == "§B2"
        assert comp.design_items == []
        assert comp.source_marker == "heading"

    def test_plate_fields_and_contracts_method(self) -> None:
        plate = Plate(
            name="Engine层",
            design_section="§B",
            components=[],
            cross_component_contracts_raw=["A->B", "C==D"],
        )
        assert plate.name == "Engine层"
        assert plate.components == []
        # cross_component_contracts() 返回 raw list
        assert plate.cross_component_contracts() == ["A->B", "C==D"]

    def test_design_doc_defaults(self) -> None:
        doc = DesignDoc(plates=[], supplements={})
        assert doc.plates == []
        assert doc.supplements == {}
        assert doc.parse_warnings == []


# ---------- ① 标题层级启发 ----------


class TestHeadingHeuristics:
    """H2→Plate / H3→Component / H4→DesignItem 层次识别."""

    def test_h2_becomes_plate(self, tmp_path: Path) -> None:
        doc = DesignDoc.parse(_write(tmp_path, "## B6. Agent 规格\n"))
        assert len(doc.plates) == 1
        assert doc.plates[0].design_section == "§B6"

    def test_h3_becomes_component_under_plate(self, tmp_path: Path) -> None:
        doc = DesignDoc.parse(
            _write(tmp_path, "## B6. Agent 规格\n### B6.1 ArchitectAgent\n")
        )
        assert len(doc.plates) == 1
        comps = doc.plates[0].components
        assert len(comps) == 1
        assert comps[0].name == "ArchitectAgent"
        assert comps[0].design_section == "§B6.1"

    def test_h4_becomes_design_item_under_component(self, tmp_path: Path) -> None:
        md = (
            "## B6. Agent 规格\n"
            "### B6.1 ArchitectAgent\n"
            "#### 批次规划\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        comp = doc.plates[0].components[0]
        assert len(comp.design_items) == 1
        assert comp.design_items[0].title == "批次规划"
        assert comp.design_items[0].source_marker == "heading"

    def test_item_id_format_section_dash_seq(self, tmp_path: Path) -> None:
        md = (
            "## B2. Router\n"
            "### B2.1 StageRouter\n"
            "#### 第一项\n"
            "#### 第二项\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        items = doc.plates[0].components[0].design_items
        assert items[0].item_id == "B2.1-1"
        assert items[1].item_id == "B2.1-2"

    def test_multiple_plates(self, tmp_path: Path) -> None:
        md = "## B6. Agent\n### B6.1 X\n## B7. Gate\n### B7.1 Y\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        assert len(doc.plates) == 2
        assert doc.plates[0].components[0].name == "X"
        assert doc.plates[1].components[0].name == "Y"

    def test_h1_and_part_ignored(self, tmp_path: Path) -> None:
        md = "# PART I 总览\n## B6. Agent\n### B6.1 X\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        # H1 不产生 plate; 只有 H2 的 B6
        assert len(doc.plates) == 1
        assert doc.plates[0].design_section == "§B6"

    def test_heading_without_number_uses_slug(self, tmp_path: Path) -> None:
        doc = DesignDoc.parse(_write(tmp_path, "## Engine 层\n### StageRouter\n"))
        assert len(doc.plates) == 1
        # 无编号 → design_section 用标题 slug (非空, 含标题信息)
        assert doc.plates[0].name == "Engine 层"
        assert doc.plates[0].components[0].name == "StageRouter"


# ---------- 表格行 / 列表项 → DesignItem 或 key_claims ----------


class TestTablesAndLists:
    """表格行/列表项作为 DesignItem 或 key_claims (§B10.4a ③)."""

    def test_table_rows_become_design_items(self, tmp_path: Path) -> None:
        md = (
            "## B2. Router\n"
            "### B2.1 StageRouter\n"
            "| 转换 | 条件 |\n"
            "|------|------|\n"
            "| T1 | stage=='' |\n"
            "| T2 | architect |\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        items = doc.plates[0].components[0].design_items
        table_items = [i for i in items if i.source_marker == "table_row"]
        # 两条数据行 (表头不算)
        assert len(table_items) == 2

    def test_list_items_captured(self, tmp_path: Path) -> None:
        md = (
            "## B2. Router\n"
            "### B2.1 StageRouter\n"
            "- 必须支持 23 转换\n"
            "- refine_source_count 上限 2\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        comp = doc.plates[0].components[0]
        # 列表项被捕获 (作为 DesignItem 或某 item 的 key_claims)
        all_text = " ".join(
            [i.title for i in comp.design_items]
            + [c for i in comp.design_items for c in i.key_claims]
        )
        assert "23 转换" in all_text
        assert "refine_source_count" in all_text

    def test_constraint_sentence_captured_in_key_claims(self, tmp_path: Path) -> None:
        md = (
            "## B2. Router\n"
            "### B2.1 StageRouter\n"
            "#### 计数规则\n"
            "refine_global_count 必须 ≤ 4, 否则触发 T9-LIMIT。\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        item = doc.plates[0].components[0].design_items[0]
        joined = " ".join(item.key_claims)
        assert "必须" in joined or "≤" in joined


# ---------- ② 显式标记消歧 ----------


class TestMarkerOverride:
    """<!-- ae:* --> 标记覆盖启发 (§B10.4a ②, 冲突时 marker 赢)."""

    def test_plate_marker_overrides_name_and_sets_contracts(
        self, tmp_path: Path
    ) -> None:
        md = (
            "## Engine 层\n"
            '<!-- ae:plate name="Engine层" contracts="A->B; C==D" -->\n'
            "### StageRouter\n"
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        plate = doc.plates[0]
        assert plate.name == "Engine层"
        assert plate.cross_component_contracts() == ["A->B", "C==D"]

    def test_component_marker_overrides_name(self, tmp_path: Path) -> None:
        md = (
            "## B6. Agent\n"
            "### 调度器组件\n"
            '<!-- ae:component name="StageRouter" -->\n'
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        assert doc.plates[0].components[0].name == "StageRouter"

    def test_design_item_marker_sets_title_and_claims(self, tmp_path: Path) -> None:
        md = (
            "## B2. Router\n"
            "### B2.1 StageRouter\n"
            "#### 原始标题\n"
            '<!-- ae:design-item title="转换表" claims="T1->architect; T4->stop" -->\n'
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        item = doc.plates[0].components[0].design_items[0]
        assert item.title == "转换表"
        assert item.key_claims == ["T1->architect", "T4->stop"]
        assert item.source_marker == "explicit_marker"

    def test_marker_wins_on_type_conflict(self, tmp_path: Path) -> None:
        """H3 启发为 Component, 但 ae:plate 标记 → 重分类为 Plate."""
        md = (
            "## B6. Agent\n"
            "### 其实是板块\n"
            '<!-- ae:plate name="独立板块" -->\n'
        )
        doc = DesignDoc.parse(_write(tmp_path, md))
        # marker 赢: 该节点成为 Plate 而非 Component
        plate_names = [p.name for p in doc.plates]
        assert "独立板块" in plate_names


# ---------- 异常结构处理决策表 ----------


class TestExceptionTable:
    """§B10.4a 异常结构处理决策表."""

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            DesignDoc.parse(tmp_path / "nonexistent.md")

    def test_no_structure_empty_plates_with_warning(self, tmp_path: Path) -> None:
        md = "这是一段没有任何标题层次的自由文本。\n没有 H2/H3, 也没有 ae 标记。\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        assert doc.plates == []
        assert len(doc.parse_warnings) >= 1
        assert any("层次" in w or "结构" in w for w in doc.parse_warnings)

    def test_component_without_items_kept_empty(self, tmp_path: Path) -> None:
        md = "## B6. Agent\n### B6.1 空组件\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        comp = doc.plates[0].components[0]
        assert comp.name == "空组件"
        assert comp.design_items == []

    def test_heading_skip_h2_to_h4_records_warning(self, tmp_path: Path) -> None:
        md = "## B6. Agent\n#### 跳级项\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        # H2 直接到 H4 (跳过 H3): 记 parse_warning
        assert len(doc.parse_warnings) >= 1


# ---------- 与 batch_plan 一致性 ----------


class TestBatchPlanConsistency:
    """Component.name 须为可用作 batch_plan[].component 的纯字符串 (§B10.4a)."""

    def test_component_name_is_plain_string(self, tmp_path: Path) -> None:
        md = "## B6. Agent\n### B6.1 ArchitectAgent\n"
        doc = DesignDoc.parse(_write(tmp_path, md))
        name = doc.plates[0].components[0].name
        assert isinstance(name, str)
        assert name  # 非空
        assert "\n" not in name
