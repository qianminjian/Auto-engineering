"""Baseline 与 Architect 增量结果的唯一候选视图。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class ArchitectureCandidateError(ValueError):
    """Architecture candidate 无法确定性物化。"""


class ArchitectureCandidateBuilder:
    """一次性合并 baseline、PlanPatch、contracts 与 obligations。"""

    def build(
        self,
        result: Mapping[str, Any],
        *,
        active_revision: int,
        current_baseline: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if active_revision <= 0:
            return deepcopy(dict(result))

        patch = result.get("plan_patch")
        if not isinstance(patch, Mapping):
            raise ArchitectureCandidateError(
                "PLAN_REFINE 必须提交 plan_patch，禁止重发完整 batch_plan"
            )
        if result.get("batch_plan") is not None:
            raise ArchitectureCandidateError(
                "PLAN_REFINE 不得同时提交 batch_plan 与 plan_patch"
            )
        submitted_revision = patch.get("base_revision")
        if submitted_revision is not None and submitted_revision != active_revision:
            raise ArchitectureCandidateError(
                "PLAN_REVISION_CONFLICT: "
                f"base={submitted_revision}, active={active_revision}"
            )

        baseline = dict(current_baseline or {})
        existing_batches = self._object_list(
            baseline.get("batch_plan", []),
            "baseline.batch_plan",
        )
        additions = self._object_list(
            patch.get("add_batches", []),
            "plan_patch.add_batches",
        )
        existing_ids = {
            batch.get("batch_id")
            for batch in existing_batches
            if isinstance(batch.get("batch_id"), str)
        }
        duplicate_ids = sorted({
            str(batch.get("batch_id"))
            for batch in additions
            if batch.get("batch_id") in existing_ids
        })
        if duplicate_ids:
            raise ArchitectureCandidateError(
                f"PLAN_BATCH_CONFLICT: {', '.join(duplicate_ids)}"
            )

        contracts = dict(baseline.get("contracts", {}))
        raw_contracts = result.get("contracts", {})
        if not isinstance(raw_contracts, Mapping):
            raise ArchitectureCandidateError("contracts 必须为 object")
        contracts.update(dict(raw_contracts))

        obligations = self._merge_obligations(
            baseline.get("obligations", []),
            result.get("obligations", []),
            patch.get("obligation_updates", []),
        )
        candidate = deepcopy(dict(result))
        candidate.pop("plan_patch", None)
        candidate["batch_plan"] = [*existing_batches, *additions]
        candidate["contracts"] = contracts
        candidate["obligations"] = obligations
        return candidate

    def _merge_obligations(
        self,
        baseline: object,
        additions: object,
        updates: object,
    ) -> list[dict[str, Any]]:
        merged = self._object_list(baseline, "baseline.obligations")
        by_source = {
            item.get("source_ref"): item
            for item in merged
            if isinstance(item.get("source_ref"), str)
        }
        ids = {
            item.get("id")
            for item in merged
            if isinstance(item.get("id"), str)
        }
        for item in self._object_list(additions, "obligations"):
            source_ref = item.get("source_ref")
            if source_ref in by_source:
                if by_source[source_ref] == item:
                    continue
                raise ArchitectureCandidateError(
                    f"OBLIGATION_UPDATE_REQUIRED: {source_ref}"
                )
            obligation_id = item.get("id")
            if obligation_id in ids:
                raise ArchitectureCandidateError(
                    f"obligation revision conflict: {obligation_id}"
                )
            merged.append(item)
            if isinstance(source_ref, str):
                by_source[source_ref] = item
            if isinstance(obligation_id, str):
                ids.add(obligation_id)

        for update in self._object_list(
            updates,
            "plan_patch.obligation_updates",
        ):
            source_ref = update.get("source_ref")
            current = by_source.get(source_ref)
            if current is None:
                raise ArchitectureCandidateError(
                    f"OBLIGATION_SOURCE_UNKNOWN: {source_ref}"
                )
            allowed = {
                "source_ref",
                "add_implementation_targets",
                "add_verification_targets",
                "add_contract_refs",
            }
            unexpected = sorted(set(update) - allowed)
            if unexpected:
                raise ArchitectureCandidateError(
                    "obligation update 字段不受支持: " + ", ".join(unexpected)
                )
            replacement = deepcopy(current)
            for field, update_field in (
                ("implementation_targets", "add_implementation_targets"),
                ("verification_targets", "add_verification_targets"),
                ("contract_refs", "add_contract_refs"),
            ):
                values = update.get(update_field, [])
                if not isinstance(values, list) or not all(
                    isinstance(value, str) for value in values
                ):
                    raise ArchitectureCandidateError(
                        f"{update_field} 必须为 string array"
                    )
                replacement[field] = list(dict.fromkeys([
                    *replacement.get(field, []),
                    *values,
                ]))
            index = merged.index(current)
            merged[index] = replacement
            by_source[source_ref] = replacement
        return merged

    @staticmethod
    def _object_list(value: object, field: str) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not all(
            isinstance(item, Mapping) for item in value
        ):
            raise ArchitectureCandidateError(f"{field} 必须为 object array")
        return [deepcopy(dict(item)) for item in value]


__all__ = ["ArchitectureCandidateBuilder", "ArchitectureCandidateError"]
