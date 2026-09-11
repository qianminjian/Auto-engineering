"""全局验证证据的 Action scope 校验。"""

from __future__ import annotations

from collections.abc import Mapping

from auto_engineering.loop.actions import ErrorResponse
from auto_engineering.loop.scope_validators import (
    ScopeValidationTarget,
    _scope_location,
    _scope_path,
)


def validate_global_evidence_scope(
    target: ScopeValidationTarget, result: dict,
) -> ErrorResponse | None:
    """绑定全局 Verifier/Audit 的显式文件证据到 Action scope。"""

    stage_modes = {
        "plate_deep_audit": "plate_audit",
        "system_verifier": "system_verifier",
        "system_deep_audit": "system_deep_audit",
    }
    mode = stage_modes.get(target._state.current_stage)
    if mode is None:
        return None
    action = target._active_action or {}
    extensions = action.get("extensions")
    scope = extensions.get("execution_scope") if isinstance(extensions, Mapping) else None
    if not isinstance(scope, Mapping) or scope.get("mode") != mode:
        return None
    raw_files = scope.get("file_targets")
    if not isinstance(raw_files, list):
        return ErrorResponse(
            "GLOBAL_EVIDENCE_SCOPE_UNAVAILABLE",
            "当前全局验证 Action 缺少可验证的 file scope",
            target._state.to_dict(),
        )
    allowed_files = {
        normalized for value in raw_files
        if (normalized := _scope_path(value)) is not None
    }
    if len(allowed_files) != len(raw_files):
        return ErrorResponse(
            "GLOBAL_EVIDENCE_SCOPE_UNAVAILABLE",
            "当前全局验证 Action 的 file scope 含非法路径",
            target._state.to_dict(),
        )

    if mode == "system_verifier":
        evidence = result.get("full_coverage_map")
        if not isinstance(evidence, list):
            return ErrorResponse(
                "GLOBAL_EVIDENCE_SCOPE_INCOMPLETE",
                "System Verifier 必须提交 full_coverage_map",
                target._state.to_dict(),
            )
        seen_items: set[str] = set()
        incomplete: list[str] = []
        for index, item in enumerate(evidence):
            if not isinstance(item, Mapping):
                incomplete.append(f"index-{index}")
                continue
            design_item = item.get("design_item")
            status = item.get("status")
            implementation = item.get("implementation")
            note = item.get("note")
            if not isinstance(design_item, str) or not design_item.strip():
                incomplete.append(f"index-{index}:design_item")
            elif design_item in seen_items:
                incomplete.append(f"{design_item}:duplicate")
            else:
                seen_items.add(design_item)
            if status not in {"IMPLEMENTED", "MISSING", "DIVERGED"}:
                incomplete.append(f"index-{index}:status")
            if not isinstance(note, str) or not note.strip():
                incomplete.append(f"{design_item or index}:note")
            if status in {"IMPLEMENTED", "DIVERGED"} and (
                _scope_location(implementation) is None
            ):
                incomplete.append(f"{design_item or index}:implementation")
        component_items = {
            str(item.get("design_item"))
            for item in (target._state.coverage_map or [])
            if isinstance(item, Mapping)
            and isinstance(item.get("design_item"), str)
            and item.get("design_item")
        }
        if component_items and seen_items != component_items:
            missing = sorted(component_items - seen_items)
            unexpected = sorted(seen_items - component_items)
            incomplete.append(
                "cross_stage="
                f"missing:{missing};unexpected:{unexpected}"
            )
        if incomplete:
            return ErrorResponse(
                "GLOBAL_EVIDENCE_SCOPE_INCOMPLETE",
                "System Verifier 的 full_coverage_map 缺少稳定条目或实现证据："
                + ",".join(incomplete),
                target._state.to_dict(),
            )
        field = "implementation"
    else:
        evidence = result.get("findings")
        field = "file"
    if not isinstance(evidence, list):
        return None
    out_of_scope: list[str] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        raw_file = item.get(field)
        if raw_file in (None, ""):
            continue
        normalized = (
            _scope_location(raw_file)
            if mode == "system_verifier"
            else _scope_path(raw_file)
        )
        if normalized is None or normalized not in allowed_files:
            out_of_scope.append(str(raw_file))
    if out_of_scope:
        return ErrorResponse(
            "GLOBAL_EVIDENCE_SCOPE_VIOLATION",
            f"{target._state.current_stage} evidence 引用了当前 scope 外文件："
            + ",".join(sorted(set(out_of_scope))),
            target._state.to_dict(),
        )
    return None


__all__ = ["validate_global_evidence_scope"]
