"""VerificationLayers — 验证层自动裁剪 (v5.6 §B6.9).

根据设计层次自动判定验证深度, 避免冗余验证 agent (不依赖用户手动配置):
  - LEAF  (5 agents): total_components==1 → 跳过 plate_deep_audit + system_verifier
  - PLATE (6 agents): total_plates==1 & components>1 → 跳过 system_verifier
  - FULL  (7 agents): total_plates>1 → 全部 5 层验证

判定优先级: design_doc (真实层次) > batch_plan (合成单板块, 恒 total_plates=1).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.engine.design_doc import DesignDoc

__all__ = ["VerificationLayers", "determine_verification_layers"]


class VerificationLayers(StrEnum):
    LEAF = "leaf"    # 单组件 — 5 Agent
    PLATE = "plate"  # 单板块多组件 — 6 Agent
    FULL = "full"    # 多板块 — 7 Agent


def determine_verification_layers(
    design_doc: DesignDoc | None,
    batch_plan: list[dict] | None,
) -> VerificationLayers:
    """从设计层次自动判定验证深度 (§B6.9).

    Args:
        design_doc: 解析后的设计文档 (design-doc 模式); None 则用 batch_plan.
        batch_plan: architect 产出的 batch 列表 (batch_plan 模式, 恒单板块).

    Returns:
        VerificationLayers: LEAF/PLATE/FULL.
    """
    if design_doc:
        total_components = sum(len(p.components) for p in design_doc.plates)
        total_plates = len(design_doc.plates)
    elif batch_plan:
        components = {b["component"] for b in batch_plan if "component" in b}
        total_components = len(components)
        total_plates = 1
    else:
        return VerificationLayers.LEAF

    if total_components <= 1:
        return VerificationLayers.LEAF
    elif total_plates == 1:
        return VerificationLayers.PLATE
    else:
        return VerificationLayers.FULL
