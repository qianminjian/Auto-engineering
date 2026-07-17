"""ProgressTree — 层次化进度看板 (B9, 人视角进度仪表盘).

与 BatchState (机器视角路由状态) 互补: ProgressTree 只做进度展示/聚合, **从不参与路由**.

结构: system → plate → component → module 四级 ProgressNode.
  - from_design_doc: 真实板块层次 (system/plate/component)
  - from_batch_plan: 单一系统下按 distinct component 建节点 (task 数来自 batch)

动态同步 (B9.8): design_section_ref 归一化后**精确**匹配, 逐节点决策
  added / modified / removed / conflicts (conflicts 非阻塞, 纯看板不 block 主循环).

父节点聚合 (B9.5): task 和 / verifier 优先级 / audit 和 / coverage 加权平均, 向上递归.

参考: v5.6-Design-Loop.md §B9.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from auto_engineering.engine.design_doc import DesignDoc

# ============================================================
# B9.2 ProgressNode
# ============================================================


@dataclass
class ProgressNode:
    """层次进度节点 — 动态演进, 非一次性快照."""
    id: str
    name: str
    level: str                       # "system"|"plate"|"component"|"module"
    parent_id: str | None
    sort_order: int
    design_section_ref: str
    design_status: str               # "locked"|"stable"|"fuzzy"|"pending"|"removed"
    version: int = 1

    total_tasks: int = 0
    done_tasks: int = 0
    current_task: str | None = None

    verifier_status: str = "pending"  # "pending"|"pass"|"failed"|"skipped"
    verifier_missing: int = 0
    verifier_diverged: int = 0

    deep_audit_status: str = "pending"
    deep_audit_p0: int = 0
    deep_audit_p1: int = 0
    deep_audit_p2: int = 0

    test_coverage_pct: float | None = None

    gate_pass_count: int = 0
    gate_run_count: int = 0

    created_at: str = ""
    updated_at: str = ""

    @property
    def completion_pct(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.done_tasks / self.total_tasks * 100


# ============================================================
# B9.4 SyncResult
# ============================================================


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


# ============================================================
# helpers
# ============================================================


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_ref(ref: str) -> str:
    """归一化: strip 空白 + 统一 § 前缀. 'B6.1'/' §B6.1 ' → '§B6.1'; '' → ''."""
    s = ref.strip()
    if not s:
        return ""
    s = s.lstrip("§").strip()
    return f"§{s}"


def _slug(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip())


def _plate_id(plate) -> str | None:
    ref = _normalize_ref(plate.design_section)
    if ref:
        return ref
    if plate.name.strip():
        return f"plate/{_slug(plate.name)}"
    return None  # 不可识别 → 悬空


def _component_id(comp) -> str:
    ref = _normalize_ref(comp.design_section)
    if ref:
        return ref
    return f"comp/{_slug(comp.name)}"


# ============================================================
# B9.3 ProgressTree
# ============================================================


@dataclass
class ProgressTree:
    """系统级进度树 — 动态演进核心数据结构."""
    system_id: str
    system_name: str
    design_doc_path: str | None
    nodes: dict[str, ProgressNode] = field(default_factory=dict)
    design_doc_version: int = 1
    updated_at: str = ""
    last_displayed_tick: int = 0

    # ---------- 工厂 ----------

    @classmethod
    def from_design_doc(cls, doc: DesignDoc, design_doc_path: str | None = None) -> ProgressTree:
        tree = cls(system_id="sys", system_name="system", design_doc_path=design_doc_path)
        tree._add_system()
        for pi, plate in enumerate(doc.plates):
            pid = _plate_id(plate)
            if pid is None:
                continue  # 悬空 plate 跳过 (其 component 在 sync 时报 conflict)
            tree._put(ProgressNode(
                id=pid, name=plate.name, level="plate", parent_id="sys",
                sort_order=pi, design_section_ref=_normalize_ref(plate.design_section),
                design_status="stable", created_at=_now(), updated_at=_now(),
            ))
            for ci, comp in enumerate(plate.components):
                cid = _component_id(comp)
                tree._put(ProgressNode(
                    id=cid, name=comp.name, level="component", parent_id=pid,
                    sort_order=ci, design_section_ref=_normalize_ref(comp.design_section),
                    design_status="stable", created_at=_now(), updated_at=_now(),
                ))
        return tree

    @classmethod
    def from_batch_plan(cls, batch_plan: list[dict], requirement: str) -> ProgressTree:
        tree = cls(system_id="sys", system_name=requirement[:60] or "system",
                   design_doc_path=None)
        tree._add_system()
        # distinct component 按出现顺序; total_tasks = 该 component 所有 batch 的 task 数
        seen: dict[str, str] = {}  # component name → node id
        for b in batch_plan:
            comp_name = b["component"]
            section = b.get("design_section", "")
            n = len(b.get("tasks", []))
            ref = _normalize_ref(section)
            cid = ref if ref else f"comp/{_slug(comp_name)}"
            if cid not in seen.values():
                tree._put(ProgressNode(
                    id=cid, name=comp_name, level="component", parent_id="sys",
                    sort_order=len(seen), design_section_ref=ref,
                    design_status="stable", total_tasks=n,
                    created_at=_now(), updated_at=_now(),
                ))
                seen[comp_name] = cid
            else:
                tree.nodes[cid].total_tasks += n
        tree._recalc_root()
        return tree

    def _add_system(self) -> None:
        self._put(ProgressNode(
            id="sys", name=self.system_name, level="system", parent_id=None,
            sort_order=0, design_section_ref="", design_status="stable",
            created_at=_now(), updated_at=_now(),
        ))

    def _put(self, node: ProgressNode) -> None:
        self.nodes[node.id] = node

    def _recalc_root(self) -> None:
        for nid, node in self.nodes.items():
            if node.level == "component":
                self.recalculate_parents(nid)

    # ---------- 动态同步 (B9.8) ----------

    def sync_from_design_doc(self, doc: DesignDoc) -> SyncResult:
        # 目标节点: (id, parent_id | None, level, name, ref, total_tasks)
        targets: list[tuple[str, str | None, str, str, str, int]] = []
        for plate in doc.plates:
            pid = _plate_id(plate)
            if pid is not None:
                targets.append((pid, "sys", "plate", plate.name,
                                _normalize_ref(plate.design_section), 0))
            for comp in plate.components:
                cid = _component_id(comp)
                parent = pid  # 悬空 plate → parent=None → conflict
                targets.append((cid, parent, "component", comp.name,
                                _normalize_ref(comp.design_section), 0))
        self.design_doc_version += 1
        return self._apply_sync(targets, structural=True)

    def sync_from_batch_plan(self, batch_plan: list[dict]) -> SyncResult:
        counts: dict[str, int] = {}
        meta: dict[str, tuple[str, str]] = {}  # cid → (name, ref)
        order: list[str] = []
        for b in batch_plan:
            comp_name = b["component"]
            ref = _normalize_ref(b.get("design_section", ""))
            cid = ref if ref else f"comp/{_slug(comp_name)}"
            if cid not in counts:
                counts[cid] = 0
                meta[cid] = (comp_name, ref)
                order.append(cid)
            counts[cid] += len(b.get("tasks", []))
        targets: list[tuple[str, str | None, str, str, str, int]] = [
            (cid, "sys", "component", meta[cid][0], meta[cid][1], counts[cid])
            for cid in order
        ]
        return self._apply_sync(targets, structural=False)

    def _apply_sync(
        self,
        targets: list[tuple[str, str | None, str, str, str, int]],
        structural: bool,
    ) -> SyncResult:
        result = SyncResult()
        seen: set[str] = {"sys"}
        for nid, parent_id, level, name, ref, total in targets:
            seen.add(nid)
            if nid in self.nodes:  # ref 命中
                node = self.nodes[nid]
                changed = False
                if not structural and total != node.total_tasks:
                    node.total_tasks = total  # 保留 done_tasks
                    # T40 D1: plan_refine 后旧 verifier 结果已失效, 重置为 pending
                    if node.level == "component" and node.verifier_status != "pending":
                        node.verifier_status = "pending"
                        node.verifier_missing = 0
                        node.verifier_diverged = 0
                    changed = True
                if node.name != name:
                    node.name = name
                    changed = True
                if changed:
                    node.version += 1
                    node.updated_at = _now()
                    result.modified.append(nid)
                else:
                    result.unchanged.append(nid)
            elif parent_id is not None and (parent_id in self.nodes or parent_id in seen):
                self._put(ProgressNode(
                    id=nid, name=name, level=level, parent_id=parent_id,
                    sort_order=len(self.nodes), design_section_ref=ref,
                    design_status="stable", total_tasks=total,
                    created_at=_now(), updated_at=_now(),
                ))
                result.added.append(nid)
            else:  # 层次悬空 → [NEED MANUAL], 不添加, 不阻塞
                result.conflicts.append(
                    f"[NEED MANUAL] {nid} (parent {parent_id!r} 不在树中)"
                )
        # removed: 现有 plate/component 本轮不再出现
        for nid, node in self.nodes.items():
            if (node.level in ("plate", "component", "module")
                    and node.design_status != "removed" and nid not in seen):
                node.design_status = "removed"
                node.updated_at = _now()
                result.removed.append(nid)
        # 向上聚合
        for nid in [*result.added, *result.modified, *result.removed]:
            self.recalculate_parents(nid)
        return result

    def upsert_node(self, node_id: str, **kwargs) -> ProgressNode:
        node = self.nodes[node_id]
        for k, v in kwargs.items():
            setattr(node, k, v)
        node.updated_at = _now()
        return node

    def mark_removed(self, node_id: str) -> None:
        self.nodes[node_id].design_status = "removed"

    def recalculate_parents(self, node_id: str) -> None:
        """子节点变化后向上递归重算聚合 (B9.5)."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        children = self.children(node_id)
        if children:
            node.total_tasks = sum(c.total_tasks for c in children)
            node.done_tasks = sum(c.done_tasks for c in children)

            statuses = {c.verifier_status for c in children}
            if "failed" in statuses:
                node.verifier_status = "failed"
            elif statuses <= {"pass", "skipped"}:
                node.verifier_status = "pass"

            node.deep_audit_p0 = sum(c.deep_audit_p0 for c in children)
            node.deep_audit_p1 = sum(c.deep_audit_p1 for c in children)
            node.deep_audit_p2 = sum(c.deep_audit_p2 for c in children)

            covered = [c for c in children if c.test_coverage_pct is not None]
            if covered:
                total = sum(c.total_tasks for c in covered)
                if total > 0:
                    node.test_coverage_pct = sum(
                        (c.test_coverage_pct or 0.0) * c.total_tasks for c in covered
                    ) / total
        if node.parent_id and node.parent_id in self.nodes:
            self.recalculate_parents(node.parent_id)

    # ---------- 查询 ----------

    def children(self, node_id: str) -> list[ProgressNode]:
        kids = [n for n in self.nodes.values() if n.parent_id == node_id]
        return sorted(kids, key=lambda n: n.sort_order)

    def completion_pct(self, node_id: str = "sys") -> float:
        return self.nodes[node_id].completion_pct if node_id in self.nodes else 0.0

    def find_by_design_section(self, section_ref: str) -> ProgressNode | None:
        target = _normalize_ref(section_ref)
        for node in self.nodes.values():
            if node.design_section_ref == target:
                return node
        return None

    # ---------- 展示 (B9.7) ----------

    def display(self, max_depth: int = 3, plate_filter: str | None = None,
                active_only: bool = True) -> str:
        lines: list[str] = []
        sys_node = self.nodes.get("sys")
        if sys_node:
            lines.append(
                f"SYSTEM  {sys_node.completion_pct:.0f}%  "
                f"({sys_node.done_tasks}/{sys_node.total_tasks} tasks)"
            )
        for plate in self.children("sys"):
            if plate_filter and plate.name != plate_filter:
                continue
            collapsed = (
                active_only
                and plate.completion_pct == 100.0
                and plate.verifier_status == "pass"
            )
            if collapsed:
                lines.append(
                    f"Plate {plate.name} — 100% ✓ "
                    f"({len(self.children(plate.id))} components)  [collapsed]"
                )
                continue
            lines.append(f"── Plate {plate.name} — {plate.completion_pct:.0f}% ──")
            for comp in self.children(plate.id):
                lines.append(
                    f"  {comp.name}  {comp.completion_pct:.0f}%  "
                    f"v:{comp.verifier_status}"
                )
        return "\n".join(lines)

    def summary(self) -> dict:
        sys_node = self.nodes.get("sys")
        return {
            "completion_pct": sys_node.completion_pct if sys_node else 0.0,
            "total_tasks": sys_node.total_tasks if sys_node else 0,
            "done_tasks": sys_node.done_tasks if sys_node else 0,
            "node_count": len(self.nodes),
        }

    # ---------- 序列化 ----------

    def to_dict(self) -> dict:
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "design_doc_path": self.design_doc_path,
            "design_doc_version": self.design_doc_version,
            "updated_at": self.updated_at,
            "last_displayed_tick": self.last_displayed_tick,
            "nodes": {nid: vars(node) for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProgressTree:
        tree = cls(
            system_id=d["system_id"],
            system_name=d["system_name"],
            design_doc_path=d.get("design_doc_path"),
            design_doc_version=d.get("design_doc_version", 1),
            updated_at=d.get("updated_at", ""),
            last_displayed_tick=d.get("last_displayed_tick", 0),
        )
        for nid, nd in d.get("nodes", {}).items():
            tree.nodes[nid] = ProgressNode(**nd)
        return tree
