"""Architect 阶段的 Research/Supplement 有界上下文。"""

from __future__ import annotations

import hashlib
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
                    source = str(item.get("source", "supplement"))
                    approved = source in {"user", "thread_policy"}
                    entries.append({
                        "gap_id": str(gap_id),
                        "source": source,
                        "content": str(item.get("content", ""))[:4000],
                        "authority": "binding" if approved else "advisory",
                        "change_policy": (
                            "already_approved" if approved
                            else "user_gate_required"
                        ),
                    })
    for gap_id, item in research_archive.items():
        if isinstance(item, dict):
            entries.append({
                "gap_id": str(gap_id),
                "source": "research_archive",
                "content": str(item.get("recommended_design") or item.get("findings") or "")[:4000],
                "authority": "advisory",
                "change_policy": "user_gate_required",
            })
    deduplicated: dict[tuple[str, str], dict[str, str]] = {}
    for entry in entries:
        digest = hashlib.sha256(entry["content"].encode("utf-8")).hexdigest()
        key = (entry["gap_id"], digest)
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = {
                **entry,
                "sources": entry["source"],
                "content_sha256": digest,
            }
        else:
            sources = existing["sources"].split(",")
            if entry["source"] not in sources:
                existing["sources"] = ",".join((*sources, entry["source"]))
    return list(deduplicated.values())[:16]
