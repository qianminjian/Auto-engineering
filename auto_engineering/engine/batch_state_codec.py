"""BatchState 的持久化编解码边界。

BatchState 本身只负责路由游标和批次推进；本模块负责把最小路由拓扑、
游标和完成事实编码为跨 Tick 可恢复的 JSON。完整设计内容仍不进入快照。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate

if TYPE_CHECKING:
    from auto_engineering.engine.batch_state import BatchState


def serialize_batch_state(state: BatchState) -> str:
    return json.dumps({
        "current_plate_idx": state.current_plate_idx,
        "current_component_idx": state.current_component_idx,
        "current_batch_idx": state.current_batch_idx,
        "total_batches": state.total_batches,
        "batch_plan": state.batch_plan,
        # Reducer 重放不能依赖进程内 DesignDoc。仅持久化路由所需的
        # plate/component 身份与章节，不复制 design items 或正文。
        "routing_plates": [
            {
                "name": plate.name,
                "design_section": plate.design_section,
                "components": [
                    {
                        "name": component.name,
                        "design_section": component.design_section,
                    }
                    for component in plate.components
                ],
            }
            for plate in state.plates
        ],
        "completed_batch_ids": sorted(state.completed_batch_ids()),
        "active_batch_id": (
            None if state.is_all_complete() or state.is_component_complete()
            else state.current_batch_id()
        ),
    })


def restore_batch_state(
    cls: type[BatchState],
    serialized: str,
    design_doc: DesignDoc | None,
    batch_plan: list[dict] | None = None,
) -> BatchState:
    """重建 plates (design_doc 有→真实; 无→合成) 再恢复游标。"""
    data = json.loads(serialized)
    bp = data.get("batch_plan") or batch_plan or []
    routing_plates = data.get("routing_plates")
    if design_doc is not None:
        state = cls.from_design_doc(design_doc, bp)
    elif isinstance(routing_plates, list) and routing_plates:
        plates: list[Plate] = []
        for raw_plate in routing_plates:
            if not isinstance(raw_plate, dict):
                raise ValueError("BATCH_ROUTING_TOPOLOGY_INVALID")
            raw_components = raw_plate.get("components")
            if not isinstance(raw_components, list) or not raw_components:
                raise ValueError("BATCH_ROUTING_TOPOLOGY_INVALID")
            components: list[Component] = []
            for raw_component in raw_components:
                if not isinstance(raw_component, dict):
                    raise ValueError("BATCH_ROUTING_TOPOLOGY_INVALID")
                name = raw_component.get("name")
                section = raw_component.get("design_section", "")
                if not isinstance(name, str) or not name or not isinstance(section, str):
                    raise ValueError("BATCH_ROUTING_TOPOLOGY_INVALID")
                components.append(Component(
                    name=name,
                    design_section=section,
                    design_items=[],
                    source_marker="batch_state",
                ))
            plate_name = raw_plate.get("name")
            plate_section = raw_plate.get("design_section", "")
            if (
                not isinstance(plate_name, str)
                or not plate_name
                or not isinstance(plate_section, str)
            ):
                raise ValueError("BATCH_ROUTING_TOPOLOGY_INVALID")
            plates.append(Plate(
                name=plate_name,
                design_section=plate_section,
                components=components,
                cross_component_contracts_raw=[],
            ))
        state = cls(
            plates=plates,
            batch_plan=cls._normalize_routing(cls.flatten_batch_plan(bp)),
            total_batches=len(bp),
        )
    else:
        state = cls.from_batch_plan(bp)
    state.current_plate_idx = data["current_plate_idx"]
    state.current_component_idx = data["current_component_idx"]
    state.current_batch_idx = data["current_batch_idx"]
    state.total_batches = data["total_batches"]
    completed = data.get("completed_batch_ids")
    if isinstance(completed, list) and all(
        isinstance(item, str) for item in completed
    ):
        state._completed_batch_ids = set(completed)
    if "active_batch_id" in data:
        active_batch_id = data.get("active_batch_id")
        # None 只表示当前 component 的开发 batch 已完成，后续仍需
        # component/plate verifier 按原游标运行；不得提前跳到 all-complete。
        if isinstance(active_batch_id, str):
            found = False
            for plate_idx, plate in enumerate(state.plates):
                for component_idx, component in enumerate(plate.components):
                    for batch_idx, batch in enumerate(state.batches_for(component)):
                        if str(batch.get("batch_id")) == active_batch_id:
                            state.current_plate_idx = plate_idx
                            state.current_component_idx = component_idx
                            state.current_batch_idx = batch_idx
                            found = True
                            break
                    if found:
                        break
                if found:
                    break
            if not found:
                raise ValueError(f"PLAN_ACTIVE_BATCH_MISSING: {active_batch_id}")
    return state


__all__ = ["restore_batch_state", "serialize_batch_state"]
