"""ProgressTree 的节点身份与设计文档辅助函数。

这些函数只负责稳定身份、时间戳和扁平板块的隐式组件投影；它们不读取或
修改 ProgressTree 状态，避免看板模型和身份归一化逻辑互相纠缠。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from auto_engineering.engine.design_doc import Component, Plate


def now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_ref(ref: str) -> str:
    """提取稳定章节编号并统一 § 前缀；标题文本变化不改变节点身份。"""
    s = ref.strip().lstrip("#").strip().replace("`", "")
    if not s:
        return ""
    s = s.lstrip("§").strip()
    section_match = re.match(
        r"(?P<section>(?:[A-Za-z]+\d+|\d+)(?:\.\d+)*(?:[A-Za-z])?)"
        r"(?=$|[\s:：—–-])",
        s,
    )
    if section_match is not None:
        s = section_match.group("section")
    return f"§{s}"


def slug(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip())


def plate_id(plate: Plate) -> str | None:
    ref = normalize_ref(plate.design_section)
    if ref:
        return ref
    if plate.name.strip():
        return f"plate/{slug(plate.name)}"
    return None  # 不可识别 → 悬空


def component_id(comp: Component) -> str:
    if comp.source_marker == "implicit_plate":
        return f"comp/{slug(comp.name)}"
    ref = normalize_ref(comp.design_section)
    if ref:
        return ref
    return f"comp/{slug(comp.name)}"


def components_for_plate(plate: Plate) -> list[Component]:
    """为纯 H2 板块提供与 BatchState 一致的隐式执行单元。"""
    if plate.components:
        return plate.components
    return [Component(
        name=plate.name,
        design_section=plate.design_section,
        design_items=[],
        source_marker="implicit_plate",
    )]


__all__ = [
    "component_id",
    "components_for_plate",
    "normalize_ref",
    "now",
    "plate_id",
    "slug",
]
