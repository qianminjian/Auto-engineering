"""T5 foundational — DesignDoc/Component/Plate accessors for _build_action.

设计参考: v5.6-Design-Loop.md §C.5.6 (_build_action verifier/audit context).

TickOrchestrator._build_action 在构造 verifier/audit action 的 context 时需要:
  - Component.design_spec_summary(): 组件设计条目摘要 (component_verifier context)
  - Plate.components_summary():      板块内组件清单 (plate_deep_audit context)
  - DesignDoc.path:                  文档路径 (system_verifier context)
  - DesignDoc.sections_summary():    全量设计章节清单 (system_verifier context)
"""

from __future__ import annotations

from auto_engineering.engine.design_doc import (
    Component,
    DesignDoc,
    DesignItem,
    Plate,
)


def _item(item_id: str, title: str, claims: list[str]) -> DesignItem:
    return DesignItem(
        item_id=item_id, design_section=f"§{item_id}", title=title,
        key_claims=claims, source_marker="heading",
    )


class TestComponentDesignSpecSummary:
    def test_joins_items_and_claims(self) -> None:
        comp = Component(
            name="StageRouter", design_section="§B2",
            design_items=[
                _item("B2-1", "StageDecision dataclass", ["必须含 next_stage", "should_stop"]),
                _item("B2-2", "next() 方法", ["shall route T1-T22"]),
            ],
        )
        summary = comp.design_spec_summary()
        assert "StageDecision dataclass" in summary
        assert "必须含 next_stage" in summary
        assert "next() 方法" in summary

    def test_empty_items_returns_empty_string(self) -> None:
        comp = Component(name="X", design_section="§X", design_items=[])
        assert comp.design_spec_summary() == ""


class TestPlateComponentsSummary:
    def test_lists_components(self) -> None:
        plate = Plate(
            name="Engine层", design_section="§B",
            components=[
                Component(name="StageRouter", design_section="§B2",
                          design_items=[_item("B2-1", "t", [])]),
                Component(name="Orchestrator", design_section="§B7",
                          design_items=[]),
            ],
        )
        summary = plate.components_summary()
        assert len(summary) == 2
        names = {c["name"] for c in summary}
        assert names == {"StageRouter", "Orchestrator"}
        sr = next(c for c in summary if c["name"] == "StageRouter")
        assert sr["design_section"] == "§B2"
        assert sr["design_items"] == 1

    def test_empty_plate(self) -> None:
        plate = Plate(name="Empty", design_section="§E", components=[])
        assert plate.components_summary() == []


class TestDesignDocPath:
    def test_path_defaults_none(self) -> None:
        doc = DesignDoc(plates=[], supplements={})
        assert doc.path is None

    def test_parse_stores_path(self, tmp_path) -> None:
        f = tmp_path / "design.md"
        f.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        doc = DesignDoc.parse(f)
        assert doc.path == str(f)


class TestDesignDocSectionsSummary:
    def test_flattens_plate_component_sections(self) -> None:
        doc = DesignDoc(
            plates=[
                Plate(name="P1", design_section="§P1", components=[
                    Component(name="C1", design_section="§B2", design_items=[]),
                    Component(name="C2", design_section="§B7", design_items=[]),
                ]),
                Plate(name="P2", design_section="§P2", components=[
                    Component(name="C3", design_section="§B9", design_items=[]),
                ]),
            ],
            supplements={},
        )
        sections = doc.sections_summary()
        assert len(sections) == 3
        refs = {s["design_section"] for s in sections}
        assert refs == {"§B2", "§B7", "§B9"}
        c1 = next(s for s in sections if s["component"] == "C1")
        assert c1["plate"] == "P1"

    def test_empty_doc(self) -> None:
        assert DesignDoc(plates=[], supplements={}).sections_summary() == []
