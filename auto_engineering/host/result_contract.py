"""Coordinator Result 的纯归一化、重绑与字段合同策略。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.host.worker_evidence import HostEvidenceValidationError
from auto_engineering.loop.actions import validate_result_format
from auto_engineering.loop.section_findings import (
    SectionFindingValidationError,
    normalize_section_findings,
)


class ResultContractService:
    """不读写运行态、只按 active Action 处理 Coordinator Result。"""

    _HOST_ONLY_FIELDS = frozenset({
        "native_result",
        "native_result_file",
        "native_worker_handle",
        "actual_model",
        "isolation_evidence",
        "execution_generation",
        "fencing_token",
        "generation",
        "fencing",
        "attestation",
        "worker_attestations",
        "receipt",
        "outcomes",
    })

    @staticmethod
    def _developer_execution_scope(
        action: Mapping[str, Any],
    ) -> tuple[str, list[str]] | None:
        if action.get("stage") != "developer":
            return None
        extensions = action.get("extensions")
        scope = (
            extensions.get("execution_scope")
            if isinstance(extensions, Mapping)
            else None
        )
        if scope is None:
            return None
        if not isinstance(scope, Mapping):
            raise HostEvidenceValidationError(("DEVELOPER_SCOPE_UNAVAILABLE",))
        batch_id = scope.get("batch_id")
        task_ids = scope.get("task_ids")
        if (
            not isinstance(batch_id, str)
            or not batch_id
            or not isinstance(task_ids, list)
            or not all(isinstance(item, str) and item for item in task_ids)
            or len(task_ids) != len(set(task_ids))
        ):
            raise HostEvidenceValidationError(("DEVELOPER_SCOPE_UNAVAILABLE",))
        return batch_id, list(task_ids)

    @staticmethod
    def _bind_developer_execution_scope(
        *,
        normalized: Mapping[str, Any],
        execution_scope: tuple[str, list[str]],
    ) -> dict[str, Any]:
        """把 active batch 的机器范围回填并校验到 Developer Result。"""

        bound = dict(normalized)
        scope_batch_id, scope_task_ids = execution_scope
        if "batch_id" not in bound:
            bound["batch_id"] = scope_batch_id
        elif bound["batch_id"] != scope_batch_id:
            raise HostEvidenceValidationError((
                "DEVELOPER_BATCH_ID_SCOPE_MISMATCH",
            ))
        if "task_ids" not in bound:
            bound["task_ids"] = list(scope_task_ids)
        else:
            actual_task_ids = bound["task_ids"]
            if (
                not isinstance(actual_task_ids, list)
                or any(
                    not isinstance(item, str) or not item
                    for item in actual_task_ids
                )
                or len(actual_task_ids) != len(set(actual_task_ids))
                or set(actual_task_ids) != set(scope_task_ids)
            ):
                raise HostEvidenceValidationError((
                    "DEVELOPER_TASK_IDS_SCOPE_MISMATCH",
                ))
        return bound

    @classmethod
    def _host_field_violations(
        cls,
        coordinator_payload: Mapping[str, Any],
    ) -> tuple[str, ...]:
        return tuple(
            f"COORDINATOR_HOST_FIELD_FORBIDDEN:{field}"
            for field in sorted(
                cls._HOST_ONLY_FIELDS.intersection(coordinator_payload)
            )
        )

    @staticmethod
    def normalize_echoed_identity(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """只归一化身份完全一致的已知宿主包装；身份仍由 Core 写入。"""

        normalized = dict(coordinator_payload)
        wrapper_keys = {"action", "stage", "tick", "thread_id", "status", "result"}
        wrapped_result = normalized.get("result")
        if (
            isinstance(wrapped_result, Mapping)
            and set(normalized) == wrapper_keys
            and normalized.get("action") == action.get("action")
            and normalized.get("stage") == action.get("stage")
            and normalized.get("tick") == action.get("tick")
            and normalized.get("thread_id") == action.get("thread_id")
            and normalized.get("status") in {"ok", "success", "completed"}
        ):
            return dict(wrapped_result)
        if "stage" in normalized and normalized["stage"] == action.get("stage"):
            del normalized["stage"]
        return normalized

    @staticmethod
    def normalize_business_payload(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """按 Core 下发合同恢复一次二次序列化，并在写证据前校验。"""

        normalized = dict(coordinator_payload)
        host_field_violations = ResultContractService._host_field_violations(
            normalized
        )
        if host_field_violations:
            raise HostEvidenceValidationError(host_field_violations)

        execution_scope = ResultContractService._developer_execution_scope(action)
        if execution_scope is not None:
            normalized = ResultContractService._bind_developer_execution_scope(
                normalized=normalized,
                execution_scope=execution_scope,
            )
        contract = action.get("result_contract")
        if contract is None:
            return normalized
        if not isinstance(contract, Mapping):
            raise HostEvidenceValidationError(("RESULT_CONTRACT_INVALID",))
        required = contract.get("required")
        properties = contract.get("properties")
        if (
            contract.get("schema_version") != "1.0"
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or not isinstance(properties, Mapping)
            or contract.get("additionalProperties") is not False
        ):
            raise HostEvidenceValidationError(("RESULT_CONTRACT_INVALID",))
        required = list(required)
        properties = dict(properties)
        if execution_scope is not None:
            properties.setdefault("batch_id", {"type": "string"})
            properties.setdefault("task_ids", {"type": "array"})
            for field in ("batch_id", "task_ids"):
                if field not in required:
                    required.append(field)
        elif action.get("stage") == "developer" and "task_ids" not in required:
            required.append("task_ids")
        violations: list[str] = [
            f"COORDINATOR_FIELD_UNEXPECTED:{field}"
            for field in sorted(str(item) for item in normalized)
            if field not in properties
        ]
        for field in required:
            if field not in normalized:
                violations.append(f"COORDINATOR_FIELD_REQUIRED:{field}")
        for field, value in tuple(normalized.items()):
            declaration = properties.get(field)
            if not isinstance(declaration, Mapping):
                continue
            raw_types = declaration.get("type")
            expected = (
                [raw_types]
                if isinstance(raw_types, str)
                else raw_types
                if isinstance(raw_types, list)
                else []
            )
            if (
                isinstance(value, str)
                and "string" not in expected
                and any(item in expected for item in ("array", "object"))
            ):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    decoded = value
                if decoded is not value:
                    value = decoded
                    normalized[field] = decoded
            if not ResultContractService.matches_json_type(value, expected):
                violations.append(
                    f"COORDINATOR_FIELD_TYPE_INVALID:{field}:"
                    f"{'|'.join(str(item) for item in expected)}"
                )
        if violations:
            raise HostEvidenceValidationError(violations)
        stage = action.get("stage")
        # Gate Result 使用 gate_resolution 作为唯一业务载荷；Gate 的 stage
        # 只是当前流程位置，不能再套用该 stage 的普通业务 Result 必填字段。
        if action.get("action") != "gate" and isinstance(stage, str):
            semantic_errors = validate_result_format(
                {"stage": stage, **normalized},
                stage,
            )
            if semantic_errors:
                raise HostEvidenceValidationError(tuple(
                    f"COORDINATOR_RESULT_INVALID:{error}"
                    for error in semantic_errors
                ))
        return normalized

    @staticmethod
    def matches_json_type(value: object, expected: Sequence[object]) -> bool:
        checks = {
            "string": lambda item: isinstance(item, str),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        return any(
            isinstance(kind, str)
            and kind in checks
            and checks[kind](value)
            for kind in expected
        )

    @staticmethod
    def bind_core_auto_decision(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """把线程策略生成的机器字段重新绑定到 active Action。"""

        payload = dict(coordinator_payload)
        auto_decision = action.get("auto_decision")
        if action.get("stage") != "gap_review" or not isinstance(
            auto_decision, Mapping
        ):
            return payload
        raw_decision = payload.get("decision")
        decision = dict(raw_decision) if isinstance(raw_decision, Mapping) else {}
        for key in ("gap_id", "resolution", "decision_source", "policy"):
            if key in auto_decision:
                decision[key] = auto_decision[key]
        payload["decision"] = decision
        return payload

    @staticmethod
    def bind_core_stage_fields(
        *,
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """由 active Action 绑定阶段机器事实，Agent 只提供推理语义。"""

        payload = dict(coordinator_payload)
        if action.get("stage") != "gap_scan":
            return payload
        raw_gaps = payload.get("gaps")
        if isinstance(raw_gaps, list):
            payload["gaps"] = [
                {
                    **dict(gap),
                    "impact": [gap["impact"]],
                }
                if isinstance(gap, Mapping)
                and isinstance(gap.get("impact"), str)
                and gap["impact"].strip()
                else gap
                for gap in raw_gaps
            ]
        context = action.get("context")
        context_mapping: Mapping[str, Any] = (
            context if isinstance(context, Mapping) else {}
        )
        sections = context_mapping.get("design_sections")
        findings = payload.pop("section_findings", None)
        if not isinstance(sections, list) or not sections:
            # 旧 Action 没有稳定工程模型；只读兼容其既有 payload。
            return dict(coordinator_payload)
        try:
            payload.update(normalize_section_findings(
                sections=sections,
                findings=findings,
                gaps=payload.get("gaps", []),
                design_doc_digest=str(context_mapping.get("design_doc_digest", "")),
            ))
        except SectionFindingValidationError as exc:
            raise HostEvidenceValidationError(exc.violations) from exc
        return payload

    @staticmethod
    def coordinator_payload_violations(
        action: Mapping[str, Any],
        coordinator_payload: Mapping[str, Any],
    ) -> list[str]:
        """在任何 evidence/journal 写入前拒绝跨 Action 陈旧业务字段。"""

        violations = list(
            ResultContractService._host_field_violations(coordinator_payload)
        )
        execution_scope = ResultContractService._developer_execution_scope(action)
        contract = action.get("result_contract")
        if isinstance(contract, Mapping) and isinstance(
            contract.get("properties"), Mapping
        ):
            allowed = {str(key) for key in contract["properties"]}
        else:
            expected = action.get("expected_format")
            allowed = (
                set()
                if not isinstance(expected, Mapping)
                else {str(key) for key in expected}
            )
        if action.get("stage") == "developer":
            allowed.add("task_ids")
            if execution_scope is not None:
                allowed.add("batch_id")
        if not allowed:
            return violations
        violations.extend([
            f"COORDINATOR_FIELD_UNEXPECTED:{key}"
            for key in sorted(str(key) for key in coordinator_payload)
            if key not in allowed
        ])
        return violations


__all__ = ["ResultContractService"]
