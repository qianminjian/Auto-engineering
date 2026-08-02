"""Architect 阶段的 Research/Supplement 有界上下文。"""

from __future__ import annotations

import json
from typing import Any


def build_architect_research_context(
    supplements_json: str | None,
    research_archive: dict[str, Any],
) -> list[dict[str, str]]:
    """生成不超过 16 条、每条内容不超过 4000 字符的可审计摘要。"""
    entries: list[dict[str, str]] = []
    if supplements_json:
        try:
            supplements = json.loads(supplements_json)
        except json.JSONDecodeError:
            supplements = {}
        if isinstance(supplements, dict):
            for gap_id, item in supplements.items():
                if isinstance(item, dict):
                    entries.append({
                        "gap_id": str(gap_id),
                        "source": str(item.get("source", "supplement")),
                        "content": str(item.get("content", ""))[:4000],
                    })
    for gap_id, item in research_archive.items():
        if isinstance(item, dict):
            entries.append({
                "gap_id": str(gap_id),
                "source": "research_archive",
                "content": str(item.get("recommended_design") or item.get("findings") or "")[:4000],
            })
    return entries[:16]
