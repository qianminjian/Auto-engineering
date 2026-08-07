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


def select_active_contracts(
    baseline: dict[str, Any],
    reached_batch_ids: set[str],
) -> dict[str, Any]:
    """只返回实现义务已到达的契约；无义务绑定的旧契约立即激活。"""
    contracts = baseline.get("contracts", {})
    if not isinstance(contracts, dict):
        return {}
    task_batches: dict[str, str] = {}
    for batch in baseline.get("batch_plan", []):
        if not isinstance(batch, dict):
            continue
        batch_id = batch.get("batch_id")
        if not isinstance(batch_id, str):
            continue
        for task in batch.get("tasks", []):
            if isinstance(task, dict) and isinstance(task.get("id"), str):
                task_batches[task["id"]] = batch_id

    required_targets: dict[str, set[str]] = {}
    for obligation in baseline.get("obligations", []):
        if not isinstance(obligation, dict):
            continue
        targets = {
            target
            for target in obligation.get("implementation_targets", [])
            if isinstance(target, str)
        }
        for contract_ref in obligation.get("contract_refs", []):
            if isinstance(contract_ref, str):
                required_targets.setdefault(contract_ref, set()).update(targets)

    active: dict[str, Any] = {}
    for name, contract in contracts.items():
        contract_targets = required_targets.get(name)
        if not contract_targets:
            active[name] = contract
            continue
        target_batches = {
            task_batches.get(target) for target in contract_targets
        }
        if None not in target_batches and target_batches <= reached_batch_ids:
            active[name] = contract
    return active


__all__ = ["build_architecture_baseline", "select_active_contracts"]
