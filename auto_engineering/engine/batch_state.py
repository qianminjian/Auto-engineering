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

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate

if TYPE_CHECKING:
    from auto_engineering.loop.plan import Plan, Task

_logger = logging.getLogger("ae.engine.batch_state")


@dataclass
class BatchState:
    plates: list[Plate]
    batch_plan: list[dict]
    total_batches: int = 0
    current_plate_idx: int = 0
    current_component_idx: int = 0
    current_batch_idx: int = 0

    # ------------------------------------------------------------------
    # 构造 (双模式, 均在 _after_architect batch_plan 就绪后调用)
    # ------------------------------------------------------------------

    @classmethod
    def from_design_doc(cls, doc: DesignDoc, batch_plan: list[dict]) -> BatchState:
        """design-doc 模式 — 用真实板块层次, 带一致性校验."""
        plate_component_names = {
            c.name for plate in doc.plates for c in plate.components
        }
        batch_components = list(dict.fromkeys(b["component"] for b in batch_plan))

        # 孤儿 batch: component 不在任何 plate → 抛错 (G2 retry, 否则静默漏实现)
        orphans = [c for c in batch_components if c not in plate_component_names]
        if orphans:
            raise ValueError(
                f"孤儿 batch: component {orphans} 不在任何 plate 中 —— "
                f"architect 须重出 batch_plan (G2 retry)"
            )

        # 零 batch 组件: design_doc 有但无对应 batch → WARN (交 architect 确认)
        zero_batch = [c for c in plate_component_names if c not in batch_components]
        if zero_batch:
            _logger.warning(
                "零 batch 组件 %s: design_doc 声明但 batch_plan 无对应 batch —— "
                "确认是'有意不实现'还是'漏排 batch'",
                sorted(zero_batch),
            )

        return cls(plates=doc.plates, batch_plan=batch_plan, total_batches=len(batch_plan))

    @classmethod
    def from_batch_plan(cls, batch_plan: list[dict]) -> BatchState:
        """batch_plan 模式 — 按出现顺序提取 distinct component → 单一合成 plate."""
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
