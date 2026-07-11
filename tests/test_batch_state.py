"""T3 — engine/batch_state.py (BatchState 组件/板块进度游标) 测试.

设计参考: v5.6-Design-Loop.md §B1.1a (BatchState 权威定义, DS-4).

BatchState 维护 plate → component → batch 三级游标 (机器视角路由状态):
  - design-doc 模式: plates = DesignDoc.plates (真实层次)
  - batch_plan 模式: 合成单一 plate 包裹 distinct components (恒 total_plates=1)

访问方法确定性无副作用 (越界加断言兜底); 推进方法有副作用 (仅 Orchestrator 调).
序列化只存游标 (3 int + total_batches), plates 每 tick 重建
(design_doc 重 parse / batch_plan 重合成).

测试原则 (per pytest-memory-management.md): 单文件 pytest --timeout=60.
"""

from __future__ import annotations

import json
import logging

import pytest

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.loop.plan import Plan, Task


def _batch(batch_id: str, component: str, section: str = "") -> dict:
    return {
        "batch_id": batch_id,
        "component": component,
        "design_section": section,
        "tasks": [{"id": f"{batch_id}-T1", "description": "x",
                   "module_ref": section, "file_targets": ["a.py"]}],
        "depends_on": [],
    }


def _design_doc(structure: dict[str, list[str]]) -> DesignDoc:
    """structure = {plate_name: [component_names]}."""
    plates = []
    for pname, comps in structure.items():
        components = [
            Component(name=c, design_section=f"§{c}", design_items=[], source_marker="heading")
            for c in comps
        ]
        plates.append(Plate(name=pname, design_section=f"§{pname}", components=components))
    return DesignDoc(plates=plates, supplements={})


# ---------- 构造 ----------


class TestConstruction:
    def test_from_batch_plan_single_synthetic_plate(self) -> None:
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY"), _batch("b3", "CompX")]
        bs = BatchState.from_batch_plan(bp)
        assert len(bs.plates) == 1
        assert bs.plates[0].name == "(single)"
        # distinct components 按出现顺序
        names = [c.name for c in bs.plates[0].components]
        assert names == ["CompX", "CompY"]
        assert bs.total_batches == 3
        assert bs.current_plate_idx == 0
        assert bs.current_component_idx == 0
        assert bs.current_batch_idx == 0

    def test_from_design_doc_uses_real_plates(self) -> None:
        doc = _design_doc({"PlateA": ["CompX", "CompY"], "PlateB": ["CompZ"]})
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY"), _batch("b3", "CompZ")]
        bs = BatchState.from_design_doc(doc, bp)
        assert len(bs.plates) == 2
        assert bs.total_batches == 3

    def test_from_design_doc_orphan_batch_raises(self) -> None:
        """batch component 不在任何 plate → 构造抛错 (G2 retry)."""
        doc = _design_doc({"PlateA": ["CompX"]})
        bp = [_batch("b1", "CompX"), _batch("b2", "OrphanComp")]
        with pytest.raises(ValueError, match=r"OrphanComp|孤儿"):
            BatchState.from_design_doc(doc, bp)

    def test_from_design_doc_zero_batch_component_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """design_doc 有组件但无对应 batch → WARN (不抛错)."""
        doc = _design_doc({"PlateA": ["CompX", "CompNoBatch"]})
        bp = [_batch("b1", "CompX")]
        with caplog.at_level(logging.WARNING):
            bs = BatchState.from_design_doc(doc, bp)
        assert bs.total_batches == 1
        assert any("CompNoBatch" in r.message for r in caplog.records)


# ---------- 访问方法 ----------


class TestAccessors:
    def _bs(self) -> BatchState:
        doc = _design_doc({"PlateA": ["CompX", "CompY"], "PlateB": ["CompZ"]})
        bp = [_batch("bx1", "CompX", "B1"), _batch("bx2", "CompX", "B1"),
              _batch("by1", "CompY", "B2"), _batch("bz1", "CompZ", "B3")]
        return BatchState.from_design_doc(doc, bp)

    def test_current_plate_component_names(self) -> None:
        bs = self._bs()
        assert bs.current_plate().name == "PlateA"
        assert bs.current_component().name == "CompX"
        assert bs.current_component_name() == "CompX"
        assert bs.current_design_section() == "§CompX"

    def test_current_batch_and_id(self) -> None:
        bs = self._bs()
        assert bs.current_batch()["batch_id"] == "bx1"
        assert bs.current_batch_id() == "bx1"

    def test_batches_for_filters_and_preserves_order(self) -> None:
        bs = self._bs()
        comp_x = bs.plates[0].components[0]
        batches = bs.batches_for(comp_x)
        assert [b["batch_id"] for b in batches] == ["bx1", "bx2"]

    def test_current_batch_tasks_filters_developer_by_batch(self) -> None:
        bs = self._bs()
        # bx1 batch 的 task id = "bx1-T1"
        plan = Plan(tasks=[
            Task(id="bx1-T1", role="developer"),
            Task(id="bx2-T1", role="developer"),
            Task(id="bx1-T1-crit", role="critic"),
        ])
        tasks = bs.current_batch_tasks(plan)
        assert [t.id for t in tasks] == ["bx1-T1"]


# ---------- 推进方法 ----------


class TestAdvance:
    def _bs(self) -> BatchState:
        doc = _design_doc({"PlateA": ["CompX", "CompY"]})
        bp = [_batch("bx1", "CompX"), _batch("bx2", "CompX"), _batch("by1", "CompY")]
        return BatchState.from_design_doc(doc, bp)

    def test_advance_batch(self) -> None:
        bs = self._bs()
        bs.advance_batch()
        assert bs.current_batch_idx == 1
        assert bs.current_component_idx == 0

    def test_advance_component_resets_batch(self) -> None:
        bs = self._bs()
        bs.advance_batch()
        bs.advance_component()
        assert bs.current_component_idx == 1
        assert bs.current_batch_idx == 0

    def test_advance_plate_resets_component_and_batch(self) -> None:
        bs = self._bs()
        bs.advance_batch()
        bs.advance_component()
        bs.advance_plate()
        assert bs.current_plate_idx == 1
        assert bs.current_component_idx == 0
        assert bs.current_batch_idx == 0


# ---------- 完成判定 ----------


class TestCompletion:
    def _bs(self) -> BatchState:
        doc = _design_doc({"PlateA": ["CompX", "CompY"]})
        bp = [_batch("bx1", "CompX"), _batch("bx2", "CompX"), _batch("by1", "CompY")]
        return BatchState.from_design_doc(doc, bp)

    def test_component_complete_when_batches_exhausted(self) -> None:
        bs = self._bs()  # CompX 有 2 batch
        assert bs.is_component_complete() is False
        bs.advance_batch()
        assert bs.is_component_complete() is False
        bs.advance_batch()  # idx=2 >= 2
        assert bs.is_component_complete() is True

    def test_plate_complete_when_components_exhausted(self) -> None:
        bs = self._bs()  # PlateA 有 2 component
        assert bs.is_plate_complete() is False
        bs.advance_component()
        assert bs.is_plate_complete() is False
        bs.advance_component()  # idx=2 >= 2
        assert bs.is_plate_complete() is True

    def test_all_complete_when_plates_exhausted(self) -> None:
        bs = self._bs()  # 1 plate
        assert bs.is_all_complete() is False
        bs.advance_plate()  # idx=1 >= 1
        assert bs.is_all_complete() is True

    def test_helper_predicates(self) -> None:
        bs = self._bs()
        comp_x = bs.current_component()
        assert bs.has_more_batches_for(comp_x) is True
        assert bs.has_more_components_in_plate() is True
        assert bs.has_more_plates() is True

    def test_completion_predicates_total_when_all_done(self) -> None:
        """所有游标出界后 completion 谓词仍安全 (不抛)."""
        bs = self._bs()
        bs.advance_plate()
        assert bs.is_all_complete() is True
        assert bs.is_plate_complete() is True
        assert bs.is_component_complete() is True


# ---------- 边界守卫 ----------


class TestBoundaryGuards:
    def test_current_batch_asserts_when_component_complete(self) -> None:
        doc = _design_doc({"PlateA": ["CompX"]})
        bp = [_batch("bx1", "CompX")]
        bs = BatchState.from_design_doc(doc, bp)
        bs.advance_batch()  # 出界
        assert bs.is_component_complete() is True
        with pytest.raises(AssertionError):
            bs.current_batch()

    def test_current_component_asserts_when_plate_complete(self) -> None:
        doc = _design_doc({"PlateA": ["CompX"]})
        bp = [_batch("bx1", "CompX")]
        bs = BatchState.from_design_doc(doc, bp)
        bs.advance_component()  # 出界
        assert bs.is_plate_complete() is True
        with pytest.raises(AssertionError):
            bs.current_component()


# ---------- 序列化 ----------


class TestSerialization:
    def test_to_json_stores_cursors_and_batch_plan_no_plates(self) -> None:
        """T9a: 序列化含游标 + batch_plan (seed), 但不存 plates (重嵌套树).

        batch_plan 内嵌使 batch_state_json 自包含 (#6 跨 tick 被清空, 不可依赖);
        plates 仍从 seed 重建, 不持久化 Plate/Component/DesignItem 深层树.
        """
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY")]
        bs = BatchState.from_batch_plan(bp)
        bs.advance_batch()
        data = json.loads(bs.to_json())
        assert set(data.keys()) == {
            "current_plate_idx", "current_component_idx",
            "current_batch_idx", "total_batches", "batch_plan",
        }
        assert data["current_batch_idx"] == 1
        assert data["total_batches"] == 2
        assert "plates" not in data  # 重嵌套树不持久化 (主设计决策保留)
        assert data["batch_plan"] == bp  # 轻量 seed 内嵌

    def test_from_json_self_contained_without_batch_plan_arg(self) -> None:
        """T9a: from_json 不传 batch_plan 也能重建 (内嵌 seed 自足)."""
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY")]
        bs = BatchState.from_batch_plan(bp)
        bs.advance_batch()
        restored = BatchState.from_json(bs.to_json(), design_doc=None)
        assert restored.current_batch_idx == 1
        assert [c.name for c in restored.plates[0].components] == ["CompX", "CompY"]

    def test_from_json_batch_plan_mode_round_trip(self) -> None:
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY")]
        bs = BatchState.from_batch_plan(bp)
        bs.advance_batch()
        s = bs.to_json()
        restored = BatchState.from_json(s, design_doc=None, batch_plan=bp)
        assert restored.current_batch_idx == 1
        assert restored.total_batches == 2
        assert restored.plates[0].name == "(single)"
        assert [c.name for c in restored.plates[0].components] == ["CompX", "CompY"]

    def test_from_json_design_doc_mode_rebuilds_real_plates(self) -> None:
        doc = _design_doc({"PlateA": ["CompX", "CompY"]})
        bp = [_batch("b1", "CompX"), _batch("b2", "CompY")]
        bs = BatchState.from_design_doc(doc, bp)
        bs.advance_component()
        s = bs.to_json()
        restored = BatchState.from_json(s, design_doc=doc, batch_plan=bp)
        assert restored.current_component_idx == 1
        assert len(restored.plates) == 1
        assert restored.plates[0].name == "PlateA"
