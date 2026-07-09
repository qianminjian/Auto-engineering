"""T5 foundational — engine/verification_layers.py (layer auto-trim).

设计参考: v5.6-Design-Loop.md §B6.9 (VerificationLayers + _determine_verification_layers).

验证层自动裁剪: 根据设计文档层次自动判定 LEAF/PLATE/FULL, 避免冗余验证 agent.
  - LEAF  (5 agents): total_components==1 → 跳过 plate_deep_audit + system_verifier
  - PLATE (6 agents): total_plates==1 & components>1 → 跳过 system_verifier
  - FULL  (7 agents): total_plates>1 → 全部 5 层验证
"""

from __future__ import annotations

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)


def _p(name: str, components: int = 1) -> Plate:
    return Plate(
        name=name, design_section=f"§{name}",
        components=[Component(name=f"{name}_c{i}", design_section=f"§{name}.{i}",
                               design_items=[])
                    for i in range(components)],
        cross_component_contracts_raw=[],
    )


def _design_doc(*names_and_counts: tuple[str, int]) -> DesignDoc:
    plates = [_p(n, c) for n, c in names_and_counts]
    return DesignDoc(plates=plates, supplements=[])


def _batch_plan(*components: str) -> list[dict]:
    return [{"batch_id": f"b-{c}", "component": c, "tasks": []} for c in components]


class TestVerificationLayers:
    def test_enum_values(self) -> None:
        assert VerificationLayers.LEAF.value == "leaf"
        assert VerificationLayers.PLATE.value == "plate"
        assert VerificationLayers.FULL.value == "full"


class TestDetermineFromDesignDoc:
    def test_leaf_single_component_in_single_plate(self) -> None:
        doc = _design_doc(("plate1", 1))
        assert determine_verification_layers(doc, None) == VerificationLayers.LEAF

    def test_plate_multi_component_single_plate(self) -> None:
        doc = _design_doc(("plate1", 3))
        assert determine_verification_layers(doc, None) == VerificationLayers.PLATE

    def test_full_multi_plate(self) -> None:
        doc = _design_doc(("plate1", 2), ("plate2", 1))
        assert determine_verification_layers(doc, None) == VerificationLayers.FULL

    def test_leaf_single_plate_single_component(self) -> None:
        doc = _design_doc(("plate1", 1))
        assert determine_verification_layers(doc, [{"component": "x"}]) == VerificationLayers.LEAF


class TestDetermineFromBatchPlan:
    def test_leaf_single_component_from_batch_plan(self) -> None:
        bp = _batch_plan("StageRouter")
        assert determine_verification_layers(None, bp) == VerificationLayers.LEAF

    def test_plate_multi_component_from_batch_plan(self) -> None:
        bp = _batch_plan("StageRouter", "Orchestrator")
        assert determine_verification_layers(None, bp) == VerificationLayers.PLATE

    def test_batch_plan_always_single_plate(self) -> None:
        """batch_plan 模式恒 total_plates=1, 即使 distinct components>1."""
        bp = _batch_plan("a", "b", "c")
        assert determine_verification_layers(None, bp) == VerificationLayers.PLATE

    def test_batch_plan_missing_component_field_filtered(self) -> None:
        bp = [{"batch_id": "b1", "tasks": []}]  # 无 component 键
        assert determine_verification_layers(None, bp) == VerificationLayers.LEAF

    def test_batch_plan_empty(self) -> None:
        assert determine_verification_layers(None, []) == VerificationLayers.LEAF


class TestBothNone:
    def test_no_input_defaults_to_leaf(self) -> None:
        assert determine_verification_layers(None, None) == VerificationLayers.LEAF


class TestDesignDocWins:
    def test_design_doc_takes_priority_over_batch_plan(self) -> None:
        """有 design_doc 时忽略 batch_plan, 以设计层次为准."""
        doc = _design_doc(("p1", 2), ("p2", 1))  # FULL
        bp = _batch_plan("a")  # 若忽略 doc → LEAF
        assert determine_verification_layers(doc, bp) == VerificationLayers.FULL
