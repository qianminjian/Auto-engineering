"""Action scope validators shared by stage result validation.

These checks are kept separate from the large semantic result validators so
that task/file ownership remains one small, auditable boundary module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ErrorResponse

__all__ = [
    "validate_component_verifier_scope",
    "validate_critic_scope",
    "validate_execution_scope",
]


class ScopeValidationTarget(Protocol):
    """Scope validation needs only this minimal orchestrator view."""

    _state: EngineState
    _active_action: dict[str, Any] | None


def _scope_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("\\", "/")
    parts = [item for item in normalized.split("/") if item not in {"", "."}]
    if not parts or normalized.startswith("/") or ".." in parts:
        return None
    return "/".join(parts)


def _scope_location(value: object) -> str | None:
    """归一化 Worker 的 ``file:line`` 实现证据。"""

    if not isinstance(value, str) or ":" not in value:
        return None
    raw_file, raw_line = value.rsplit(":", 1)
    if not raw_line.isdigit() or int(raw_line) < 1:
        return None
    return _scope_path(raw_file)


def validate_execution_scope(
    target: ScopeValidationTarget, result: dict,
) -> ErrorResponse | None:
    """把 Developer Result 绑定到 Action 声明的 task/file 白名单。"""

    if target._state.current_stage != "developer":
        return None
    action = target._active_action or {}
    expected_format = action.get("expected_format")
    if not isinstance(expected_format, Mapping) or "task_ids" not in expected_format:
        return None
    extensions = action.get("extensions")
    scope = extensions.get("execution_scope") if isinstance(extensions, Mapping) else None
    if not isinstance(scope, Mapping):
        return ErrorResponse(
            "DEVELOPER_SCOPE_UNAVAILABLE",
            "当前 Developer Action 缺少可验证的 task/file scope",
            target._state.to_dict(),
        )
    raw_expected_ids = scope.get("task_ids")
    raw_allowed_files = scope.get("file_targets")
    if (
        not isinstance(raw_expected_ids, list)
        or not all(isinstance(item, str) and item for item in raw_expected_ids)
        or not isinstance(raw_allowed_files, list)
    ):
        return ErrorResponse(
            "DEVELOPER_SCOPE_UNAVAILABLE",
            "当前 Developer Action 的 task/file scope 无法验证",
            target._state.to_dict(),
        )
    expected_ids = list(raw_expected_ids)
    actual_ids = result.get("task_ids")
    if (
        not isinstance(actual_ids, list)
        or any(not isinstance(item, str) or not item for item in actual_ids)
        or len(actual_ids) != len(set(actual_ids))
        or set(actual_ids) != set(expected_ids)
    ):
        actual = actual_ids if isinstance(actual_ids, list) else []
        missing = sorted(set(expected_ids) - set(actual))
        unexpected = sorted(set(actual) - set(expected_ids))
        return ErrorResponse(
            "DEVELOPER_SCOPE_VIOLATION",
            "Developer Result 的 task_ids 未完整且仅覆盖当前 batch："
            f"缺少={missing}; 越界={unexpected}",
            target._state.to_dict(),
        )

    allowed_files = {
        normalized for value in raw_allowed_files
        if (normalized := _scope_path(value)) is not None
    }
    changed = result.get("files_changed", [])
    changed_files = [_scope_path(value) for value in changed]
    out_of_scope = sorted({
        value for value in changed_files
        if isinstance(value, str) and value not in allowed_files
    })
    if any(value is None for value in changed_files) or out_of_scope:
        invalid_count = sum(value is None for value in changed_files)
        return ErrorResponse(
            "DEVELOPER_SCOPE_VIOLATION",
            "Developer Result 的 files_changed 超出当前 batch file_targets："
            f"越界={out_of_scope}; 非法路径数量={invalid_count}",
            target._state.to_dict(),
        )

    evidence = result.get("red_evidence", [])
    if isinstance(evidence, list):
        evidence_refs = {
            str(item.get(field))
            for item in evidence
            if isinstance(item, Mapping)
            for field in ("task_id", "task_ref")
            if isinstance(item.get(field), str) and item.get(field)
        }
        unexpected_refs = sorted(evidence_refs - set(expected_ids))
        if unexpected_refs:
            return ErrorResponse(
                "DEVELOPER_SCOPE_VIOLATION",
                "Developer red_evidence 引用了当前 batch 之外的 task："
                + ",".join(unexpected_refs),
                target._state.to_dict(),
            )
    return None


def validate_critic_scope(
    target: ScopeValidationTarget, result: dict,
) -> ErrorResponse | None:
    """Critic 的文件型发现必须落在当前批次的审查范围内。"""

    if target._state.current_stage != "critic":
        return None
    action = target._active_action or {}
    extensions = action.get("extensions")
    scope = extensions.get("execution_scope") if isinstance(extensions, Mapping) else None
    if not isinstance(scope, Mapping) or scope.get("mode") != "critic_batch":
        return None
    raw_files = scope.get("file_targets")
    if not isinstance(raw_files, list):
        return ErrorResponse(
            "CRITIC_SCOPE_UNAVAILABLE",
            "当前 Critic Action 缺少可验证的 file scope",
            target._state.to_dict(),
        )
    allowed_files = {
        normalized for value in raw_files
        if (normalized := _scope_path(value)) is not None
    }
    if len(allowed_files) != len(raw_files):
        return ErrorResponse(
            "CRITIC_SCOPE_UNAVAILABLE",
            "当前 Critic Action 的 file scope 含非法路径",
            target._state.to_dict(),
        )
    findings = result.get("findings")
    if not isinstance(findings, list):
        return None
    out_of_scope: list[str] = []
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        raw_file = finding.get("file")
        if raw_file in (None, ""):
            continue
        if finding.get("kind") in {"plan_gap", "contract_gap", "project_capability"}:
            continue
        normalized = _scope_path(raw_file)
        if normalized is None or normalized not in allowed_files:
            out_of_scope.append(str(raw_file))
    if out_of_scope:
        return ErrorResponse(
            "CRITIC_SCOPE_VIOLATION",
            "Critic findings 引用了当前 batch 之外的文件："
            + ",".join(sorted(set(out_of_scope))),
            target._state.to_dict(),
        )

    # Critic 仍以 findings 作为当前 batch 的严格审查结果；跨批次阻断
    # 问题必须显式进入独立通道，避免把合法的资源/共享模块缺陷静默丢掉，
    # 也避免通过普通 finding 绕过当前 batch 的文件边界。
    cross_batch = result.get("cross_batch_findings")
    if cross_batch is None:
        return None
    if not isinstance(cross_batch, list):
        return ErrorResponse(
            "CRITIC_SCOPE_UNAVAILABLE",
            "Critic 的 cross_batch_findings 必须为数组",
            target._state.to_dict(),
        )
    invalid_cross_batch: list[str] = []
    for finding in cross_batch:
        if not isinstance(finding, Mapping):
            invalid_cross_batch.append("<非对象 finding>")
            continue
        raw_file = finding.get("file")
        if raw_file in (None, ""):
            invalid_cross_batch.append("<缺少 file>")
            continue
        if _scope_path(raw_file) is None:
            invalid_cross_batch.append(str(raw_file))
    if invalid_cross_batch:
        return ErrorResponse(
            "CRITIC_SCOPE_VIOLATION",
            "Critic cross_batch_findings 含非法文件路径或缺少 file："
            + ",".join(sorted(set(invalid_cross_batch))),
            target._state.to_dict(),
        )
    return None


def validate_component_verifier_scope(
    target: ScopeValidationTarget, result: dict,
) -> ErrorResponse | None:
    """Verifier 只能提交当前 Action 声明的批次设计条目。"""

    if target._state.current_stage != "component_verifier":
        return None
    action = target._active_action or {}
    scope = action.get("verification_scope")
    if not isinstance(scope, dict) or scope.get("mode") != "batch_design_items":
        return None
    component = scope.get("component")
    if result.get("component") != component:
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "component_verifier 结果的 component 未绑定当前批次",
            target._state.to_dict(),
        )
    expected = scope.get("design_item_ids")
    if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "当前 Action 的 design_item_ids 非法，无法安全接收覆盖结果",
            target._state.to_dict(),
        )
    raw_allowed_files = scope.get("file_targets")
    allowed_files = {
        normalized for value in raw_allowed_files
        if (normalized := _scope_path(value)) is not None
    } if isinstance(raw_allowed_files, list) else set()
    if isinstance(raw_allowed_files, list) and len(allowed_files) != len(raw_allowed_files):
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "当前 Action 的 file_targets 含非法路径，无法安全接收覆盖结果",
            target._state.to_dict(),
        )
    coverage = result.get("coverage_map")
    if not isinstance(coverage, list):
        return None
    actual: list[str] = []
    for item in coverage:
        if not isinstance(item, dict) or not isinstance(item.get("design_item"), str):
            return ErrorResponse(
                "COMPONENT_VERIFICATION_SCOPE_INVALID",
                "coverage_map 每项必须绑定非空 design_item",
                target._state.to_dict(),
            )
        status = item.get("status")
        raw_file = item.get("file")
        if raw_file not in (None, ""):
            normalized_file = _scope_path(raw_file)
            if normalized_file is None or (
                allowed_files and normalized_file not in allowed_files
            ):
                return ErrorResponse(
                    "COMPONENT_VERIFICATION_SCOPE_INVALID",
                    "coverage_map 的 file 超出当前组件实现文件范围",
                    target._state.to_dict(),
                )
        elif status in {"IMPLEMENTED", "DIVERGED"} and allowed_files:
            return ErrorResponse(
                "COMPONENT_VERIFICATION_SCOPE_INVALID",
                "IMPLEMENTED/DIVERGED coverage 必须绑定当前实现文件",
                target._state.to_dict(),
            )
        actual.append(item["design_item"])
    if len(actual) != len(set(actual)):
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "coverage_map 不得重复提交同一 design_item",
            target._state.to_dict(),
        )
    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("缺少=" + ",".join(missing))
        if unexpected:
            detail.append("越界=" + ",".join(unexpected))
        return ErrorResponse(
            "COMPONENT_VERIFICATION_SCOPE_INVALID",
            "coverage_map 未完整且仅覆盖当前批次白名单（" + "; ".join(detail) + "）",
            target._state.to_dict(),
        )
    return None
