"""T4b — engine/progress_tree.py (ProgressTree 层次化进度看板) 测试.

设计参考: v5.6-Design-Loop.md §B9 (ProgressTree, B9.2~B9.8).

ProgressTree 是人视角进度仪表盘 (与 BatchState 机器视角互补):
  - B9.2 ProgressNode (完成率 property + 生命周期/验证/审计/测试字段)
  - B9.3 ProgressTree (构建/同步/聚合/查询/展示/序列化)
  - B9.4 SyncResult (added/modified/removed/unchanged/conflicts)
  - B9.5 父节点聚合 (task 和 / verifier 优先级 / audit 和 / coverage 加权平均)
  - B9.7 展示折叠 (completion==100 且 verifier pass → [collapsed])
  - B9.8 动态同步 (ref 归一化精确匹配 → added/modified/removed/conflicts)

测试原则 (per pytest-memory-management.md): 单文件 pytest --timeout=60.
"""

from __future__ import annotations

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.progress_tree import (
    ProgressNode,
    ProgressTree,
    SyncResult,
)


def _doc(structure: dict[str, list[tuple[str, str]]]) -> DesignDoc:
    """structure = {plate_name: [(comp_name, comp_section)]}. plate section = §<name>."""
    plates = []
    for pname, comps in structure.items():
        components = [
            Component(name=cn, design_section=cs, design_items=[], source_marker="heading")
            for cn, cs in comps
        ]
        plates.append(Plate(name=pname, design_section=f"§{pname}", components=components))
    return DesignDoc(plates=plates, supplements={})


def _batch(batch_id: str, component: str, section: str, n_tasks: int) -> dict:
    return {
        "batch_id": batch_id,
        "component": component,
        "design_section": section,
        "tasks": [
            {"id": f"{batch_id}-T{i}", "description": "x",
             "module_ref": section, "file_targets": ["a.py"]}
            for i in range(n_tasks)
        ],
        "depends_on": [],
    }


# ---------- B9.2 ProgressNode ----------


class TestProgressNode:
    def test_completion_pct_zero_tasks(self) -> None:
        node = ProgressNode(id="x", name="X", level="component", parent_id="sys",
                            sort_order=0, design_section_ref="§X", design_status="stable")
        assert node.completion_pct == 0.0

    def test_completion_pct_ratio(self) -> None:
        node = ProgressNode(id="x", name="X", level="component", parent_id="sys",
                            sort_order=0, design_section_ref="§X", design_status="stable",
                            total_tasks=4, done_tasks=1)
        assert node.completion_pct == 25.0

    def test_defaults(self) -> None:
        node = ProgressNode(id="x", name="X", level="component", parent_id="sys",
                            sort_order=0, design_section_ref="§X", design_status="stable")
        assert node.version == 1
        assert node.verifier_status == "pending"
        assert node.deep_audit_status == "pending"
        assert node.test_coverage_pct is None


# ---------- B9.3 构建 ----------


class TestBuildFromDesignDoc:
    def test_builds_system_plate_component_hierarchy(self) -> None:
        doc = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        tree = ProgressTree.from_design_doc(doc)
        levels = {n.level for n in tree.nodes.values()}
        assert levels == {"system", "plate", "component"}
        # component ref 归一化
        comp = tree.find_by_design_section("B1")
        assert comp is not None
        assert comp.level == "component"
        assert comp.name == "CompX"

    def test_children_navigation(self) -> None:
        doc = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        tree = ProgressTree.from_design_doc(doc)
        sys_children = tree.children("sys")
        assert len(sys_children) == 1
        assert sys_children[0].level == "plate"
        plate = sys_children[0]
        assert len(tree.children(plate.id)) == 2


class TestBuildFromBatchPlan:
    def test_builds_component_nodes_with_task_counts(self) -> None:
        bp = [_batch("bx1", "CompX", "§B1", 2), _batch("bx2", "CompX", "§B1", 1),
              _batch("by1", "CompY", "§B2", 3)]
        tree = ProgressTree.from_batch_plan(bp, requirement="test req")
        comp_x = tree.find_by_design_section("B1")
        assert comp_x is not None
        assert comp_x.total_tasks == 3  # 2 + 1
        # 系统级聚合
        assert tree.completion_pct("sys") == 0.0
        assert tree.nodes["sys"].total_tasks == 6  # 3 + 3


# ---------- B9.5 父节点聚合 ----------


class TestAggregation:
    def _tree(self) -> ProgressTree:
        doc = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        return ProgressTree.from_design_doc(doc)

    def test_task_sum_propagates_to_root(self) -> None:
        tree = self._tree()
        cx = tree.find_by_design_section("B1")
        cy = tree.find_by_design_section("B2")
        assert cx and cy
        tree.upsert_node(cx.id, total_tasks=4, done_tasks=2)
        tree.upsert_node(cy.id, total_tasks=6, done_tasks=3)
        tree.recalculate_parents(cx.id)
        tree.recalculate_parents(cy.id)
        assert tree.nodes["sys"].total_tasks == 10
        assert tree.nodes["sys"].done_tasks == 5

    def test_verifier_any_failed_makes_parent_failed(self) -> None:
        tree = self._tree()
        cx = tree.find_by_design_section("B1")
        cy = tree.find_by_design_section("B2")
        assert cx and cy
        tree.upsert_node(cx.id, verifier_status="pass")
        tree.upsert_node(cy.id, verifier_status="failed")
        tree.recalculate_parents(cx.id)
        plate = tree.nodes[cx.parent_id]  # type: ignore[index]
        assert plate.verifier_status == "failed"

    def test_verifier_all_pass_makes_parent_pass(self) -> None:
        tree = self._tree()
        cx = tree.find_by_design_section("B1")
        cy = tree.find_by_design_section("B2")
        assert cx and cy
        tree.upsert_node(cx.id, verifier_status="pass")
        tree.upsert_node(cy.id, verifier_status="skipped")
        tree.recalculate_parents(cx.id)
        plate = tree.nodes[cx.parent_id]  # type: ignore[index]
        assert plate.verifier_status == "pass"

    def test_deep_audit_findings_sum(self) -> None:
        tree = self._tree()
        cx = tree.find_by_design_section("B1")
        cy = tree.find_by_design_section("B2")
        assert cx and cy
        tree.upsert_node(cx.id, deep_audit_p0=1, deep_audit_p1=2)
        tree.upsert_node(cy.id, deep_audit_p0=0, deep_audit_p1=3)
        tree.recalculate_parents(cx.id)
        plate = tree.nodes[cx.parent_id]  # type: ignore[index]
        assert plate.deep_audit_p0 == 1
        assert plate.deep_audit_p1 == 5

    def test_coverage_weighted_average(self) -> None:
        tree = self._tree()
        cx = tree.find_by_design_section("B1")
        cy = tree.find_by_design_section("B2")
        assert cx and cy
        tree.upsert_node(cx.id, total_tasks=2, test_coverage_pct=90.0)
        tree.upsert_node(cy.id, total_tasks=8, test_coverage_pct=40.0)
        tree.recalculate_parents(cx.id)
        plate = tree.nodes[cx.parent_id]  # type: ignore[index]
        # (90*2 + 40*8) / 10 = 50
        assert plate.test_coverage_pct == 50.0


# ---------- B9.8 动态同步 ----------


class TestSync:
    def test_modified_preserves_done_tasks_and_bumps_version(self) -> None:
        bp1 = [_batch("bx1", "CompX", "§B1", 2)]
        tree = ProgressTree.from_batch_plan(bp1, requirement="r")
        cx = tree.find_by_design_section("B1")
        assert cx
        tree.upsert_node(cx.id, done_tasks=1)  # 模拟已完成 1 个
        old_version = tree.nodes[cx.id].version
        # batch_plan 更新: CompX task 数 2→3
        bp2 = [_batch("bx1", "CompX", "§B1", 3)]
        result = tree.sync_from_batch_plan(bp2)
        assert isinstance(result, SyncResult)
        assert cx.id in result.modified
        assert tree.nodes[cx.id].total_tasks == 3
        assert tree.nodes[cx.id].done_tasks == 1  # 保留
        assert tree.nodes[cx.id].version == old_version + 1

    def test_added_new_component(self) -> None:
        doc1 = _doc({"PlateA": [("CompX", "§B1")]})
        tree = ProgressTree.from_design_doc(doc1)
        doc2 = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        result = tree.sync_from_design_doc(doc2)
        added_refs = [tree.nodes[i].design_section_ref for i in result.added]
        assert "§B2" in added_refs
        assert tree.nodes["§B2"].version == 1

    def test_removed_marks_not_deletes(self) -> None:
        doc1 = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        tree = ProgressTree.from_design_doc(doc1)
        doc2 = _doc({"PlateA": [("CompX", "§B1")]})  # CompY 消失
        result = tree.sync_from_design_doc(doc2)
        assert "§B2" in result.removed
        assert "§B2" in tree.nodes  # 未删除
        assert tree.nodes["§B2"].design_status == "removed"

    def test_conflicts_dangling_parent_not_added(self) -> None:
        """component 的 parent plate 不可识别 (无 ref 无 name) → conflicts, 不添加."""
        doc1 = _doc({"PlateA": [("CompX", "§B1")]})
        tree = ProgressTree.from_design_doc(doc1)
        # 悬空: plate 无 name 无 section → 不可识别; 其 component 悬空
        ghost_plate = Plate(
            name="", design_section="",
            components=[Component(name="Ghost", design_section="§ZZ",
                                  design_items=[], source_marker="heading")],
        )
        doc2 = DesignDoc(plates=[*doc1.plates, ghost_plate], supplements={})
        result = tree.sync_from_design_doc(doc2)
        assert len(result.conflicts) >= 1
        assert "§ZZ" not in tree.nodes  # 未添加

    def test_conflicts_non_blocking(self) -> None:
        """conflicts 不阻塞 — sync 正常返回, 其它节点照常处理."""
        doc1 = _doc({"PlateA": [("CompX", "§B1")]})
        tree = ProgressTree.from_design_doc(doc1)
        ghost_plate = Plate(name="", design_section="",
                            components=[Component(name="Ghost", design_section="§ZZ",
                                                  design_items=[], source_marker="heading")])
        doc2 = DesignDoc(
            plates=[*doc1.plates,
                    Plate(name="PlateB", design_section="§PB",
                          components=[Component(name="CompZ", design_section="§B9",
                                                design_items=[], source_marker="heading")]),
                    ghost_plate],
            supplements={},
        )
        result = tree.sync_from_design_doc(doc2)
        # 冲突不阻塞: 正常节点 CompZ 仍被添加
        assert "§B9" in tree.nodes
        assert len(result.conflicts) >= 1


# ---------- B9.7 展示折叠 ----------


class TestDisplay:
    def _completed_tree(self) -> ProgressTree:
        doc = _doc({"PlateDone": [("CompA", "§B1")]})
        tree = ProgressTree.from_design_doc(doc)
        ca = tree.find_by_design_section("B1")
        assert ca
        tree.upsert_node(ca.id, total_tasks=2, done_tasks=2, verifier_status="pass")
        tree.recalculate_parents(ca.id)
        return tree

    def test_completed_plate_collapsed(self) -> None:
        tree = self._completed_tree()
        out = tree.display(active_only=True)
        assert "[collapsed]" in out
        assert "PlateDone" in out

    def test_incomplete_plate_expanded(self) -> None:
        doc = _doc({"PlateWIP": [("CompA", "§B1")]})
        tree = ProgressTree.from_design_doc(doc)
        ca = tree.find_by_design_section("B1")
        assert ca
        tree.upsert_node(ca.id, total_tasks=2, done_tasks=1, verifier_status="pending")
        tree.recalculate_parents(ca.id)
        out = tree.display(active_only=True)
        assert "[collapsed]" not in out
        assert "CompA" in out  # 子组件展开

    def test_active_only_false_disables_collapse(self) -> None:
        tree = self._completed_tree()
        out = tree.display(active_only=False)
        assert "[collapsed]" not in out
        assert "CompA" in out


# ---------- 序列化 ----------


class TestSerialization:
    def test_to_dict_from_dict_round_trip(self) -> None:
        doc = _doc({"PlateA": [("CompX", "§B1"), ("CompY", "§B2")]})
        tree = ProgressTree.from_design_doc(doc)
        cx = tree.find_by_design_section("B1")
        assert cx
        tree.upsert_node(cx.id, total_tasks=5, done_tasks=2, verifier_status="pass")
        d = tree.to_dict()
        restored = ProgressTree.from_dict(d)
        assert set(restored.nodes.keys()) == set(tree.nodes.keys())
        rcx = restored.find_by_design_section("B1")
        assert rcx
        assert rcx.total_tasks == 5
        assert rcx.done_tasks == 2
        assert rcx.verifier_status == "pass"
