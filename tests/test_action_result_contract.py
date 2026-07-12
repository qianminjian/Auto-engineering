"""action/stage-result 契约测试 (v7.0 T33a — 消费者驱动契约).

固化 TickOrchestrator 与任意驱动 (AgentDriver/StandaloneDriver) 之间的两个唯一
耦合点形状:
  - action JSON   (引擎→驱动): action.schema.json ↔ _build_action / ActionDone / ActionError
  - stage-result  (驱动→引擎): stage-result.schema.json ↔ actions.RESULT_SCHEMA

核心防漂移断言: stage-result.schema.json 的 per-stage required 必须与运行时权威
actions.RESULT_SCHEMA 完全一致 —— 代码改了 required 但 schema 没同步 → 本测试红。

单文件 pytest --timeout=60, 无真实子进程/LLM (复用 tick 测试的快速 stub helper).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from jsonschema import Draft202012Validator

from auto_engineering.loop.actions import (
    RESULT_SCHEMA,
    ActionDone,
    ActionError,
    validate_result_format,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "auto_engineering" / "loop"
_ACTION_SCHEMA = json.loads((_SCHEMA_DIR / "action.schema.json").read_text(encoding="utf-8"))
_RESULT_SCHEMA_JSON = json.loads((_SCHEMA_DIR / "stage-result.schema.json").read_text(encoding="utf-8"))

_action_validator = Draft202012Validator(_ACTION_SCHEMA)
_result_validator = Draft202012Validator(_RESULT_SCHEMA_JSON)

# Phase 0 stage (结构自由, RESULT_SCHEMA 不校验), 但 _build_action 会产出
_PHASE0_STAGES = ("gap_scan", "gap_review", "research")

_VALID_PLAN = "实现组件, 包含完整的 TDD Red-Green-Refactor 循环 + Gate 验证流程, 确保文件隔离检查通过"


# ── 快速 stub helper (复用 test_tick_orchestrator 模式, 无真实 LLM/子进程) ──


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    g = MagicMock()
    g.check.return_value = MagicMock(action="pass")
    return g


def _orchestrator() -> TickOrchestrator:
    return TickOrchestrator(
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=None,
    )


# ── result fixtures (合法契约样本) ──


def _valid_result(stage: str) -> dict:
    fixtures: dict[str, dict] = {
        "architect": {
            "stage": "architect",
            "plan": _VALID_PLAN,
            "batch_plan": [{"batch_id": "b1", "component": "c1", "tasks": []}],
            "file_list": ["auto_engineering/foo.py"],
            "contracts": {},
        },
        "developer": {
            "stage": "developer",
            "batch_id": "b1",
            "files_changed": ["auto_engineering/foo.py"],
            "commit_hash": "abc123",
            "test_results": {"passed": 3, "failed": 0},
        },
        "critic": {
            "stage": "critic",
            "verdict": "APPROVE",
            "findings": [],
            "critic_feedback": "looks good",
        },
        "component_verifier": {
            "stage": "component_verifier",
            "component": "c1",
            "coverage_map": [{"design_item": "x", "status": "IMPLEMENTED"}],
            "missing_count": 0,
            "diverged_count": 0,
        },
    }
    return fixtures[stage]


class TestSchemaFilesVersionedAndValid:
    def test_action_schema_meta_valid(self):
        Draft202012Validator.check_schema(_ACTION_SCHEMA)

    def test_result_schema_meta_valid(self):
        Draft202012Validator.check_schema(_RESULT_SCHEMA_JSON)

    def test_both_schemas_versioned_have_id(self):
        assert _ACTION_SCHEMA["$id"].endswith("action.schema.json")
        assert _RESULT_SCHEMA_JSON["$id"].endswith("stage-result.schema.json")
        # 版本化: $comment 声明 contract 版本号 (vN.N.N)
        assert "v1.0.0" in _ACTION_SCHEMA["$comment"]
        assert "v1.0.0" in _RESULT_SCHEMA_JSON["$comment"]


class TestResultSchemaMirrorsRuntimeSSOT:
    """stage-result.schema.json per-stage required == actions.RESULT_SCHEMA (防漂移)."""

    @staticmethod
    def _schema_required_map() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for clause in _RESULT_SCHEMA_JSON["allOf"]:
            const = clause["if"]["properties"]["stage"]["const"]
            out[const] = clause["then"]["required"]
        return out

    def test_every_runtime_stage_covered_by_schema(self):
        m = self._schema_required_map()
        for stage in RESULT_SCHEMA:
            assert stage in m, f"stage-result.schema.json 缺 stage '{stage}'"

    def test_no_orphan_stage_in_schema(self):
        m = self._schema_required_map()
        for stage in m:
            assert stage in RESULT_SCHEMA, f"schema 含 RESULT_SCHEMA 未定义的 stage '{stage}'"

    def test_required_fields_identical_per_stage(self):
        m = self._schema_required_map()
        for stage, spec in RESULT_SCHEMA.items():
            assert sorted(m[stage]) == sorted(spec["required"]), (
                f"stage '{stage}' required 漂移: schema={sorted(m[stage])} "
                f"vs RESULT_SCHEMA={sorted(spec['required'])}"
            )


class TestActionSchemaStagesMirrorSSOT:
    def _enum(self) -> set[str]:
        return set(_ACTION_SCHEMA["properties"]["action"]["enum"])

    def test_intermediate_stages_match_ssot(self):
        intermediate = self._enum() - {"done", "error"}
        expected = set(RESULT_SCHEMA) | set(_PHASE0_STAGES)
        assert intermediate == expected, (
            f"action enum 中间 stage 漂移: {intermediate} vs {expected}"
        )

    def test_terminal_actions_present(self):
        assert {"done", "error"} <= self._enum()


class TestActionRoundTrip:
    """≥2 真实 _build_action 输出符合 action.schema.json (绑定代码非仅 fixture)."""

    def test_real_architect_action_conforms(self):
        o = _orchestrator()
        action = o.init("实现登录功能")  # 真实 _build_action(architect)
        assert action["action"] == "architect"
        _action_validator.validate(action)  # raises if invalid

    def test_real_gap_scan_action_conforms(self, tmp_path):
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))  # 真实 _build_action(gap_scan)
        assert action["action"] == "gap_scan"
        _action_validator.validate(action)

    def test_done_action_conforms(self):
        action = ActionDone("GOAL_ACHIEVED", reason="all gates pass", tick=5).to_dict()
        _action_validator.validate(action)

    def test_error_action_conforms(self):
        action = ActionError(error_code="STAGE_MISMATCH", message="bad stage").to_dict()
        _action_validator.validate(action)

    def test_error_action_missing_code_rejected(self):
        assert not _action_validator.is_valid({"action": "error", "message": "x"})

    def test_unknown_action_value_rejected(self):
        assert not _action_validator.is_valid({"action": "not_a_stage"})


class TestResultRoundTrip:
    """result fixture 同时通过 JSON schema 与运行时 validate_result_format (双校验一致)."""

    @pytest.mark.parametrize("stage", ["architect", "developer", "critic", "component_verifier"])
    def test_valid_result_passes_both_validators(self, stage):
        r = _valid_result(stage)
        _result_validator.validate(r)  # schema OK
        assert validate_result_format(r, stage) == []  # runtime OK

    def test_missing_required_rejected_by_both(self):
        r = _valid_result("architect")
        del r["plan"]  # 缺必填
        assert not _result_validator.is_valid(r)
        assert validate_result_format(r, "architect") != []

    def test_bad_verdict_rejected_by_both(self):
        r = _valid_result("critic")
        r["verdict"] = "WRONG"
        assert not _result_validator.is_valid(r)
        assert validate_result_format(r, "critic") != []

    def test_bad_coverage_status_rejected_by_both(self):
        r = _valid_result("component_verifier")
        r["coverage_map"] = [{"design_item": "x", "status": "BOGUS"}]
        assert not _result_validator.is_valid(r)
        assert validate_result_format(r, "component_verifier") != []
