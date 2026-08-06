"""Architect 已接受事实的有界、内容寻址投影。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def build_architecture_baseline(
    *,
    revision: int,
    design_doc_path: str,
    design_doc_digest: str,
    plan: str,
    batch_plan: list[dict[str, Any]],
    contracts: dict[str, Any],
    obligations: list[dict[str, Any]],
    accepted_at_tick: int,
) -> dict[str, Any]:
    """规范化并摘要 Architect 已接受输出；时间不参与摘要外的可变状态。"""
    if revision < 1:
        raise ValueError("ArchitectureBaseline revision 必须为正整数")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "revision": revision,
        "design_doc_ref": {
            "path": design_doc_path,
            "digest": design_doc_digest,
        },
        "plan_summary": plan[:4000],
        "batch_plan": batch_plan,
        "contracts": contracts,
        "obligations": obligations,
        "accepted_at_tick": accepted_at_tick,
    }
    digest_payload = dict(payload)
    digest_payload.pop("accepted_at_tick")
    payload["baseline_id"] = hashlib.sha256(
        _canonical_json(digest_payload).encode("utf-8")
    ).hexdigest()
    return payload


__all__ = ["build_architecture_baseline"]
