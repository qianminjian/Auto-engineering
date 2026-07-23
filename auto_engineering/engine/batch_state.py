"""BatchState — plate → component → batch 三级进度游标 (B1.1a, DS-4 权威定义).

机器视角的路由状态 (与 ProgressTree 人视角互补, 见 B9). 写入者: 仅 Orchestrator.

两种模式统一为同一视图:
  - design-doc 模式: plates = DesignDoc.plates (真实板块层次)
  - batch_plan 模式 (模糊需求): 合成单一 plate 包裹 distinct components (恒 total_plates=1)

访问方法确定性无副作用 (越界加断言兜底, 仅在对应 is_*_complete() 为 False 时调用);
推进方法有副作用 (仅 Orchestrator 调用).

序列化不存 plates (重嵌套树), 只存游标 + batch_plan (轻量 seed) —— plates 每次
从 seed 重建, 避免持久化 Plate/Component/DesignItem 深层树:
  design-doc 模式: plates 由 design_doc_path (#34) 每 tick 重 parse (确定性无漂移);
  batch_plan 模式: plates 由内嵌 batch_plan 重新合成.
batch_plan 内嵌 (不依赖 EngineState.batch_plan #6): #6 被 clear_stage_fields 在
architect→developer 过渡时清空, 跨 tick 不可依赖 → batch_state_json 必须自包含 (T9a).

参考: v5.6-Design-Loop.md §B1.1a.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate

if TYPE_CHECKING:
    from auto_engineering.engine.models import Plan, Task

_logger = logging.getLogger("ae.engine.batch_state")


@dataclass
class BatchState:
    plates: list[Plate]
    batch_plan: list[dict]
    total_batches: int = 0
    current_plate_idx: int = 0
    current_component_idx: int = 0
    current_batch_idx: int = 0

    # 已警告过的零 batch 组件集合 — 类级别 (防重复警告, T39 B9/D2)
    _warned_zero_batch: ClassVar[set[str]] = set()
    _warned_lock: ClassVar[threading.Lock] = threading.Lock()  # P1-16: 并行 tick 保护

    # ------------------------------------------------------------------
    # 构造 (双模式, 均在 _after_architect batch_plan 就绪后调用)
    # ------------------------------------------------------------------

    @staticmethod
    def flatten_batch_plan(batch_plan: list[dict]) -> list[dict]:
        """将 architect 嵌套格式扁平化为 BatchState 游标格式.

        Architect 输入 (plate→component→batches 三层):
          [{"plate": "p1", "component": "c1", "batches": [
              {"batch_id": "b1", ...}, {"batch_id": "b2", ...}]}]
        BatchState 游标格式 (flat, 每个 item 一个 batch):
          [{"component": "c1", "batch_id": "b1", ...},
           {"component": "c1", "batch_id": "b2", ...}]
        已是 flat 格式则原样返回.
        """
        if not batch_plan:
            return []
        if "batches" in batch_plan[0]:
            flat: list[dict] = []
            for plate_entry in batch_plan:
                component_name = plate_entry["component"]
                design_section = plate_entry.get("design_section", "")
                for batch in plate_entry["batches"]:
                    batch["component"] = component_name
                    if design_section:
                        batch.setdefault("design_section", design_section)
                    flat.append(batch)
            return flat
        return batch_plan

    @classmethod
    def from_design_doc(cls, doc: DesignDoc, batch_plan: list[dict]) -> BatchState:
        """design-doc 模式 — 用真实板块层次, 带一致性校验."""
        batch_plan = cls.flatten_batch_plan(batch_plan)
        plate_component_names = {
            c.name for plate in doc.plates for c in plate.components
        }
        # Build design_section → name lookup (LLM uses section IDs like "§6.1")
        section_to_name: dict[str, str] = {}
        for plate in doc.plates:
            for comp in plate.components:
                if comp.design_section:
                    section_to_name[comp.design_section] = comp.name

        # Step 1: Resolve design_section references first (preferred by architect)
        for b in batch_plan:
            ds = b.get("design_section")
            if ds and ds in section_to_name and b["component"] not in plate_component_names:
                b["component"] = section_to_name[ds]

        batch_components = list(dict.fromkeys(b["component"] for b in batch_plan))

        # Step 2: 孤儿 batch — 归一化模糊匹配兜底
        def _normalize(name: str) -> str:
            n = name.replace("`", "").strip()
            n = re.sub(r'\([^)]*\.(ts|tsx|py|js|css)[^)]*\)', '', n).strip()
            n = re.sub(r' — .*$', '', n).strip()
            return n
        norm_map: dict[str, str] = {_normalize(n): n for n in plate_component_names}
        valid = sorted(plate_component_names)
        unresolved: list[str] = []
        for b in batch_plan:
            comp = b["component"]
            if comp in plate_component_names:
                continue
            norm_comp = _normalize(comp)
            if norm_comp in norm_map:
                b["component"] = norm_map[norm_comp]
                continue
            subs = [v for v in valid if norm_comp.lower() in _normalize(v).lower()]
            if len(subs) == 1:
                b["component"] = subs[0]
                continue
            unresolved.append(comp)
        if unresolved:
            hints = []
            for orphan in unresolved:
                close = difflib.get_close_matches(_normalize(orphan), list(norm_map.keys()), n=3, cutoff=0.3)
                if close: hints.append(f"'{orphan}' → 最接近: {[norm_map[c] for c in close]}")
                else: hints.append(f"'{orphan}' → 无相似匹配")
            raise ValueError(
                f"孤儿 batch: component {unresolved} 不在任何 plate 中。"
                f"有效 component 名: {valid}。"
                f"{' | '.join(hints)} —— "
                f"architect 须重出 batch_plan (G2 retry)"
            )

        # Recompute after auto-correction (component names may have changed)
        batch_components = list(dict.fromkeys(b["component"] for b in batch_plan))

        # 零 batch 组件: design_doc 有但无对应 batch
        # 降级为 INFO — 信息性章节 (数据流/设计决策/已知问题) 无需实现, 属正常情况.
        # T39 B9/D2: 每个组件只记录一次.
        zero_batch = [c for c in plate_component_names if c not in batch_components]
        with cls._warned_lock:
            new_zero = [c for c in zero_batch if c not in cls._warned_zero_batch]
            if new_zero:
                cls._warned_zero_batch.update(new_zero)
        if new_zero:
            _logger.info(
                "设计文档组件无对应 batch (信息性章节，属正常): %s",
                sorted(new_zero),
            )

        # 过滤: 仅保留有 batch 的 component, 移除无 component 的 plate
        batch_component_set = set(batch_components)
        filtered_plates = []
        for plate in doc.plates:
            active = [c for c in plate.components if c.name in batch_component_set]
            if active:
                filtered_plates.append(Plate(
                    name=plate.name, design_section=plate.design_section,
                    components=active, cross_component_contracts_raw=plate.cross_component_contracts_raw,
                ))
        return cls(plates=filtered_plates, batch_plan=batch_plan, total_batches=len(batch_plan))

    @classmethod
    def from_batch_plan(cls, batch_plan: list[dict]) -> BatchState:
        """batch_plan 模式 — 按出现顺序提取 distinct component → 单一合成 plate."""
        batch_plan = cls.flatten_batch_plan(batch_plan)
        names = list(dict.fromkeys(b["component"] for b in batch_plan))
        comps = [
            Component(name=n, design_section="", design_items=[], source_marker="batch_plan")
            for n in names
        ]
        plate = Plate(
            name="(single)", design_section="", components=comps,
            cross_component_contracts_raw=[],
        )
        return cls(plates=[plate], batch_plan=batch_plan, total_batches=len(batch_plan))

    # ------------------------------------------------------------------
    # 访问方法 (确定性, 无副作用; 越界断言兜底)
    # ------------------------------------------------------------------

    def current_plate(self) -> Plate:
        assert not self.is_all_complete(), (
            f"current_plate() 越界: plate_idx={self.current_plate_idx} "
            f">= len(plates)={len(self.plates)}"
        )
        return self.plates[self.current_plate_idx]

    def current_component(self) -> Component:
        assert not self.is_plate_complete(), (
            f"current_component() 越界: component_idx={self.current_component_idx}"
        )
        return self.current_plate().components[self.current_component_idx]

    def batches_for(self, comp: Component) -> list[dict]:
        return [b for b in self.batch_plan if b["component"] == comp.name]

    def current_batch(self) -> dict:
        assert not self.is_component_complete(), (
            f"current_batch() 越界: batch_idx={self.current_batch_idx}"
        )
        return self.batches_for(self.current_component())[self.current_batch_idx]

    def current_component_name(self) -> str:
        return self.current_component().name

    def current_batch_id(self) -> str:
        return self.current_batch()["batch_id"]

    def current_design_section(self) -> str:
        return self.current_component().design_section

    def current_batch_tasks(self, plan: Plan) -> list[Task]:
        """plan 中属于 current_batch_id() 的 developer Task (按 task id 匹配)."""
        batch = self.current_batch()
        task_ids = {t["id"] for t in batch.get("tasks", [])}
        return [t for t in plan.get_tasks_by_stage("developer") if t.id in task_ids]

    # ------------------------------------------------------------------
    # 推进方法 (有副作用, 仅 Orchestrator 调用)
    # ------------------------------------------------------------------

    def advance_batch(self) -> None:
        self.current_batch_idx += 1

    def advance_component(self) -> None:
        self.current_component_idx += 1
        self.current_batch_idx = 0

    def advance_plate(self) -> None:
        self.current_plate_idx += 1
        self.current_component_idx = 0
        self.current_batch_idx = 0

    # ------------------------------------------------------------------
    # 完成判定 (total functions — 出界仍安全, 供路由决策)
    # ------------------------------------------------------------------

    def is_all_complete(self) -> bool:
        return self.current_plate_idx >= len(self.plates)

    def is_plate_complete(self) -> bool:
        if self.is_all_complete():
            return True
        plate = self.plates[self.current_plate_idx]
        return self.current_component_idx >= len(plate.components)

    def is_component_complete(self) -> bool:
        if self.is_plate_complete():
            return True
        comp = self.plates[self.current_plate_idx].components[self.current_component_idx]
        return self.current_batch_idx >= len(self.batches_for(comp))

    def has_more_batches_for(self, comp: Component) -> bool:
        return self.current_batch_idx < len(self.batches_for(comp))

    def has_more_components_in_plate(self) -> bool:
        if self.is_all_complete():
            return False
        plate = self.plates[self.current_plate_idx]
        return self.current_component_idx < len(plate.components)

    def has_more_plates(self) -> bool:
        return self.current_plate_idx < len(self.plates)

    # ------------------------------------------------------------------
    # 序列化 (只存游标; plates 每 tick 重建)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps({
            "current_plate_idx": self.current_plate_idx,
            "current_component_idx": self.current_component_idx,
            "current_batch_idx": self.current_batch_idx,
            "total_batches": self.total_batches,
            "batch_plan": self.batch_plan,  # 轻量 seed; plates 仍不存 (从此重建)
        })

    # ------------------------------------------------------------------
    # T94: Pre-planned Gate (DecisionGate form 1)
    # ------------------------------------------------------------------

    def _get_pending_gate(self) -> dict | None:
        """Return the next pending gate declaration for the current batch, or None."""
        batch = self.current_batch() if not self.is_component_complete() else None
        if batch:
            return batch.get("gate")
        return None

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 序列化 (只存游标; plates 每 tick 重建)
    # ------------------------------------------------------------------

    @classmethod
    def from_json(
        cls, s: str, design_doc: DesignDoc | None,
        batch_plan: list[dict] | None = None,
    ) -> BatchState:
        """重建 plates (design_doc 有→真实; 无→合成) 再恢复游标.

        batch_plan 优先用 json 内嵌 (自包含, T9a); 无内嵌时回退传入参数
        (兼容旧调用). #6 (EngineState.batch_plan) 跨 tick 被清空, 不能依赖.
        """
        data = json.loads(s)
        bp = data.get("batch_plan") or batch_plan or []
        bs = cls.from_design_doc(design_doc, bp) if design_doc is not None else cls.from_batch_plan(bp)
        bs.current_plate_idx = data["current_plate_idx"]
        bs.current_component_idx = data["current_component_idx"]
        bs.current_batch_idx = data["current_batch_idx"]
        bs.total_batches = data["total_batches"]
        return bs
