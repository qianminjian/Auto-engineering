"""T5 foundational — loop/actions.py (Action/ErrorResponse + RESULT_SCHEMA + validate).

设计参考: v5.6-Design-Loop.md §C.3.1 (action JSON) + §C.3.3 (error 响应) + §C.3.4 (RESULT_SCHEMA).

TickOrchestrator 的 I/O 层: 每 tick Python 输出一个 action dict (stdout),
Agent 执行后写 stage-result.json, Python 读回验证. 本模块提供:
  - ActionDone / ActionError: Python → Agent 的终态/错误 action
  - ErrorResponse: _read_and_validate 校验失败的返回 (带 current_state, 供 isinstance 分流)
  - RESULT_SCHEMA + validate_result_format: 各 stage result 必填字段/值域校验

测试原则 (per pytest-memory-management.md): 单文件 pytest --timeout=60.
"""

from __future__ import annotations

import pytest

from auto_engineering.loop.actions import (
    RESULT_SCHEMA,
    ActionDone,
    ActionError,
    ErrorResponse,
    validate_result_format,
)
from auto_engineering.loop.protocol import (
    ProtocolErrorCode,
    ProtocolValidationError,
    validate_result_envelope,
)


class TestActionDone:
    def test_minimal_done(self) -> None:
        d = ActionDone(verdict="HARD_LIMIT", reason="MAJOR 超限").to_dict()
        assert d["action"] == "done"
        assert d["verdict"] == "HARD_LIMIT"
        assert d["verdict_reason"] == "MAJOR 超限"
        assert "stage" not in d  # stage key omitted when None (P2-27 audit fix)

    def test_verdict_level_included(self) -> None:
        d = ActionDone(verdict="GOAL_ACHIEVED", reason="all covered", verdict_level=1).to_dict()
        assert d["verdict_level"] == 1

    def test_optional_fields_emitted_when_set(self) -> None:
        d = ActionDone(
            verdict="GOAL_ACHIEVED", reason="ok", verdict_level=1,
            tick=9, thread_id="uuid-v4", rounds=2,
            gate_summary={"safety": "pass"}, checkpoint_id="cp-1",
        ).to_dict()
        assert d["tick"] == 9
        assert d["thread_id"] == "uuid-v4"
        assert d["rounds"] == 2
        assert d["gate_summary"] == {"safety": "pass"}
        assert d["checkpoint_id"] == "cp-1"

    def test_optional_fields_omitted_when_none(self) -> None:
        d = ActionDone(verdict="STAGNANT").to_dict()
        # 未提供的可选字段不出现 (保持 JSON 精简)
        assert "checkpoint_id" not in d
        assert "rounds" not in d


class TestActionError:
    def test_to_dict(self) -> None:
        d = ActionError(error_code="UNKNOWN_STAGE", message="Unknown stage: foo").to_dict()
        assert d == {
            "action": "error",
            "error_code": "UNKNOWN_STAGE",
            "message": "Unknown stage: foo",
        }


class TestErrorResponse:
    def test_to_dict_with_current_state(self) -> None:
        cs = {"stage": "critic", "round": 1, "tick": 3,
              "thread_id": "uuid-v4", "expected_stage": "critic"}
        d = ErrorResponse(
            error_code="INVALID_STAGE",
            message="Expected 'critic' got 'component_verifier'.",
            current_state=cs,
        ).to_dict()
        assert d["action"] == "error"
        assert d["error_code"] == "INVALID_STAGE"
        assert d["current_state"] == cs

    def test_current_state_optional(self) -> None:
        d = ErrorResponse(error_code="INVALID_FORMAT", message="missing plan").to_dict()
        assert d["action"] == "error"
        assert "current_state" not in d


class TestResultSchema:
    def test_schema_covers_all_stages(self) -> None:
        for stage in (
            "architect", "developer", "critic",
            "component_verifier", "plate_deep_audit",
            "system_verifier", "system_deep_audit",
        ):
            assert stage in RESULT_SCHEMA
            assert "required" in RESULT_SCHEMA[stage]


class TestValidateResultFormat:
    @pytest.mark.parametrize(
        ("stage", "result", "field"),
        [
            (
                "architect",
                {
                    "stage": "architect",
                    "plan": ["not", "text"],
                    "batch_plan": [{"batch_id": "b1"}],
                    "file_list": "a.py",
                },
                "plan",
            ),
            (
                "developer",
                {
                    "stage": "developer",
                    "batch_id": "b1",
                    "files_changed": "a.py",
                    "test_results": {"passed": "5", "failed": False},
                },
                "files_changed",
            ),
            (
                "critic",
                {"stage": "critic", "verdict": "APPROVE", "findings": {}},
                "findings",
            ),
            (
                "system_deep_audit",
                {
                    "stage": "system_deep_audit",
                    "findings": [],
                    "p0_count": "0",
                    "p1_count": 0,
                    "p2_count": 0,
                    "total_audited_files": 1,
                },
                "p0_count",
            ),
        ],
    )
    def test_rejects_required_fields_with_wrong_json_types(
        self,
        stage: str,
        result: dict,
        field: str,
    ) -> None:
        errors = validate_result_format(result, stage)

        assert any(field in error and "类型" in error for error in errors)

    def test_valid_architect(self) -> None:
        result = {
            "stage": "architect",
            "plan": "x" * 60,
            "batch_plan": [{"batch_id": "b1"}],
            "file_list": ["a.py"],
        }
        assert validate_result_format(result, "architect") == []

    def test_architect_missing_required(self) -> None:
        errs = validate_result_format({"stage": "architect"}, "architect")
        assert any("plan" in e for e in errs)
        assert any("batch_plan" in e for e in errs)

    def test_architect_plan_too_short(self) -> None:
        result = {"stage": "architect", "plan": "short",
                  "batch_plan": [{"batch_id": "b1"}], "file_list": ["a.py"]}
        errs = validate_result_format(result, "architect")
        assert any("plan" in e for e in errs)

    def test_architect_empty_batch_plan(self) -> None:
        result = {"stage": "architect", "plan": "x" * 60,
                  "batch_plan": [], "file_list": ["a.py"]}
        errs = validate_result_format(result, "architect")
        assert any("batch_plan" in e for e in errs)

    def test_valid_developer(self) -> None:
        result = {
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["a.py"],
            "test_results": {"passed": 5, "failed": 0},
        }
        assert validate_result_format(result, "developer") == []

    def test_developer_failed_tests_rejected(self) -> None:
        result = {"stage": "developer", "batch_id": "b1",
                  "files_changed": ["a.py"],
                  "test_results": {"passed": 5, "failed": 2}}
        errs = validate_result_format(result, "developer")
        assert any("failed" in e for e in errs)

    def test_developer_no_files_changed_rejected(self) -> None:
        result = {"stage": "developer", "batch_id": "b1",
                  "files_changed": [],
                  "test_results": {"passed": 1, "failed": 0}}
        errs = validate_result_format(result, "developer")
        assert any("files_changed" in e for e in errs)

    def test_valid_critic_approve(self) -> None:
        result = {"stage": "critic", "verdict": "APPROVE", "findings": []}
        assert validate_result_format(result, "critic") == []

    def test_critic_invalid_verdict(self) -> None:
        result = {"stage": "critic", "verdict": "MAYBE", "findings": []}
        errs = validate_result_format(result, "critic")
        assert any("verdict" in e for e in errs)

    def test_valid_component_verifier(self) -> None:
        result = {
            "stage": "component_verifier", "component": "StageRouter",
            "coverage_map": [{"design_item": "x", "status": "IMPLEMENTED"}],
            "missing_count": 0, "diverged_count": 0,
        }
        assert validate_result_format(result, "component_verifier") == []

    def test_component_verifier_bad_status(self) -> None:
        result = {
            "stage": "component_verifier", "component": "X",
            "coverage_map": [{"design_item": "x", "status": "BOGUS"}],
            "missing_count": 0, "diverged_count": 0,
        }
        errs = validate_result_format(result, "component_verifier")
        assert any("status" in e for e in errs)

    def test_valid_system_deep_audit(self) -> None:
        result = {
            "stage": "system_deep_audit", "findings": [],
            "p0_count": 0, "p1_count": 1, "p2_count": 3,
            "total_audited_files": 48,
        }
        assert validate_result_format(result, "system_deep_audit") == []

    def test_unknown_stage_returns_error(self) -> None:
        errs = validate_result_format({"stage": "bogus"}, "bogus")
        assert errs != []


class TestProtocolResultValidation:
    def test_critic_output_fields_are_accepted_by_envelope_ssot(self) -> None:
        """Critic prompt/output model 合法字段必须与 Result 白名单同源。"""
        result = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "result-critic-1",
            "thread_id": "thread-1",
            "tick": 3,
            "stage": "critic",
            "causation_id": "action-critic-1",
            "correlation_id": "thread-1",
            "extensions": {},
            "verdict": "MAJOR",
            "findings": [],
            "strengths": [{"description": "边界清晰"}],
            "assessment": "Needs rework",
        }

        envelope = validate_result_envelope(result)

        assert envelope.stage == "critic"

    def test_missing_causation_has_stable_error_code(self) -> None:
        result = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "result-1",
            "thread_id": "thread-1",
            "tick": 1,
            "stage": "critic",
            "correlation_id": "thread-1",
            "extensions": {},
            "verdict": "APPROVE",
            "findings": [],
        }

        try:
            validate_result_envelope(result)
        except ProtocolValidationError as exc:
            assert exc.code is ProtocolErrorCode.INVALID_ENVELOPE
        else:
            raise AssertionError("缺少 causation_id 的 v1.1 Result 必须被拒绝")

    def test_unknown_top_level_field_has_stable_error_code(self) -> None:
        result = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "result-1",
            "thread_id": "thread-1",
            "tick": 1,
            "stage": "critic",
            "causation_id": "action-1",
            "correlation_id": "thread-1",
            "extensions": {},
            "verdict": "APPROVE",
            "findings": [],
            "unexpected": "not allowed",
        }

        try:
            validate_result_envelope(result)
        except ProtocolValidationError as exc:
            assert exc.code is ProtocolErrorCode.INVALID_ENVELOPE
        else:
            raise AssertionError("v1.1 Result 的未知顶层字段必须被拒绝")
