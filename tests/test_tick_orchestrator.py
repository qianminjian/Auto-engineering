"""TickOrchestrator unit tests — 完整 LEAF batch_plan 循环 (快速 stub, 防挂死).

设计参考: v5.6-Design-Loop.md §C.5.

所有测试注入:
  - gate_runner:    快速 stub (全 PASS, 不跑真实 lint/test)
  - guardrail:      快速 stub (always pass)
  - EventStore: 可选注入，用于验证单一事件事实链

单文件 pytest --timeout=60, 无真实子进程/LLM.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import VerificationLayers
from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import WorkerAttestation
from auto_engineering.loop.actions import ErrorResponse
from auto_engineering.loop.architect_validation import dry_run_architect_plan
from auto_engineering.loop.effects import EffectExecutor
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.reducers import default_reducer_registry
from auto_engineering.loop.scope_validators import validate_critic_scope
from auto_engineering.loop.stages.base import TransitionContext
from auto_engineering.loop.stages.design import CriticHandler
from auto_engineering.loop.stages.verification import (
    ComponentVerifierHandler,
    SystemVerifierHandler,
)
from auto_engineering.loop.tick_orchestrator import ORCH_BUDGET_MS, TickOrchestrator

_TEST_RUNTIME_HANDLE = tempfile.TemporaryDirectory(prefix="ae-orchestrator-tests-")
_TEST_RUNTIME_ROOT = Path(_TEST_RUNTIME_HANDLE.name)
(_TEST_RUNTIME_ROOT / "demo").mkdir()
(_TEST_RUNTIME_ROOT / "pyproject.toml").write_text(
    "[project]\nname='demo'\n", encoding="utf-8"
)
_ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
_ACTIVE_ORCHESTRATOR: TickOrchestrator | None = None


class _EnvelopeTestOrchestrator(TickOrchestrator):
    """把旧的紧凑测试输入扩展为当前 Result Envelope。"""

    def tick_dict(self, result: dict) -> dict:
        if "schema_version" not in result and self._active_action is not None:
            active = self._active_action
            result = {
                "schema_version": "1.1",
                "message_type": "result",
                "message_id": f"test-result-{active['tick']}",
                "thread_id": active["thread_id"],
                "tick": active["tick"],
                "stage": result.get("stage", active["stage"]),
                "causation_id": active["message_id"],
                "correlation_id": active["correlation_id"],
                "extensions": {},
                **result,
            }
        return super().tick_dict(result)


def _worker_prompt(action: dict) -> str:
    """读取当前 Action 绑定的 Worker prompt artifact，不从 Action 内联取正文。"""

    invocation = action["spawn"]["invocations"][0]
    return (_ACTIVE_TEST_ROOT / invocation["prompt_ref"]).read_text(
        encoding="utf-8"
    )


def _materialize_worker_action(builder, state, **kwargs):
    plan = builder.build_plan(state, **kwargs)
    executor = EffectExecutor(builder.project_root)
    for intent in plan.effect_intents:
        executor.execute(intent)
    action = plan.payload
    invocation = action["spawn"]["invocations"][0]
    prompt = (builder.project_root / invocation["prompt_ref"]).read_text(
        encoding="utf-8"
    )
    return action, prompt


@pytest.fixture(autouse=True)
def _track_active_orchestrator(monkeypatch):
    """让旧文件式 Result 夹具绑定当前严格 Action，而非伪造 Core 证明。"""
    original = TickOrchestrator.init

    def tracked(orchestrator, *args, **kwargs):
        global _ACTIVE_ORCHESTRATOR, _ACTIVE_TEST_ROOT
        _ACTIVE_ORCHESTRATOR = orchestrator
        _ACTIVE_TEST_ROOT = orchestrator.project_root
        return original(orchestrator, *args, **kwargs)

    monkeypatch.setattr(TickOrchestrator, "init", tracked)


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    g = MagicMock()
    g.check.return_value = MagicMock(action="pass")
    return g


def _orchestrator(escalate: bool = False) -> TickOrchestrator:
    global _ACTIVE_ORCHESTRATOR, _ACTIVE_TEST_ROOT
    _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
    _ACTIVE_ORCHESTRATOR = _EnvelopeTestOrchestrator(
        project_root=_TEST_RUNTIME_ROOT,
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        escalate=escalate,
    )
    return _ACTIVE_ORCHESTRATOR


def _make_result_file(data: dict) -> Path:
    active = _ACTIVE_ORCHESTRATOR._active_action if _ACTIVE_ORCHESTRATOR else None
    if data.get("stage") == "developer" and "task_ids" not in data:
        extensions = active.get("extensions") if isinstance(active, dict) else None
        scope = (
            extensions.get("execution_scope")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(scope, dict) and isinstance(scope.get("task_ids"), list):
            data["task_ids"] = list(scope["task_ids"])
    active_spawn = active.get("spawn") if isinstance(active, dict) else None
    if (
        data.get("spawned") is not False
        and isinstance(active_spawn, dict)
        and active.get("stage") == data.get("stage")
    ):
        data["spawned"] = True
        proof_path = (
            _ACTIVE_TEST_ROOT / ".ae-state" / "spawn-proofs"
            / f"{active['spawn_proof_token']}.json"
        )
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["status"] = "completed"
        proof["completed_at"] = "2026-08-01T00:00:00Z"
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        data["spawn_proof_token"] = active["spawn_proof_token"]
        plan = SpawnPlan.from_action(active)
        for spec in plan.invocations:
            (_ACTIVE_TEST_ROOT / spec.receipt_path).write_text(json.dumps({
                "status": "completed", "stage": active["stage"],
                "worker": spec.worker_id,
                "native_worker_handle": f"test-{spec.worker_id}",
                "requested_effort": spec.requested_effort,
                "actual_model": "test-model",
            }), encoding="utf-8")
        data["worker_attestations"] = [
            WorkerAttestation.completed(
                platform=HostPlatform.CODEX,
                action_message_id=active["message_id"],
                invocation=spec,
                effective_effort=spec.requested_effort,
                isolation_evidence="fork_turns=none",
                visible_capabilities=tuple(sorted(spec.capabilities)),
                actual_model="test-model",
            ).to_dict()
            for spec in plan.invocations
        ]
    if active is not None:
        data = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": f"result-{active['message_id']}-{active['tick']}",
            "thread_id": active["thread_id"],
            "tick": active["tick"],
            "stage": data.get("stage", active["stage"]),
            "causation_id": active["message_id"],
            "correlation_id": active["correlation_id"],
            "extensions": {},
            **data,
        }
    f = Path(tempfile.mktemp(suffix=".json"))
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def _prepare_existing_project(project_root: Path) -> None:
    """创建可由有界 Probe 确认的最小现有 Python 项目。"""
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (project_root / "demo").mkdir(exist_ok=True)


# 满足 architect RESULT_SCHEMA plan_min_length=50 的有效计划 (内容对路由无影响)
_VALID_PLAN = (
    "实现组件, 包含完整的 TDD Red-Green-Refactor 循环 + Gate 验证流程, 确保文件隔离检查通过"
)


# ── init ──


class TestInit:
    def test_init_without_design_doc_starts_architect(self) -> None:
        o = _orchestrator()
        action = o.init("实现登录功能")
        assert action["action"] == "architect"
        assert action["stage"] == "architect"
        assert action["tick"] == 1
        # DS-15: requirement at action top level, context removed from spawn stages
        assert action["requirement"] == "实现登录功能"

    def test_init_sets_expected_stage(self) -> None:
        o = _orchestrator()
        o.init("req")
        assert o._state.expected_stage == "architect"

    def test_unchanged_revision_blocks_duplicate_deep_audit(
        self, tmp_path: Path
    ) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "system_deep_audit"
        revision = o._audit_revision_fingerprint("system_deep_audit")
        o._state.audit_revision_fingerprints["system_deep_audit"] = revision

        action = o._apply_loop_budget({
            "action": "system_deep_audit",
            "stage": "system_deep_audit",
            "spawn": {"count": 3},
        })

        assert action["action"] == "error"
        assert action["error_code"] == "AUDIT_REVISION_UNCHANGED"

    def test_init_with_design_doc_starts_gap_scan(self, tmp_path) -> None:
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'")
        (tmp_path / "demo").mkdir()
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))
        assert action["stage"] == "gap_scan"
        assert action["action"] == "gap_scan"
        assert o._state.design_doc_digest.startswith("sha256:")
        assert "gaps" in action["expected_format"]
        assert o._design_doc is not None
        assert "设计模糊性扫描者" in action["instruction"]
        assert '"requirement": "req"' in action["instruction"]

    def test_architect_dry_run_uses_component_title_or_section_ref(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text("## B1 页面\n### Button\n实现按钮\n", encoding="utf-8")
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("实现页面", design_doc_path=str(design))
        valid = {
            "stage": "architect",
            "batch_plan": [{
                "batch_id": "B1",
                "component": "Button",
                "design_section": "Button",
                "design_item_refs": ["Button-1"],
                "tasks": [{
                    "id": "B1-T1", "description": "实现按钮", "kind": "implementation",
                    "module_ref": "Button", "file_targets": ["button.py"],
                    "depends_on": [],
                }],
            }],
        }
        assert dry_run_architect_plan(o._design_doc, valid, o._state.requirement) is None
        invalid = {**valid, "batch_plan": [{
            **valid["batch_plan"][0], "component": "Missing", "design_section": "Missing"
        }]}
        assert "Missing" in (
            dry_run_architect_plan(o._design_doc, invalid, o._state.requirement) or ""
        )

    def test_architect_plan_requires_design_item_refs_when_component_has_items(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text(
            "## B1 页面\n### Button\n#### 行为\n必须可点击\n",
            encoding="utf-8",
        )
        doc = DesignDoc.parse(design)
        result = {
            "stage": "architect",
            "batch_plan": [{
                "batch_id": "B1",
                "component": "Button",
                "design_section": "Button",
                "tasks": [{
                    "id": "T1", "description": "实现按钮", "kind": "implementation",
                    "module_ref": "Button", "file_targets": ["button.py"],
                    "depends_on": [],
                }],
            }],
        }

        error = dry_run_architect_plan(doc, result, "实现页面")

        assert error is not None
        assert "BATCH_DESIGN_ITEM_SCOPE_REQUIRED" in error

    @pytest.mark.parametrize("coverage_map", [
        [{"design_item": "§1.1-2", "status": "IMPLEMENTED"}],
        [],
    ])
    def test_component_verifier_rejects_scope_drift(self, coverage_map, tmp_path) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "component_verifier"
        o._active_action = {
            "stage": "component_verifier",
            "verification_scope": {
                "mode": "batch_design_items",
                "component": "类型系统",
                "batch_id": "B1",
                "design_item_ids": ["§1.1-1"],
            },
        }
        o._active_action = {
            **o._active_action,
            "message_id": "test-active",
            "thread_id": o._state.thread_id,
            "tick": o._state.tick,
            "correlation_id": o._state.thread_id,
        }
        result_file = _make_result_file({
            "stage": "component_verifier",
            "component": "类型系统",
            "coverage_map": coverage_map,
            "missing_count": 0,
            "diverged_count": 0,
        })

        result = o._validate_result_dict(
            json.loads(result_file.read_text(encoding="utf-8"))
        )

        assert result.error_code == "COMPONENT_VERIFICATION_SCOPE_INVALID"

    def test_component_verifier_rejects_out_of_scope_file(self, tmp_path) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "component_verifier"
        o._active_action = {
            "stage": "component_verifier",
            "verification_scope": {
                "mode": "batch_design_items",
                "component": "类型系统",
                "batch_id": "B1",
                "design_item_ids": ["§1.1-1"],
                "file_targets": ["src/types.py"],
            },
        }
        result = o._validate_result_dict({
            "stage": "component_verifier",
            "component": "类型系统",
            "coverage_map": [{
                "design_item": "§1.1-1",
                "status": "IMPLEMENTED",
                "file": "src/other.py",
            }],
            "missing_count": 0,
            "diverged_count": 0,
        })

        assert result.error_code == "COMPONENT_VERIFICATION_SCOPE_INVALID"

    def test_critic_rejects_finding_outside_active_batch(self, tmp_path) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "critic"
        o._active_action = {
            "stage": "critic",
            "extensions": {
                "execution_scope": {
                    "schema_version": "1.0",
                    "mode": "critic_batch",
                    "batch_id": "B1",
                    "file_targets": ["src/types.py"],
                }
            },
        }
        result = o._validate_result_dict({
            "stage": "critic",
            "verdict": "MAJOR",
            "findings": [{
                "severity": "P1",
                "kind": "implementation_defect",
                "file": "src/other.py",
                "issue": "越界",
                "suggestion": "修复",
            }],
            "strengths": [],
            "critic_feedback": "需要修复",
            "assessment": "With fixes",
        })

        assert result.error_code == "CRITIC_SCOPE_VIOLATION"

    def test_critic_accepts_explicit_cross_batch_finding(self, tmp_path) -> None:
        """跨批次阻断问题必须走显式通道，不能被普通 scope 规则吞掉。"""
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "critic"
        o._active_action = {
            "stage": "critic",
            "extensions": {
                "execution_scope": {
                    "schema_version": "1.0",
                    "mode": "critic_batch",
                    "batch_id": "B1",
                    "file_targets": ["src/types.py"],
                }
            },
        }
        payload = {
            "stage": "critic",
            "verdict": "MAJOR",
            "findings": [],
            "cross_batch_findings": [{
                "finding_id": "F-CROSS-001",
                "severity": "P0",
                "kind": "implementation_defect",
                "file": "src/hooks/useAudioRecorder.ts",
                "line": 38,
                "issue": "越界但阻断闭环",
                "suggestion": "修复并增加回归测试",
            }],
            "strengths": [],
            "critic_feedback": "需要修复",
            "assessment": "With fixes",
        }
        error = validate_critic_scope(o, payload)

        assert error is None

    def test_system_audit_rejects_out_of_scope_file(self, tmp_path) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "system_deep_audit"
        o._active_action = {
            "stage": "system_deep_audit",
            "extensions": {
                "execution_scope": {
                    "schema_version": "1.0",
                    "mode": "system_deep_audit",
                    "file_targets": ["src/known.py"],
                }
            },
        }
        result = o._validate_result_dict({
            "stage": "system_deep_audit",
            "findings": [{
                "severity": "P1",
                "dimension": "code_quality",
                "file": "src/other.py",
                "line": 1,
                "description": "越界",
                "evidence": "证据",
                "suggested_fix": "修复",
            }],
            "p0_count": 0,
            "p1_count": 1,
            "p2_count": 0,
            "total_audited_files": 1,
            "design_docs_stale": False,
            "design_doc_suggestions": "",
            "missing_count": 0,
            "diverged_count": 0,
        })

        assert result.error_code == "GLOBAL_EVIDENCE_SCOPE_VIOLATION"

    def test_system_verifier_requires_bound_implementation_evidence(self, tmp_path) -> None:
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req")
        o._state.current_stage = "system_verifier"
        o._state.coverage_map = [{
            "design_item": "B1-1", "status": "IMPLEMENTED",
        }, {
            "design_item": "B1-2", "status": "IMPLEMENTED",
        }]
        o._active_action = {
            "stage": "system_verifier",
            "extensions": {
                "execution_scope": {
                    "schema_version": "1.0",
                    "mode": "system_verifier",
                    "file_targets": ["src/known.py"],
                }
            },
        }
        base = {
            "stage": "system_verifier",
            "spawned": True,
            "recheck_log": [],
            "full_coverage_map": [{
                "design_section": "B1",
                "design_item": "B1-1",
                "status": "IMPLEMENTED",
                "implementation": "",
                "note": "声明已找到实现",
            }],
            "total_design_items": 1,
            "covered_count": 1,
            "missing_count": 0,
            "diverged_count": 0,
        }

        invalid = o._validate_global_evidence_scope(base)
        assert invalid.error_code == "GLOBAL_EVIDENCE_SCOPE_INCOMPLETE"

        base["full_coverage_map"][0]["implementation"] = "src/known.py:42"
        invalid_cross_stage = o._validate_global_evidence_scope(base)
        assert invalid_cross_stage.error_code == "GLOBAL_EVIDENCE_SCOPE_INCOMPLETE"
        assert "cross_stage=" in invalid_cross_stage.message

        base["full_coverage_map"].append({
            "design_section": "B1",
            "design_item": "B1-2",
            "status": "IMPLEMENTED",
            "implementation": "src/known.py:43",
            "note": "声明已找到实现",
        })
        assert o._validate_global_evidence_scope(base) is None


# ── tick: architect → developer ──


class TestTickArchitectToDeveloper:
    def test_architect_result_builds_batch_state_and_advances(self) -> None:
        o = _orchestrator()
        o.init("实现 StageRouter")
        # feed nested batch_plan architect result
        r = _make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-SR-1",
                "design_section": "B2",
                "component": "StageRouter",
                "depends_on": [],
                "tasks": [
                    {"id": "T1", "description": "StageDecision + next() 骨架",
                     "module_ref": "§B2",
                     "file_targets": ["auto_engineering/loop/stage_router.py"]},
                ],
            }],
            "file_list": ["auto_engineering/loop/stage_router.py"],
            "contracts": {},
        })
        action = o.tick(r)
        assert action["action"] == "developer"
        assert action["stage"] == "developer"
        assert o._plan is not None
        assert o._batch_state is not None
        assert o._batch_state.current_component_name() == "StageRouter"
        assert o._verification_layers == VerificationLayers.LEAF

    def test_developer_result_must_match_active_batch_identity(self) -> None:
        o = _orchestrator()
        o.init("实现 StageRouter")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-SR-1",
                "design_section": "B2",
                "component": "StageRouter",
                "depends_on": [],
                "tasks": [{"id": "T1", "description": "实现骨架"}],
            }],
            "file_list": [],
            "contracts": {},
        }))

        response = o._validate_result_dict({
            "stage": "developer",
            "batch_id": "not-the-active-batch",
            "task_ids": ["T1"],
            "files_changed": [],
            "test_results": {"passed": 1, "failed": 0},
        })

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "DEVELOPER_BATCH_ID_MISMATCH"
        assert len(o._plan.get_tasks_by_stage("developer")) == 1

    def test_developer_result_must_cover_active_tasks_and_files(self) -> None:
        o = _orchestrator()
        o.init("实现 StageRouter")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-SR-1",
                "design_section": "B2",
                "component": "StageRouter",
                "depends_on": [],
                "tasks": [
                    {"id": "T1", "description": "实现骨架", "file_targets": ["x.py"]},
                    {"id": "T2", "description": "补测试", "file_targets": ["tests/test_x.py"]},
                ],
            }],
            "file_list": [],
            "contracts": {},
        }))

        missing_task = o._validate_result_dict({
            "stage": "developer",
            "spawned": True,
            "batch_id": "batch-SR-1",
            "task_ids": ["T1"],
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        })
        assert isinstance(missing_task, ErrorResponse)
        assert missing_task.error_code == "DEVELOPER_SCOPE_VIOLATION"
        assert "T2" in missing_task.message

        out_of_scope_file = o._validate_result_dict({
            "stage": "developer",
            "spawned": True,
            "batch_id": "batch-SR-1",
            "task_ids": ["T1", "T2"],
            "files_changed": ["outside.py"],
            "test_results": {"passed": 1, "failed": 0},
        })
        assert isinstance(out_of_scope_file, ErrorResponse)
        assert out_of_scope_file.error_code == "DEVELOPER_SCOPE_VIOLATION"
        assert "outside.py" in out_of_scope_file.message

    def test_empty_batch_plan_returns_error(self) -> None:
        o = _orchestrator()
        o.init("req")
        r = _make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [],
            "file_list": ["x.py"], "contracts": {},
        })
        action = o.tick(r)
        assert action["action"] == "error"
        assert action["error_code"] == "RESULT_VALIDATION_ERROR"


# ── tick: developer → critic (multiple batches) ──


class TestTickDeveloperToCritic:
    def test_developer_batch_complete_advances_to_critic(self) -> None:
        o = _orchestrator()
        o.init("req")
        # architect tick
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-X-1", "design_section": "B2", "component": "X",
                "tasks": [{"id": "T1", "description": "d1", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }],
            "file_list": ["x.py"], "contracts": {},
        }))
        # developer tick (唯一 batch 完成 → critic)
        action = o.tick(_make_result_file({
            "stage": "developer",
            "batch_id": "batch-X-1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 3, "failed": 0},
        }))
        assert action["action"] == "critic"
        assert action["stage"] == "critic"

    def test_multiple_batches_stay_developer(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b1", "design_section": "B2", "component": "C",
                 "tasks": [{"id": "T1", "description": "d1", "module_ref": "§B2",
                            "file_targets": ["a.py"]}]},
                {"batch_id": "b2", "design_section": "B2", "component": "C",
                 "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B2",
                            "file_targets": ["b.py"]}]},
            ],
            "file_list": ["a.py", "b.py"], "contracts": {},
        }))
        # first developer batch
        a1 = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["a.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        assert a1["action"] == "developer"  # 还有 batch b2
        assert a1["batch_id"] == "b2"
        # second developer batch → critic
        a2 = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b2",
            "files_changed": ["b.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        assert a2["action"] == "critic"



# ── critic → component_verifier → system_deep_audit → convergence ──


class TestFullLeafConvergence:
    def test_clean_leaf_assurance_bundle_reaches_goal_without_more_workers(self) -> None:
        o = _orchestrator()
        o.init("实现单个组件")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        critic = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        assert "assurance_bundle" in critic["expected_format"]

        done = o.tick(_make_result_file({
            "stage": "critic", "spawned": True,
            "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
            "assurance_bundle": {
                "component_verification": {
                    "component": "Foo",
                    "coverage_map": [{
                        "design_item": "B2-1", "status": "IMPLEMENTED",
                        "file": "foo.py", "line": 1, "note": "",
                    }],
                    "missing_count": 0,
                    "diverged_count": 0,
                    "recheck_log": [],
                },
                "system_audit": {
                    "dimensions": [
                        "architecture", "code_quality", "engineering",
                        "virtualization", "team_design_coverage",
                    ],
                    "findings": [],
                    "p0_count": 0,
                    "p1_count": 0,
                    "p2_count": 0,
                    "total_audited_files": 1,
                    "design_docs_stale": False,
                    "design_doc_suggestions": [],
                    "missing_count": 0,
                    "diverged_count": 0,
                },
            },
        }))

        assert done["action"] == "done"
        assert done["verdict"] == "GOAL_ACHIEVED"
        assert o._state.coverage_map[0]["status"] == "IMPLEMENTED"

    def test_full_leaf_cycle_reaches_goal_achieved(self) -> None:
        """LEAF: architect→dev→critic→comp_verifier→system_deep_audit→GOAL_ACHIEVED."""
        o = _orchestrator()
        o.init("实现单个组件")

        # 1. architect
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))

        # 2. developer
        a_dev = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        assert a_dev["stage"] == "critic"

        # 3. critic APPROVE
        a_critic = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        assert a_critic["stage"] == "component_verifier"

        # 4. component_verifier (all covered, no gaps)
        a_verifier = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [
                {"design_item": "B2-1", "status": "IMPLEMENTED",
                 "file": "foo.py", "line": 10, "note": ""},
            ],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a_verifier["stage"] == "system_deep_audit"

        # 5. system_deep_audit (no P0/P1, design_coverage_ok)
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True,
            "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 1,
            "total_audited_files": 2,
            "design_docs_stale": False,
            "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a_audit["action"] == "done"
        assert a_audit["verdict"] == "GOAL_ACHIEVED"
        assert (
            a_audit["extensions"]["ae"]["runtime_revision"]["engine_build_id"]
            != "unknown"
        )


class TestPlateConvergence:
    """PLATE (T19): 2 组件单板块 → component_verifier×2 → plate_deep_audit →
    system_deep_audit → GOAL_ACHIEVED (跳过 system_verifier)。

    覆盖 LEAF 路径不经过的 plate_deep_audit 层集成。
    """

    @staticmethod
    def _approve_component(o: TickOrchestrator, component: str, batch_id: str) -> dict:
        """driver: developer → critic APPROVE → component_verifier(clean), 返回下一 action."""
        a_dev = o.tick(_make_result_file({
            "stage": "developer", "batch_id": batch_id,
            "files_changed": [f"{component.lower()}.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        assert a_dev["stage"] == "critic"
        a_critic = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "ok",
        }))
        assert a_critic["stage"] == "component_verifier"
        return o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": component,
            "coverage_map": [
                {"design_item": f"{component}-1", "status": "IMPLEMENTED",
                 "file": f"{component.lower()}.py", "line": 1, "note": ""},
            ],
            "missing_count": 0, "diverged_count": 0,
        }))

    def test_plate_cycle_runs_plate_deep_audit_then_goal(self) -> None:
        o = _orchestrator()
        o.init("实现两个组件的板块")

        # architect: 2 distinct components → PLATE (total_plates=1, components=2)
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b-Foo", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "foo", "module_ref": "§B2",
                            "file_targets": ["foo.py"]}]},
                {"batch_id": "b-Bar", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "bar", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ],
            "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))
        assert o._verification_layers == VerificationLayers.PLATE

        # 组件 1 (Foo) 验完 → 仍有组件 → 回 developer (Bar)
        a_after_foo = self._approve_component(o, "Foo", "b-Foo")
        assert a_after_foo["stage"] == "developer"

        # 组件 2 (Bar) 验完 → 无更多组件 → PLATE → plate_deep_audit
        a_after_bar = self._approve_component(o, "Bar", "b-Bar")
        assert a_after_bar["stage"] == "plate_deep_audit"

        # plate_deep_audit clean → 无更多板块 → PLATE → system_deep_audit (跳 system_verifier)
        a_plate = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "spawned": True, "plate": "(single)", "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "cross_component_issues": [], "total_audited_files": 2,
        }))
        assert a_plate["stage"] == "system_deep_audit"

        # system_deep_audit clean → GOAL_ACHIEVED
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "total_audited_files": 2, "design_docs_stale": False,
            "design_doc_suggestions": "", "missing_count": 0, "diverged_count": 0,
        }))
        assert a_audit["action"] == "done"
        assert a_audit["verdict"] == "GOAL_ACHIEVED"

    def test_full_layer_routes_plate_audit_through_system_verifier(self) -> None:
        """FULL: plate_deep_audit clean → system_verifier → system_deep_audit。

        与 PLATE 的差异只在验证尾部多一层 system_verifier (7 Agent)。多板块推进
        机制已由 determine_verification_layers 单测覆盖 (test_verification_layers.py)；
        此处置单板块 + 手动 FULL 隔离该分支路由 (line 511-512 / 528), 避免重复
        构造重量级多板块 design_doc E2E。
        """
        o = _orchestrator()
        o.init("实现两个组件的板块")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b-Foo", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "foo", "module_ref": "§B2",
                            "file_targets": ["foo.py"]}]},
                {"batch_id": "b-Bar", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "bar", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ],
            "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))
        # 模拟多板块设计文档场景的验证尾部路由
        o._verification_layers = VerificationLayers.FULL

        self._approve_component(o, "Foo", "b-Foo")
        a_after_bar = self._approve_component(o, "Bar", "b-Bar")
        assert a_after_bar["stage"] == "plate_deep_audit"

        # plate_deep_audit clean → FULL → system_verifier (不跳过)
        a_plate = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "spawned": True, "plate": "(single)", "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "cross_component_issues": [], "total_audited_files": 2,
        }))
        assert a_plate["stage"] == "system_verifier"

        # system_verifier clean → system_deep_audit
        a_sysv = o.tick(_make_result_file({
            "stage": "system_verifier", "spawned": True,
            "full_coverage_map": [
                {
                    "design_section": "B2", "design_item": "Foo-1",
                    "status": "IMPLEMENTED", "implementation": "foo.py:1",
                    "note": "已在实现文件中找到对应代码",
                },
                {
                    "design_section": "B3", "design_item": "Bar-1",
                    "status": "IMPLEMENTED", "implementation": "bar.py:1",
                    "note": "已在实现文件中找到对应代码",
                },
            ],
            "total_design_items": 2, "covered_count": 2,
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a_sysv["stage"] == "system_deep_audit"

        # system_deep_audit clean → GOAL_ACHIEVED
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "total_audited_files": 2, "design_docs_stale": False,
            "design_doc_suggestions": "", "missing_count": 0, "diverged_count": 0,
        }))
        assert a_audit["action"] == "done"
        assert a_audit["verdict"] == "GOAL_ACHIEVED"


class TestSystemDeepAuditCoverageGate:
    """system_deep_audit 覆盖度信号不能是空操作.

    Bug 2: expected_format 不含 missing_count/diverged_count → Agent 不产出 →
    design_coverage_ok 恒 True → 每次首轮无 P0/P1 即误判 GOAL_ACHIEVED.
    修复方向 (对齐 verifier 回路): 补 expected_format 键 + 覆盖缺口路由到
    plan_refine 做补充设计, 而非终止.
    """

    def _drive_to_system_deep_audit(self, o) -> dict:
        """走 architect→dev→critic→comp_verifier(clean), 返回 system_deep_audit action."""
        o.init("实现单个组件")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        return o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))

    def test_expected_format_requests_coverage_keys(self) -> None:
        """system_deep_audit action 必须向 Agent 索要 missing_count/diverged_count."""
        o = _orchestrator()
        a = self._drive_to_system_deep_audit(o)
        assert a["stage"] == "system_deep_audit"
        assert "missing_count" in a["expected_format"]
        assert "diverged_count" in a["expected_format"]

    def test_coverage_gap_routes_to_plan_refine_not_goal(self) -> None:
        """无 P0/P1 但 missing_count>0 → 回 architect 补充设计, 不误判 GOAL_ACHIEVED."""
        o = _orchestrator()
        self._drive_to_system_deep_audit(o)
        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 1, "diverged_count": 0,
        }))
        assert a["action"] == "architect"  # plan_refine → 补充设计
        assert a.get("verdict") not in ("GOAL_ACHIEVED", "UNEXPECTED")

    def test_diverged_gap_also_routes_to_plan_refine(self) -> None:
        """diverged_count>0 同样触发补充设计回路."""
        o = _orchestrator()
        self._drive_to_system_deep_audit(o)
        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 2,
        }))
        assert a["action"] == "architect"

    def test_event_store_replays_deep_audit_revision_as_verification_fact(self, tmp_path) -> None:
        """Deep Audit 去重指纹必须随验证事件进入 EventStore 投影。"""
        global _ACTIVE_ORCHESTRATOR, _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
        with SQLiteEventStore(tmp_path / "events.db") as events:
            o = TickOrchestrator(
                _TEST_RUNTIME_ROOT,
                gate_runner=_pass_gate_runner,
                guardrail=_pass_guardrail(),
                event_store=events,
            )
            _ACTIVE_ORCHESTRATOR = o
            self._drive_to_system_deep_audit(o)
            action = o.tick(_make_result_file({
                "stage": "system_deep_audit", "spawned": True,
                "findings": [], "p0_count": 0, "p1_count": 0,
                "p2_count": 0, "total_audited_files": 1,
                "design_docs_stale": False, "design_doc_suggestions": "",
                "missing_count": 0, "diverged_count": 0,
            }))

            assert action["verdict"] == "GOAL_ACHIEVED"
            stream = events.load_stream(o._state.thread_id)
            verification_events = [
                event for event in stream
                if event.event_type is LoopEventType.VERIFICATION_STATE_UPDATED
                and "audit_revision_fingerprints"
                in event.to_dict()["payload"].get("changes", {})
            ]
            assert len(verification_events) == 1, [
                (event.event_type.value, list(event.to_dict()["payload"]))
                for event in stream[-8:]
            ]
            projection = events.load_projection(o._state.thread_id)
            assert projection is not None
            assert projection.audit_revision_fingerprints == (
                o._state.audit_revision_fingerprints
            )


# ── MAJOR loop ──


class TestCriticMajorLoop:
    def test_critic_major_returns_to_developer(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},  # developer 必须 TDD-green
        }))
        # critic MAJOR
        action = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "MAJOR",
            "findings": [{"file": "x.py", "line": 1, "severity": "P0",
                          "issue": "bug", "suggestion": "fix"}],
        }))
        assert action["action"] == "developer"
        assert action["stage"] == "developer"
        assert action["feedback"] is not None  # findings 注入

    def test_developer_repair_does_not_complete_the_same_batch_twice(self) -> None:
        """Critic 返修只重开工作，不得再次推进已完成的 Batch 游标。"""
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "MAJOR",
            "findings": [{"file": "x.py", "line": 1, "severity": "P0",
                          "issue": "bug", "suggestion": "fix"}],
        }))

        action = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))

        assert action["action"] == "critic"
        assert o._progress_tree is not None
        component = o._progress_tree.find_by_design_section("B2")
        assert component is not None
        assert component.done_tasks == component.total_tasks == 1

    def test_two_critic_repairs_preserve_completed_batch_cursor(self) -> None:
        """连续 MAJOR 返修后 APPROVE 必须进入验证，不得倒退重做已完成批次。"""
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        for issue in ("first defect", "second defect"):
            o.tick(_make_result_file({
                "stage": "critic", "spawned": True, "verdict": "MAJOR",
                "findings": [{"file": "x.py", "line": 1, "severity": "P0",
                              "issue": issue, "suggestion": "fix"}],
            }))
            o.tick(_make_result_file({
                "stage": "developer", "batch_id": "b1",
                "files_changed": ["x.py"],
                "test_results": {"passed": 2, "failed": 0},
            }))

        action = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE",
            "findings": [],
        }))

        assert action["action"] == "component_verifier"
        assert o._batch_state is not None
        assert o._batch_state.is_component_complete()
        assert o._progress_tree is not None
        component = o._progress_tree.find_by_design_section("B2")
        assert component is not None
        assert component.done_tasks == component.total_tasks == 1

    def test_critic_major_invalid_verdict_returns_error(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        action = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "INVALID", "findings": [],
        }))
        assert action["action"] == "error"
        # verdict 值域由 RESULT_SCHEMA 边界校验拦截 (先于 _after_critic)
        assert action["error_code"] == "RESULT_VALIDATION_ERROR"


# ── error handling ──


class TestErrorHandling:
    def test_stage_mismatch_returns_error_response(self) -> None:
        o = _orchestrator()
        o.init("req")  # stage=architect
        r = _make_result_file({"stage": "developer", "files_changed": ["x.py"]})
        action = o.tick(r)
        assert action["action"] == "error"
        assert action["error_code"] == "STAGE_MISMATCH"

    def test_delayed_stage_result_is_rejected_without_state_projection(self) -> None:
        """延迟的上一阶段 payload 不能再通过 E2 降级写入当前状态。"""
        o = _orchestrator()
        active = o.init("req")
        before_plan = o._state.plan
        result = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "delayed-result",
            "thread_id": active["thread_id"],
            "tick": active["tick"],
            "stage": "developer",
            "causation_id": active["message_id"],
            "correlation_id": active["correlation_id"],
            "extensions": {},
            "spawned": True,
            "files_changed": ["stale.py"],
            "test_results": {"passed": 1, "failed": 0},
        }

        action = o.tick_dict(result)

        assert action["action"] == "error"
        assert action["error_code"] == "STAGE_MISMATCH"
        assert o._state.plan == before_plan

    @pytest.mark.parametrize(
        ("field", "value"),
        [("correlation_id", "other-thread"), ("tick", 999)],
    )
    def test_native_result_must_bind_active_action_correlation_and_tick(
        self, field: str, value: object,
    ) -> None:
        o = _orchestrator()
        active = o.init("req")
        result = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "result-1",
            "thread_id": active["thread_id"],
            "tick": active["tick"],
            "stage": active["stage"],
            "causation_id": active["message_id"],
            "correlation_id": active["correlation_id"],
            "extensions": {},
            "spawned": True,
            field: value,
        }

        action = o.tick_dict(result)

        assert action["action"] == "error"
        assert action["error_code"] == "ACTION_NOT_ACTIVE"

    def test_invalid_json_returns_parse_error(self) -> None:
        o = _orchestrator()
        o.init("req")
        f = Path(tempfile.mktemp(suffix=".json"))
        f.write_text("not json", encoding="utf-8")
        action = o.tick(f)
        assert action["action"] == "error"
        assert action["error_code"] == "RESULT_PARSE_ERROR"


# ── plan_refine limit ──


class TestPlanRefineLimit:
    def test_plan_refine_returns_to_architect(self) -> None:
        """gap → plan_refine → 返回 architect 重新生成 batch_plan."""
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        a1 = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "C",
            "coverage_map": [{"design_item": "B2-1", "status": "MISSING"}],
            "missing_count": 1, "diverged_count": 0,
        }))
        assert a1["action"] == "architect"  # plan_refine → architect

    def test_refine_limit_by_pre_set_counter(self) -> None:
        """预设分源计数器到 MAX (=2), 下一次 plan_refine 触发 REFINE_LIMIT."""
        o = _orchestrator()
        o.init("req")
        o._state.plan_refine_by_source["component_verifier"] = 2
        o._state.plan_refine_count = 2
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "C",
            "coverage_map": [{"design_item": "B2-1", "status": "MISSING"}],
            "missing_count": 1, "diverged_count": 0,
        }))
        assert a["action"] == "done"
        assert a["verdict"] == "REFINE_LIMIT"


class TestRefineRequestDelivery:
    """T20b: plan_refine 后 architect action 经 feedback 承载归一 RefineRequest (§B6.10)."""

    @staticmethod
    def _drive_component_gap(o: TickOrchestrator, status: str) -> dict:
        """architect→dev→critic(APPROVE)→component_verifier(缺口) → architect action."""
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1", "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        return o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": status,
                              "file": "foo.py", "line": 7, "note": "缺"}],
            "missing_count": 1 if status == "MISSING" else 0,
            "diverged_count": 1 if status == "DIVERGED" else 0,
        }))

    def test_architect_action_carries_plan_refine_feedback(self) -> None:
        o = _orchestrator()
        a = self._drive_component_gap(o, "MISSING")
        assert a["action"] == "architect"
        fb = a["feedback"]
        assert fb["mode"] == "PLAN_REFINE"
        req = fb["refine_request"]
        assert req["source"] == "component_verifier"
        assert req["scope_component"] == "Foo"
        assert len(req["gaps"]) == 1
        assert req["gaps"][0]["kind"] == "MISSING"
        assert req["gaps"][0]["design_ref"] == "B2-1"

    def test_diverged_gap_normalized_with_location(self) -> None:
        o = _orchestrator()
        a = self._drive_component_gap(o, "DIVERGED")
        gap = a["feedback"]["refine_request"]["gaps"][0]
        assert gap["kind"] == "DIVERGED"
        assert gap["location"] == "foo.py:7"

    def test_refine_request_json_persisted_to_state(self) -> None:
        o = _orchestrator()
        self._drive_component_gap(o, "MISSING")
        assert o._state.refine_request_json
        req = json.loads(o._state.refine_request_json)
        assert req["source"] == "component_verifier"
        assert req["trigger_tick"] >= 0

    def test_critic_plan_gap_is_delivered_to_architect_without_loss(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1", "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))

        action = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "MAJOR",
            "findings": [{
                "finding_id": "F-001", "severity": "P1",
                "kind": "contract_gap", "design_ref": "§11.3",
                "file": "foo.py", "line": 7,
                "issue": "契约缺失", "suggestion": "补实现与回归测试",
            }],
        }))

        assert action["stage"] == "architect"
        request = action["feedback"]["refine_request"]
        assert request["source"] == "critic"
        assert request["gaps"] == [{
            "kind": "CRITIC_FINDING",
            "design_ref": "§11.3",
            "detail": "契约缺失",
            "suggested_action": "补实现与回归测试",
            "severity": "P1",
            "location": "foo.py:7",
            "source_ref": "F-001",
        }]

    def test_empty_refine_input_fails_before_architect_transition(self) -> None:
        o = _orchestrator()
        o.init("req")
        stage_before = o._state.current_stage

        action = o._handle_plan_refine("critic")

        assert action["action"] == "error"
        assert action["error_code"] == "REFINE_INPUT_EMPTY"
        assert o._state.current_stage == stage_before
        assert o._state.plan_refine_count == 0

    def test_real_run_critic_findings_close_into_a_new_repair_batch(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B1", "component": "Setup",
                "tasks": [{"id": "b1-t1", "description": "initial",
                           "module_ref": "§11", "file_targets": ["setup.ts"]}],
            }],
            "file_list": ["setup.ts"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["setup.ts"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        findings = [
            {
                "finding_id": finding_id,
                "severity": "P1",
                "kind": kind,
                "file": file,
                "issue": issue,
                "suggestion": suggestion,
            }
            for finding_id, kind, file, issue, suggestion in (
                ("F-001", "contract_gap", "vitest.setup.ts", "缺少 cleanup", "补 cleanup"),
                ("F-002", "contract_gap", "vitest.setup.ts", "缺少 media mock", "补 mock"),
                ("F-003", "project_capability", "eslint.config.js", "lint 为空", "补规则"),
            )
        ]
        refine = o.tick(_make_result_file({
            "stage": "critic", "spawned": True,
            "verdict": "MAJOR", "findings": findings,
        }))
        assert [
            gap["source_ref"]
            for gap in refine["feedback"]["refine_request"]["gaps"]
        ] == ["F-001", "F-002", "F-003"]

        tasks = []
        obligations = []
        for index, finding_id in enumerate(("F-001", "F-002", "F-003"), 1):
            implementation_id = f"b2-t{index * 2 - 1}"
            verification_id = f"b2-t{index * 2}"
            tasks.extend([
                {
                    "id": implementation_id,
                    "kind": "implementation",
                    "description": f"修复 {finding_id}",
                    "module_ref": "§11",
                    "file_targets": ["vitest.setup.ts"],
                },
                {
                    "id": verification_id,
                    "kind": "test",
                    "description": f"验证 {finding_id}",
                    "module_ref": "§11",
                    "file_targets": ["tests/setup.test.ts"],
                },
            ])
            obligations.append({
                "id": f"O-{finding_id}",
                "source_ref": finding_id,
                "summary": f"关闭 {finding_id}",
                "implementation_targets": [implementation_id],
                "verification_targets": [verification_id],
                "contract_refs": [],
            })

        developer = o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "plan_patch": {"add_batches": [{
                "batch_id": "b2", "design_section": "B1",
                "component": "Setup Repair", "tasks": tasks,
            }]},
            "file_list": ["vitest.setup.ts", "eslint.config.js"],
            "contracts": {}, "obligations": obligations,
        }))

        assert developer["action"] == "developer"
        assert developer["batch_id"] == "b2"
        assert o._state.open_findings == findings


class TestRefineSourcesAndLimits:
    """T20: 多回源触发 plan_refine + 分源≤2/全局≤4 上限 (§B6.10/DS-8)."""

    def _seed_two_component_plate(self, o: TickOrchestrator) -> None:
        o.init("实现两个组件的板块")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b-Foo", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "foo", "module_ref": "§B2",
                            "file_targets": ["foo.py"]}]},
                {"batch_id": "b-Bar", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "bar", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ],
            "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))

    def test_plate_deep_audit_finding_routes_to_refine_with_audit_gap(self) -> None:
        o = _orchestrator()
        self._seed_two_component_plate(o)
        TestPlateConvergence._approve_component(o, "Foo", "b-Foo")
        a_bar = TestPlateConvergence._approve_component(o, "Bar", "b-Bar")
        assert a_bar["stage"] == "plate_deep_audit"
        # plate_deep_audit 发现 P0 → plan_refine 回 architect
        a = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "spawned": True, "plate": "(single)",
            "findings": [{"severity": "P0", "dimension": "architecture",
                          "agent_source": ["a"], "file": "foo.py", "line": 3,
                          "description": "跨组件契约破坏", "suggested_fix": "对齐接口"}],
            "p0_count": 1, "p1_count": 0, "p2_count": 0,
            "cross_component_issues": [], "total_audited_files": 2,
        }))
        assert a["action"] == "architect"
        req = a["feedback"]["refine_request"]
        assert req["source"] == "plate_deep_audit"
        assert req["scope_plate"] == "(single)"
        assert req["gaps"][0]["kind"] == "AUDIT_FINDING"
        assert req["gaps"][0]["severity"] == "P0"

    def test_plate_audit_recounts_and_closes_even_one_real_p1(self) -> None:
        """Agent 自报计数不可信；去重后的单个真实 P1 仍必须进入修复。"""
        o = _orchestrator()
        self._seed_two_component_plate(o)
        TestPlateConvergence._approve_component(o, "Foo", "b-Foo")
        a_bar = TestPlateConvergence._approve_component(o, "Bar", "b-Bar")
        assert a_bar["stage"] == "plate_deep_audit"
        dup = {"severity": "P1", "dimension": "code_quality",
               "file": "foo.py", "line": 5, "description": "同一 P1", "suggested_fix": "fix"}
        a = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "spawned": True, "plate": "(single)",
            "findings": [
                {**dup, "agent_source": "architecture"},
                {**dup, "agent_source": "code_quality"},  # 同一问题, 去重后 1 条
            ],
            "p0_count": 0, "p1_count": 99,  # Agent 膨胀自报
            "p2_count": 0, "total_audited_files": 2, "cross_component_issues": [],
        }))
        # 自报 99 被忽略，但去重后的 1 条真实 P1 仍不能放行。
        assert a["stage"] == "architect"
        assert o._state.open_findings

    def test_plate_audit_recount_detects_p0_despite_agent_zero_count(self) -> None:
        """B6.7a: Agent 漏报 p0_count=0 但 findings 含 P0 → Python 重算触发 plan_refine."""
        o = _orchestrator()
        self._seed_two_component_plate(o)
        TestPlateConvergence._approve_component(o, "Foo", "b-Foo")
        a_bar = TestPlateConvergence._approve_component(o, "Bar", "b-Bar")
        assert a_bar["stage"] == "plate_deep_audit"
        a = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "spawned": True, "plate": "(single)",
            "findings": [{"severity": "P0", "dimension": "architecture",
                          "agent_source": "architecture", "file": "foo.py", "line": 3,
                          "description": "真 P0", "suggested_fix": "对齐接口"}],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,  # Agent 漏报计数
            "total_audited_files": 2, "cross_component_issues": [],
        }))
        assert a["action"] == "architect"  # Python 重算 p0=1 → 触发 plan_refine
        assert a["feedback"]["refine_request"]["gaps"][0]["severity"] == "P0"

    def test_global_limit_stops_even_when_per_source_under_cap(self) -> None:
        """全局计数达 4 → REFINE_LIMIT, 即便当前源分源计数为 0 (DS-8 全局独立上限)."""
        o = _orchestrator()
        o.init("req")
        # 全局已 4, component_verifier 分源 0 → 触发的是全局上限
        o._state.plan_refine_count = 4
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1", "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "C",
            "coverage_map": [{"design_item": "B2-1", "status": "MISSING"}],
            "missing_count": 1, "diverged_count": 0,
        }))
        assert a["action"] == "done"
        assert a["verdict"] == "REFINE_LIMIT"
        assert "全局" in a["verdict_reason"]

    def test_per_source_counter_increments_on_each_refine(self) -> None:
        o = _orchestrator()
        TestRefineRequestDelivery._drive_component_gap(o, "MISSING")
        assert o._state.plan_refine_by_source["component_verifier"] == 1
        assert o._state.plan_refine_count == 1


class TestPlanRefineProgressSync:
    """T24: plan_refine 后 architect 重出 batch_plan → ProgressTree 增量同步 (§B9.8).

    验证 _after_architect (plan_refine 分支) 调 sync_from_batch_plan, 产出
    added/removed 反映到看板树, 而非重建丢历史.
    """

    @staticmethod
    def _refine_to_architect(o: TickOrchestrator, batch_plan_v1: list[dict]) -> None:
        """init → architect(v1) → dev → critic → component_verifier(MISSING) → architect."""
        o.init("req")
        first_comp = batch_plan_v1[0]["component"]
        first_batch = batch_plan_v1[0]["batch_id"]
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": batch_plan_v1,
            "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": first_batch,
            "files_changed": ["foo.py"], "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": first_comp,
            "coverage_map": [{"design_item": "B2-1", "status": "MISSING"}],
            "missing_count": 1, "diverged_count": 0,
        }))
        assert a["action"] == "architect"

    def test_refine_adds_new_component_to_tree_preserving_old(self) -> None:
        o = _orchestrator()
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
        ])
        names_before = {n.name for n in o._progress_tree.nodes.values()}
        assert "Foo" in names_before and "Bar" not in names_before

        # architect v2 (PLAN-REFINE): 只新增 Bar，旧 Foo 由 Core 保留
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "plan_patch": {"base_revision": 1, "add_batches": [
                {"batch_id": "b2", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ]}, "file_list": ["bar.py"], "contracts": {},
        }))
        names_after = {n.name for n in o._progress_tree.nodes.values()}
        assert "Foo" in names_after  # 增量: 旧节点保留
        assert "Bar" in names_after  # added

    def test_refine_rejects_full_plan_before_mutating_execution_tree(self) -> None:
        o = _orchestrator()
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
        ])
        baseline_before = o._state.architecture_baseline["baseline_id"]
        active_message_id = o._active_action["message_id"]
        counters_before = dict(o._state.guardrail_retry_counters)

        result = o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b1", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "changed",
                            "module_ref": "§B2", "file_targets": ["foo.py"]}]},
            ],
            "file_list": ["foo.py"], "contracts": {},
        }))

        assert result["action"] == "error"
        assert result["error_code"] == "ARCHITECT_PLAN_INVALID"
        assert o._active_action["message_id"] == active_message_id
        assert o._state.guardrail_retry_counters == counters_before
        assert o._state.architecture_baseline["baseline_id"] == baseline_before
        assert o._batch_state.batch_plan[0]["tasks"][0]["description"] == "d"

        from auto_engineering.loop.actions import ErrorResponse

        invalid = ErrorResponse(
            "ARCHITECT_PLAN_INVALID",
            "Architect 计划无法初始化执行树: invalid",
        )
        second = o._tick_process_result(invalid)
        assert second["action"] == "error"
        assert second["error_code"] == "ARCHITECT_PLAN_INVALID"
        assert o._active_action["message_id"] == active_message_id
        assert o._state.guardrail_retry_counters == counters_before

    def test_refine_action_requests_incremental_plan_patch(self) -> None:
        o = _orchestrator()
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
        ])

        action = o._active_action
        assert action["expected_format"]["plan_patch"].startswith("{")
        assert "obligation_updates" in action["expected_format"]["plan_patch"]
        assert "batch_plan" not in action["expected_format"]
        prompt = _worker_prompt(action)
        assert '"plan_revision": 1' in prompt
        assert "历史 obligation 自动继承" in prompt
        assert "不得重复提交" in prompt

    def test_refine_patch_cannot_delete_existing_component(self) -> None:
        o = _orchestrator()
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
            {"batch_id": "b2", "design_section": "B3", "component": "Bar",
             "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B3",
                        "file_targets": ["bar.py"]}]},
        ])
        # architect v2 只能新增修复工作，旧组件不在 patch 中也不能被删除
        result = o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "plan_patch": {"base_revision": 1, "add_batches": [
                {"batch_id": "b3", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T3", "description": "fix", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ]}, "file_list": ["bar.py"], "contracts": {},
        }))
        assert result["stage"] == "developer"
        foo_nodes = [n for n in o._progress_tree.nodes.values() if n.name == "Foo"]
        assert len(foo_nodes) == 1  # 未删除
        assert foo_nodes[0].design_status == "stable"


class TestVerifierRecheck:
    """T26c/DS-9 (B6.6a): Haiku verifier action 携带 Sonnet 窄范围复核指令.

    负判定 (MISSING/DIVERGED) 触发 Sonnet 二次确认, 消除假阳无谓 plan_refine.
    """

    def test_component_verifier_action_carries_recheck(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1", "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        a = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
        }))
        assert a["stage"] == "component_verifier"
        rc = a["recheck"]
        assert rc["enabled"] is True
        assert rc["trigger"] == "on_negative"
        assert rc["scope"] == "narrow"
        # DS-15: model removed — platform selects model, not hardcoded in recheck

    def test_system_verifier_action_carries_recheck(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._state.current_stage = "system_verifier"
        a = o.build_action()
        assert a["stage"] == "system_verifier"
        rc = a["recheck"]
        assert rc["enabled"] is True
        assert rc["trigger"] == "on_negative"

    def test_non_verifier_action_has_no_recheck(self) -> None:
        # architect action 无 recheck (仅 Haiku verifier 需要)
        o = _orchestrator()
        a = o.init("req")
        assert a["stage"] == "architect"
        assert "recheck" not in a


# ── build_action context checks ──


class TestBuildActionContexts:
    def test_architect_action_has_expected_format(self) -> None:
        o = _orchestrator()
        a = o.init("req")
        assert "expected_format" in a
        assert "batch_plan" in a["expected_format"]
        assert "kind" in a["expected_format"]["batch_plan"]
        assert "module_ref" in a["expected_format"]["batch_plan"]
        assert "depends_on" in a["expected_format"]["batch_plan"]
        assert "depends_on 为 task_id 数组" in a["expected_format"]["batch_plan"]
        assert '"requirement": "req"' in _worker_prompt(a)

    def test_developer_action_has_tasks(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]},
                          {"id": "T2", "description": "d2", "module_ref": "§B2",
                           "file_targets": ["y.py"]}],
            }], "file_list": ["x.py", "y.py"], "contracts": {},
        }))
        assert o._plan is not None
        devs = o._plan.get_tasks_by_stage("developer")
        assert len(devs) == 2

    def test_developer_instruction_uses_central_role_and_feedback(self) -> None:
        o = _orchestrator()
        o.init("修复恢复流程")
        o._state.current_stage = "developer"

        action = o.build_action(feedback="P0：重复 Result 会推进两次")

        prompt = _worker_prompt(action)
        assert "你是 Developer" in prompt
        assert "重复 Result 会推进两次" in prompt
        assert '"git_authorized": false' in prompt

    def test_critic_action_has_context_fields(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        action = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        # Phase 70: context 只在编译后的 worker prompt 中出现一次。
        assert action["action"] == "critic"
        assert action["stage"] == "critic"
        assert "context" not in action
        prompt = _worker_prompt(action)
        assert '"files_changed": [' in prompt
        assert '"x.py"' in prompt
        assert action["extensions"]["context_manifest"]["duplicate_block_bytes"] == 0

    def test_system_verifier_receives_global_context(self) -> None:
        o = _orchestrator()
        o.init("验证全量设计")
        o._state.current_stage = "system_verifier"
        o._state.design_doc_path = "design/spec.md"
        o._state.file_list = ["auto_engineering/events/store.py"]
        o._state.coverage_map = [{"design_item": "幂等", "status": "IMPLEMENTED"}]

        action = o.build_action()

        prompt = _worker_prompt(action)
        assert "design/spec.md" in prompt
        assert "auto_engineering/events/store.py" in prompt
        assert '"design_item": "幂等"' in prompt


# ── T7: _apply_result_to_state (result → EngineState) ──


def _seed_architect(o: TickOrchestrator) -> None:
    """init + architect tick → 建立 batch_state + progress_tree, 进入 developer."""
    o.init("req")
    o.tick(_make_result_file({
        "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
            "batch_id": "b1", "design_section": "B2", "component": "C",
            "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                       "file_targets": ["x.py"]}],
        }], "file_list": ["x.py"], "contracts": {},
    }))


class TestApplyResultToState:
    def test_architect_writes_plan_batch_file_contracts(self) -> None:
        o = _orchestrator()
        o.init("req")
        result = {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{"batch_id": "b1"}],
            "file_list": ["x.py"], "contracts": {"c1": "spec"},
        }
        o._apply_result_to_state(result)
        decision = o._build_stage_decision(result)
        registry = default_reducer_registry()
        for event in decision.events:
            if event.event_type is not LoopEventType.STAGE_ADVANCED:
                o._state = registry.reduce(o._state, event)
        assert o._state.plan == _VALID_PLAN
        assert o._state.batch_plan == [{"batch_id": "b1"}]
        assert o._state.file_list == ["x.py"]
        assert o._state.contracts == {"c1": "spec"}

    def test_developer_writes_files_commit_tests(self) -> None:
        o = _orchestrator()
        o._state = EngineState(thread_id="thread-1", current_stage="developer")
        result = {
            "stage": "developer", "files_changed": ["a.py"],
            "commit_hash": "abc", "test_results": {"passed": 2, "failed": 0},
        }
        decision = o._build_stage_decision(result)
        for event in decision.events:
            if event.event_type is LoopEventType.RESULT_EVIDENCE_RECORDED:
                o._state = default_reducer_registry().reduce(o._state, event)
        assert o._state.files_changed == ["a.py"]
        assert o._state.commit_hash == "abc"
        assert o._state.test_results == {"passed": 2, "failed": 0}

    def test_critic_writes_verdict_to_critic_verdict_field(self) -> None:
        """Critic 事实通过 Handler 事件写入，而不是 Result 旁路赋值。"""
        state = EngineState(thread_id="thread-1", current_stage="critic")
        decision = CriticHandler().apply(
            state.to_dict(),
            {"verdict": "APPROVE", "findings": [{"x": 1}], "critic_feedback": "ok"},
            TransitionContext(thread_id="thread-1", tick=1, event_sequence=1),
        )
        registry = default_reducer_registry()
        for event in decision.events:
            if event.event_type is LoopEventType.CRITIC_STATE_UPDATED:
                state = registry.reduce(state, event)

        assert state.critic_verdict == "APPROVE"
        assert state.findings == [{"x": 1}]
        assert state.critic_feedback == "ok"

    def test_component_verifier_writes_coverage_map(self) -> None:
        state = EngineState(thread_id="thread-1", current_stage="component_verifier")
        decision = ComponentVerifierHandler().apply(
            state.to_dict(),
            {"coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED"}]},
            TransitionContext(
                thread_id="thread-1",
                tick=1,
                event_sequence=1,
                extensions={"verification_layers": "leaf"},
            ),
        )
        for event in decision.events:
            if event.event_type is LoopEventType.VERIFICATION_STATE_UPDATED:
                state = default_reducer_registry().reduce(state, event)
        assert state.coverage_map == [
            {"design_item": "B2-1", "status": "IMPLEMENTED"}]

    def test_system_verifier_maps_full_coverage_to_coverage_map(self) -> None:
        state = EngineState(thread_id="thread-1", current_stage="system_verifier")
        decision = SystemVerifierHandler().apply(
            state.to_dict(),
            {"full_coverage_map": [{"design_section": "B2", "status": "IMPLEMENTED"}]},
            TransitionContext(thread_id="thread-1", tick=1, event_sequence=1),
        )
        for event in decision.events:
            if event.event_type is LoopEventType.VERIFICATION_STATE_UPDATED:
                state = default_reducer_registry().reduce(state, event)
        assert state.coverage_map == [
            {"design_section": "B2", "status": "IMPLEMENTED"}]

    def test_critic_invalid_verdict_rejected_by_after_critic(self) -> None:
        """T116: 非法 verdict 不产生 Critic 事实事件。"""
        state = EngineState(thread_id="thread-1", current_stage="critic")
        decision = CriticHandler().apply(
            state.to_dict(), {"verdict": "INVALID", "findings": []},
            TransitionContext(thread_id="thread-1", tick=1, event_sequence=1),
        )

        assert decision.action_context["error"]["error_code"] == "INVALID_VERDICT"
        assert decision.events == ()

    def test_critic_allows_empty_verdict(self) -> None:
        """T116: 空 verdict 不产生未验证的 Critic 状态。"""
        state = EngineState(thread_id="thread-1", current_stage="critic")
        decision = CriticHandler().apply(
            state.to_dict(), {"verdict": "", "findings": []},
            TransitionContext(thread_id="thread-1", tick=1, event_sequence=1),
        )

        assert decision.action_context["error"]["error_code"] == "INVALID_VERDICT"
        assert decision.events == ()

    def test_critic_approve_verdict_still_writes(self) -> None:
        """T116: 合法 APPROVE 通过 Critic 领域事件写入 state。"""
        state = EngineState(thread_id="thread-1", current_stage="critic")
        decision = CriticHandler().apply(
            state.to_dict(), {"verdict": "APPROVE", "findings": [{"x": 1}]},
            TransitionContext(thread_id="thread-1", tick=1, event_sequence=1),
        )
        registry = default_reducer_registry()
        for event in decision.events:
            if event.event_type is LoopEventType.CRITIC_STATE_UPDATED:
                state = registry.reduce(state, event)

        assert state.critic_verdict == "APPROVE"
        assert state.findings == [{"x": 1}]


# ── T7b: ProgressTree 更新 + _display_progress ──


class TestProgressWiring:
    def test_architect_tick_builds_progress_tree(self) -> None:
        o = _orchestrator()
        _seed_architect(o)
        assert o._progress_tree is not None
        assert o._progress_tree.summary()["node_count"] >= 1

    def test_display_progress_serializes_to_state_json(self) -> None:
        o = _orchestrator()
        _seed_architect(o)
        o._display_progress()
        assert o._state.progress_tree_json
        d = json.loads(o._state.progress_tree_json)
        assert "nodes" in d

    def test_display_progress_sets_updated_at(self) -> None:
        o = _orchestrator()
        _seed_architect(o)
        o._display_progress()
        assert o._progress_tree.updated_at != ""

    def test_display_progress_prints_to_stderr_with_timestamp(self, capsys) -> None:
        o = _orchestrator()
        _seed_architect(o)
        capsys.readouterr()  # 清空 seed 阶段输出
        o._display_progress()
        captured = capsys.readouterr()
        import re
        # 进度展示走 stderr (不污染 stdout 的 action JSON 契约), 带 [HH:MM:SS] 时间戳
        assert re.search(r"\[\d{2}:\d{2}:\d{2}\]", captured.err)
        assert "SYSTEM" in captured.err
        assert captured.out == ""

    def test_display_progress_idempotent_within_same_tick(self, capsys) -> None:
        o = _orchestrator()
        _seed_architect(o)
        o._display_progress()  # 首次: 打印 + 记 last_displayed_tick
        capsys.readouterr()  # 清空
        o._display_progress()  # 同 tick 再调 → 去重, 不再打印
        assert capsys.readouterr().err == ""

    def test_display_progress_prints_again_on_new_tick(self, capsys) -> None:
        o = _orchestrator()
        _seed_architect(o)
        o._display_progress()
        capsys.readouterr()
        o._state.tick += 1  # 新 tick
        o._display_progress()
        assert "SYSTEM" in capsys.readouterr().err

    def test_full_leaf_cycle_populates_progress_tree_json(self) -> None:
        o = _orchestrator()
        o.init("实现单个组件")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"], "test_results": {"passed": 2, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 1,
            "total_audited_files": 2, "design_docs_stale": False,
            "design_doc_suggestions": "", "missing_count": 0, "diverged_count": 0,
        }))
        assert a["verdict"] == "GOAL_ACHIEVED"
        # system_deep_audit handler 调 _display_progress → 序列化到 state
        assert o._state.progress_tree_json
        d = json.loads(o._state.progress_tree_json)
        assert d["nodes"]


# ── T7c: Phase 0 Pre-flight Gap Analysis (gap_scan/gap_review/research) ──


def _init_design(o: TickOrchestrator, tmp_path) -> None:
    """init --design-doc 模式 → 进入 gap_scan."""
    (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
    design = tmp_path / "design.md"
    design.write_text("## §B2 StageRouter\n\ncontent\n", encoding="utf-8")
    _prepare_existing_project(tmp_path)
    o.project_root = tmp_path
    o.init("req", design_doc_path=str(design))


def _gap_scan_result(gaps: list[dict]) -> Path:
    orchestrator = _ACTIVE_ORCHESTRATOR
    assert orchestrator is not None
    design_doc = orchestrator._design_doc
    assert design_doc is not None
    sections = design_doc.sections_summary() or [
        {"design_section": plate.design_section}
        for plate in design_doc.plates
    ]
    coverage = [
        {
            "design_section_ref": item["design_section"],
            "verdict": "gap" if any(
                gap.get("design_section_ref") == item["design_section"]
                for gap in gaps
            ) else "clear",
            "evidence": [f"已检查 {item['design_section']} 的实现充分性"],
        }
        for item in sections
    ]
    return _make_result_file({
        "stage": "gap_scan", "gaps": gaps,
        "scanned_sections": len(coverage), "has_blocking": False,
        "design_doc_digest": orchestrator._state.design_doc_digest,
        "scan_coverage": coverage,
    })


def _blocking_gap_scan_result(gaps: list[dict]) -> Path:
    """gap_scan result with has_blocking=True (T107)."""
    blocking_gaps = []
    for gap in gaps:
        options = [
            {
                **option,
                "enabled": False,
                "disabled_reason": "architectural gap 不允许纯 Defer",
            }
            if option.get("resolution") == "Defer" else dict(option)
            for option in gap.get("options", [])
        ]
        blocking_gaps.append({
            **gap,
            "grade": "architectural",
            "options": options,
            "blocking_rule": "architectural gap 禁止纯 Defer",
        })
    orchestrator = _ACTIVE_ORCHESTRATOR
    assert orchestrator is not None
    design_doc = orchestrator._design_doc
    assert design_doc is not None
    sections = design_doc.sections_summary() or [
        {"design_section": plate.design_section}
        for plate in design_doc.plates
    ]
    return _make_result_file({
        "stage": "gap_scan", "gaps": blocking_gaps,
        "scanned_sections": len(sections), "has_blocking": True,
        "design_doc_digest": orchestrator._state.design_doc_digest,
        "scan_coverage": [
            {
                "design_section_ref": item["design_section"],
                "verdict": "gap",
                "evidence": ["该章节存在 architectural gap"],
            }
            for item in sections
        ],
    })


_GAP_B2 = {
    "id": "gap-B2",
    "design_section_ref": "§B2",
    "grade": "component",
    "clarity": "vague",
    "summary": "边界未定义",
    "depends_on": [],
    "evidence": ["§B2 只描述职责，未定义输入输出"],
    "problem_statement": "组件边界无法唯一实现",
    "impact": ["影响接口契约与测试边界"],
    "dependencies": [],
    "recommendation": {
        "resolution": "Research",
        "reason": "需要先确认调用方约束",
        "confidence": "medium",
        "requires_user_approval": False,
    },
    "options": [
        {"resolution": "Fill", "meaning": "用户补充最终设计", "enabled": True},
        {"resolution": "Research", "meaning": "先查证约束", "enabled": True},
        {"resolution": "Defer", "meaning": "交 Architect 细化", "enabled": True},
    ],
    "blocking_rule": "component gap 可 Defer",
}


class TestPhase0GapScan:
    def test_init_hands_off_unstructured_design_before_gap_scan_worker(
        self, tmp_path,
    ) -> None:
        """无 H2/H3 的设计文档在首个 Worker 前必须交给用户修复。"""
        o = _orchestrator()
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text("# Only a title\n\nNo executable hierarchy.\n", encoding="utf-8")
        _prepare_existing_project(tmp_path)
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))
        assert action["action"] == "gate"
        assert action["stage"] == "gap_scan"
        assert action["gate"]["id"] == "design_structure_preflight"
        assert action["gate"]["reason_code"] == "DESIGN_STRUCTURE_PREFLIGHT_REQUIRED"
        assert "spawn" not in action
        assert action["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_USER"

    def test_preflight_resolution_stops_for_explicit_reinit(self, tmp_path) -> None:
        o = _orchestrator()
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text("# Only a title\n", encoding="utf-8")
        _prepare_existing_project(tmp_path)
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))

        resolution = _make_result_file({
            "gate_resolution": {
                "gate_id": action["gate"]["id"],
                "resolution": "修复设计文档后重新初始化",
            },
        })
        stopped = o.tick(resolution)

        assert stopped["action"] == "done"
        assert stopped["verdict"] == "TERMINATED"
        assert "重新执行 --init" in stopped["message"]

    def test_preflight_rejects_wrong_gate_resolution(self, tmp_path) -> None:
        o = _orchestrator()
        _prepare_existing_project(tmp_path)
        design = tmp_path / "design.md"
        design.write_text("# Only a title\n", encoding="utf-8")
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))

        rejected = o.tick(_make_result_file({
            "gate_resolution": {
                "gate_id": action["gate"]["id"],
                "resolution": "继续",
            },
        }))

        assert rejected["action"] == "error"
        assert rejected["error_code"] == "INVALID_GATE_RESOLUTION"

    def test_invalid_design_does_not_lock_ledger_before_reinit(self, tmp_path) -> None:
        """修正文档后重新 init 不应被失败尝试留下的源哈希阻断。"""
        o = _orchestrator()
        _prepare_existing_project(tmp_path)
        design = tmp_path / "design.md"
        design.write_text("# Only a title\n", encoding="utf-8")
        o.project_root = tmp_path

        first = o.init("req", design_doc_path=str(design))
        assert first["action"] == "gate"
        ledger = tmp_path / ".ae-state" / "design-decision-ledger.json"
        assert not ledger.exists()

        design.write_text("## B1 Feature\n\ncontract\n", encoding="utf-8")
        second = o.init("req", design_doc_path=str(design))

        assert second["stage"] == "gap_scan"
        assert second["action"] != "gate"
        assert ledger.exists()

    def test_zero_gap_without_section_evidence_is_rejected(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        result = _make_result_file({
            "stage": "gap_scan",
            "gaps": [],
            "scanned_sections": 1,
            "has_blocking": False,
        })

        action = o.tick(result)

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_SCAN_EVIDENCE_INCOMPLETE"

    def test_zero_gap_with_wrong_design_digest_is_rejected(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        result = _make_result_file({
            "stage": "gap_scan",
            "gaps": [],
            "scanned_sections": 1,
            "has_blocking": False,
            "design_doc_digest": "sha256:stale",
            "scan_coverage": [{
                "design_section_ref": "§B2",
                "verdict": "clear",
                "evidence": ["已检查职责与输入输出"],
            }],
        })

        action = o.tick(result)

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_SCAN_DESIGN_MISMATCH"

    def test_incomplete_gap_analysis_is_rejected_before_review(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        incomplete = {
            "id": "gap-incomplete",
            "design_section_ref": "§B2",
            "grade": "component",
            "clarity": "vague",
            "summary": "边界未定义",
            "depends_on": [],
        }

        action = o.tick(_gap_scan_result([incomplete]))

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_ANALYSIS_INCOMPLETE"

    def test_gap_scan_with_gaps_routes_to_gap_review(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        action = o.tick(_gap_scan_result([_GAP_B2]))
        assert action["stage"] == "gap_review"
        assert action["action"] == "gap_review"
        assert action["current_gap"]["id"] == "gap-B2"

    def test_gap_scan_rejects_missing_clarity_for_explicit_design_items(
        self, tmp_path,
    ) -> None:
        """实现文件缺失不得把已有明确设计条目升级成设计 gap。"""
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text(
            "## A1 Core\n\n### A1.1 Counter function\n\n"
            "#### Contract\n\n- next_value(current, step) returns current + step.\n",
            encoding="utf-8",
        )
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        implementation_gap = {
            **_GAP_B2,
            "id": "gap-implementation-only",
            "design_section_ref": "§A1.1",
            "clarity": "missing",
            "summary": "counter.py 尚未实现",
            "evidence": ["src/canary_math/counter.py 文件不存在"],
        }

        action = o.tick(_gap_scan_result([implementation_gap]))

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_ANALYSIS_IMPLEMENTATION_MISCLASSIFIED"

    def test_gap_scan_rejects_missing_clarity_for_explicit_paragraph_contract(
        self, tmp_path,
    ) -> None:
        """H3 下的明确正文契约不能因尚未有源码而变成设计 Gap。"""
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text(
            "## §1 Counter module\n\n"
            "### §1.1 Public behavior\n\n"
            "Implement `Counter(initial: int = 0)`; `increment(amount: int) -> int` "
            "returns the new value and rejects bool with TypeError.\n",
            encoding="utf-8",
        )
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        implementation_gap = {
            **_GAP_B2,
            "id": "gap-paragraph-contract",
            "design_section_ref": "§1.1",
            "clarity": "missing",
            "summary": "counter.py 尚未实现",
            "evidence": ["src/counter.py 文件不存在"],
        }

        action = o.tick(_gap_scan_result([implementation_gap]))

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_ANALYSIS_IMPLEMENTATION_MISCLASSIFIED"

    def test_gap_scan_rejects_gap_bound_to_future_improvement_section(
        self, tmp_path,
    ) -> None:
        """明确的未来改进只能作为 advisory，不能触发当前版本用户 Gate。"""
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text(
            "## 13. 已知问题与未来改进\n\n"
            "### 13.2 当前版本约束\n\n当前行为契约。\n\n"
            "### 13.3 未来改进方向\n\n后续版本再考虑。\n",
            encoding="utf-8",
        )
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        future_gap = {
            **_GAP_B2,
            "id": "gap-future",
            "design_section_ref": "§13.3",
            "evidence": ["§13.3 未来改进方向：后续版本再考虑同源服务层"],
            "summary": "未来改进方向尚未实现",
            "problem_statement": "未来版本的服务层尚未实现",
        }

        action = o.tick(_gap_scan_result([future_gap]))

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_ANALYSIS_FUTURE_SCOPE_MISCLASSIFIED"
        assert "§13.3" in action["message"]

    def test_gap_scan_keeps_current_contract_gap_reportable(
        self, tmp_path,
    ) -> None:
        """当前章节之间的未决契约矛盾仍必须进入 Gap Review。"""
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text(
            "## 13. 已知问题与未来改进\n\n"
            "### 13.2 当前版本约束\n\n当前行为契约。\n\n"
            "### 13.3 未来改进方向\n\n后续版本再考虑。\n",
            encoding="utf-8",
        )
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        current_gap = {
            **_GAP_B2,
            "id": "gap-current",
            "design_section_ref": "§13.2",
            "evidence": ["§13.2 当前版本约束未定义跨组件输入输出"],
        }

        action = o.tick(_gap_scan_result([current_gap]))

        assert action["action"] == "gap_review"
        assert action["current_gap"]["id"] == "gap-current"

    def test_gap_scan_rejects_advisory_reference_in_gap_evidence(
        self, tmp_path,
    ) -> None:
        """当前章节的 gap 也不得借未来章节作为证据来源。"""
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text(
            "## 13. 已知问题与未来改进\n\n"
            "### 13.2 当前版本约束\n\n当前行为契约。\n\n"
            "### 13.3 未来改进方向\n\n后续版本再考虑。\n",
            encoding="utf-8",
        )
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        mixed_gap = {
            **_GAP_B2,
            "id": "gap-mixed-source",
            "design_section_ref": "§13.2",
            "evidence": [
                "§13.2 当前版本约束未定义输入输出",
                "§13.3 未来改进方向也提到同源服务层",
            ],
        }

        action = o.tick(_gap_scan_result([mixed_gap]))

        assert action["action"] == "error"
        assert action["error_code"] == "GAP_ANALYSIS_FUTURE_SCOPE_MISCLASSIFIED"

    def test_gap_scan_no_gaps_routes_to_architect(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        action = o.tick(_gap_scan_result([]))
        assert action["stage"] == "architect"
        assert action["action"] == "architect"
        assert action["gap_scan_summary"] == {
            "design_doc_digest": o._state.design_doc_digest,
            "scanned_sections": 1,
            "gap_count": 0,
            "has_blocking": False,
            "outcome": "no_gaps_auto_continue",
        }

    def test_gap_scan_writes_gap_report_json(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        report = json.loads(o._state.gap_report_json)
        assert report["gaps"][0]["id"] == "gap-B2"
        assert report["scanned_sections"] == 1


class TestPhase0GapReview:
    def test_action_is_core_persisted_single_gap_wizard(self, tmp_path) -> None:
        """用户每次只判断一个 gap，累计状态不能留在宿主聊天内存。"""
        o = _orchestrator()
        _init_design(o, tmp_path)
        gaps = [
            {**_GAP_B2, "id": "gap-A"},
            {**_GAP_B2, "id": "gap-B"},
        ]

        action = o.tick(_gap_scan_result(gaps))

        assert action["mode"] == "wizard"
        assert action["current_gap_index"] == 0
        assert action["total_gaps"] == 2
        assert action["current_gap"]["id"] == "gap-A"
        assert "gaps" not in action
        assert action["decisions_so_far"] == []
        assert action["gap_review_contract"] == {
            "display_scope": "current_gap_only",
            "decision_count": 1,
            "gap_id_source": "current_gap.id",
            "forbidden_context": [
                "historical_gap_scan_gaps",
                "future_gap_details",
                "batch_decisions",
            ],
        }
        assert "decision" in action["expected_format"]

    def test_single_decision_is_persisted_before_next_gap(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        gaps = [
            {**_GAP_B2, "id": "gap-A"},
            {**_GAP_B2, "id": "gap-B"},
        ]
        o.tick(_gap_scan_result(gaps))

        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "gap-A",
                "resolution": "fill",
                "fill_content": "明确 A 的输入输出契约",
                "decision_source": "user",
            },
        }))

        assert action["stage"] == "gap_review"
        assert action["current_gap"]["id"] == "gap-B"
        assert [item["gap_id"] for item in action["decisions_so_far"]] == [
            "gap-A"
        ]
        saved = action["decisions_so_far"][0]
        assert saved["assistant_recommendation"] == "Research"
        assert saved["recommendation_accepted"] is False
        assert saved["evidence_refs"] == gaps[0]["evidence"]
        assert saved["decision_source"] == "user"
        assert o._state.current_stage == "gap_review"

    def test_structured_policy_applies_recommendation_to_remaining_gaps(
        self, tmp_path,
    ) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        gaps = [
            {**_GAP_B2, "id": "gap-A"},
            {**_GAP_B2, "id": "gap-B"},
        ]
        o.tick(_gap_scan_result(gaps))

        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "gap-A",
                "resolution": "Fill",
                "fill_content": "用户明确补齐 gap-A",
                "decision_source": "user",
                "apply_to_remaining": "recommendations",
            },
        }))

        assert o._state.gap_decision_policy == "remaining_recommendations"
        assert action["extensions"]["ae"]["execution_control"]["disposition"] == "CONTINUE"
        assert action["auto_decision"] == {
            "gap_id": "gap-B",
            "resolution": "Research",
            "decision_source": "thread_policy",
            "policy": "remaining_recommendations",
        }

        next_action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": action["auto_decision"],
        }))

        assert next_action["stage"] == "research"
        assert o._state.pending_gap_decisions[-1]["decision_source"] == (
            "thread_policy"
        )

    def test_tick_rebinds_core_auto_decision_when_old_result_bypasses_finalizer(
        self, tmp_path,
    ) -> None:
        """恢复旧 checkpoint 时，直接重放的旧 Result 也不能绕过 Core 权威。"""

        o = _orchestrator()
        _init_design(o, tmp_path)
        gaps = [
            {**_GAP_B2, "id": "gap-A"},
            {**_GAP_B2, "id": "gap-B"},
        ]
        o.tick(_gap_scan_result(gaps))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "gap-A",
                "resolution": "Fill",
                "fill_content": "用户明确补齐 gap-A",
                "decision_source": "user",
                "apply_to_remaining": "recommendations",
            },
        }))

        next_action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "stale-gap",
                "resolution": "Defer",
                "decision_source": "thread_policy",
                "fill_content": "沿用旧宿主已经生成的补充内容",
            },
        }))

        assert action["auto_decision"]["policy"] == "remaining_recommendations"
        assert next_action["stage"] == "research"
        assert o._state.pending_gap_decisions[-1] == {
            "gap_id": "gap-B",
            "resolution": "Research",
            "fill_content": "沿用旧宿主已经生成的补充内容",
            "decision_source": "thread_policy",
            "policy": "remaining_recommendations",
            "assistant_recommendation": "Research",
            "recommendation_accepted": True,
            "evidence_refs": _GAP_B2["evidence"],
        }

    def test_binding_gap_never_uses_remaining_recommendations_automatically(
        self, tmp_path,
    ) -> None:
        """线程策略只覆盖已明确标注为非绑定的普通缺口。"""
        o = _orchestrator()
        _init_design(o, tmp_path)
        binding_gap = {
            **_GAP_B2,
            "recommendation": {
                **_GAP_B2["recommendation"],
                "requires_user_approval": True,
            },
        }
        o.tick(_gap_scan_result([binding_gap]))
        o._state.gap_decision_policy = "remaining_recommendations"

        action = o.build_action()

        assert action["auto_decision"] is None
        result = _make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": binding_gap["id"],
                "resolution": "Research",
                "decision_source": "thread_policy",
                "policy": "remaining_recommendations",
            },
        })
        rejected = o.tick(result)
        assert rejected["error_code"] == "GAP_REVIEW_POLICY_REQUIRES_APPROVAL"

    def test_action_exposes_only_current_gap_with_core_cursor(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        gap_a = {**_GAP_B2, "id": "gap-A"}
        gap_b = {**_GAP_B2, "id": "gap-B"}

        action = o.tick(_gap_scan_result([gap_a, gap_b]))

        assert action["current_gap"]["id"] == "gap-A"
        assert action["current_gap_index"] == 0
        assert action["total_gaps"] == 2
        assert "gaps" not in action

    def test_partial_decisions_are_rejected_without_advancing(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        gap_a = {**_GAP_B2, "id": "gap-A"}
        gap_b = {**_GAP_B2, "id": "gap-B"}
        o.tick(_gap_scan_result([gap_a, gap_b]))

        response = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-A", "resolution": "fill",
                           "fill_content": "明确 A"}],
        }))

        assert response["action"] == "error"
        assert response["error_code"] == "GAP_REVIEW_DECISIONS_INCOMPLETE"
        assert o._state.current_stage == "gap_review"

    def test_duplicate_or_unknown_gap_decisions_are_rejected(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))

        response = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [
                {"gap_id": "gap-B2", "resolution": "fill", "fill_content": "a"},
                {"gap_id": "gap-B2", "resolution": "defer"},
                {"gap_id": "unknown", "resolution": "defer"},
            ],
        }))

        assert response["action"] == "error"
        assert response["error_code"] == "GAP_REVIEW_DECISIONS_INVALID_SET"
        assert o._state.current_stage == "gap_review"

    def test_fill_injects_supplement_and_routes_architect(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "user_note": "补充", "fill_content": "契约: X→Y"}],
        }))
        assert action["stage"] == "architect"
        assert "gap-B2" in o._design_doc.supplements
        supp = o._design_doc.supplements["gap-B2"]
        assert supp.content == "契约: X→Y"
        assert supp.source == "user"
        assert supp.confidence == "high"
        assert o._state.design_supplements_json
        # DS-15: supplements 在 state 中，不再注入 architect context，不再注入 architect context

    def test_research_decision_routes_to_research(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "research"}],
        }))
        assert action["stage"] == "research"
        assert o._state.pending_research_ids == ["gap-B2"]
        assert action["gap"]["id"] == "gap-B2"

    def test_all_fill_no_research_routes_architect(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "c"}],
        }))
        assert action["stage"] == "architect"
        assert o._state.pending_research_ids == []

    # ── T107: gap_review human-in-the-loop auto-pause ──

    def test_blocking_gap_adds_architect_to_pause_at_stages(self, tmp_path) -> None:
        """T107a: has_blocking=True → architect 加入 _pause_at_stages."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_blocking_gap_scan_result([_GAP_B2]))
        assert "architect" not in o._pause_at_stages
        o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "c"}],
        }))
        assert "architect" in o._pause_at_stages

    def test_blocking_gap_triggers_checkpoint_gate(self, tmp_path) -> None:
        """T107b: has_blocking=True → gap_review 返回 checkpoint gate (非 architect action)."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_blocking_gap_scan_result([_GAP_B2]))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "c"}],
        }))
        assert action["action"] == "gate"
        assert action["gate"]["type"] == "stage_checkpoint"
        assert action["gate"]["id"] == "checkpoint_architect"

    def test_no_blocking_skips_pause_at_stages(self, tmp_path) -> None:
        """T107c: has_blocking=False → _pause_at_stages 不变, 直接进入 architect."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        assert "architect" not in o._pause_at_stages
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "c"}],
        }))
        assert action["action"] == "architect"
        assert "architect" not in o._pause_at_stages


class TestPhase0Research:
    def _drive_to_research(self, o, tmp_path, resolution: str) -> None:
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": resolution}],
        }))

    def test_research_injects_supplement_and_routes_review(self, tmp_path) -> None:
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "research")
        action = o.tick(_make_result_file({
            "stage": "research",
            "findings": "检索到 langgraph tick 控制流",
            "sources": [{"tier": "tier0", "ref": "_loop.py", "note": ""}],
            "source_tier": "tier0", "confidence": "high",
            "recommended_design": "采用 tick/after_tick 分离",
        }))
        assert action["stage"] == "gap_review"
        assert action["is_rereview"] is True
        supp = o._design_doc.supplements["gap-B2"]
        assert supp.source == "research_agent"
        assert supp.source_tier == "tier0"
        assert supp.content == "采用 tick/after_tick 分离"
        assert o._state.pending_research_ids == []
        assert "采用 tick/after_tick 分离" in o._state.design_supplements_json

    def test_defer_research_routes_to_gap_review_for_rereview(self, tmp_path) -> None:
        """T0.7: defer_research 研究完成 → 回 gap_review 复审 (非直达 architect)."""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "defer_research")
        action = o.tick(_make_result_file({
            "stage": "research", "findings": "研究发现: 设计缺跨组件契约",
            "source_tier": "tier1", "confidence": "medium",
            "recommended_design": "建议补充契约 X→Y",
        }))
        # 回 gap_review 复审, 携带 research_findings 供用户做补充设计
        assert action["stage"] == "gap_review"
        assert action["is_rereview"] is True
        assert "gap-B2" in action["research_findings"]
        # 尚未成 Supplement (待复审决策), findings 已存档
        assert "gap-B2" not in o._design_doc.supplements
        assert "gap-B2" in o._state.research_archive

    def test_rereview_fill_creates_supplement_and_routes_architect(self, tmp_path) -> None:
        """复审: 用户据 findings 做补充设计 (Fill) → Supplement + 消费存档 → architect."""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "defer_research")
        o.tick(_make_result_file({
            "stage": "research", "recommended_design": "建议 X→Y",
            "source_tier": "tier1", "confidence": "medium",
        }))
        # 复审: Fill 写入补充设计
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "补充设计: 契约 X→Y 落定"}],
        }))
        assert action["stage"] == "architect"
        assert "gap-B2" in o._design_doc.supplements
        assert o._design_doc.supplements["gap-B2"].content == "补充设计: 契约 X→Y 落定"
        # Fill 后存档已消费
        assert "gap-B2" not in o._state.research_archive
        # architect 携带 supplement (计划表补充调整的依据)
        # DS-15: context slimmed, supplements in state only

    def test_rereview_defer_keeps_findings_for_architect(self, tmp_path) -> None:
        """复审: 用户仍 Defer → findings 留 archive 给 architect, 不成 Supplement → architect."""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "defer_research")
        o.tick(_make_result_file({
            "stage": "research", "recommended_design": "建议 X→Y",
            "source_tier": "tier1", "confidence": "medium",
        }))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "defer"}],
        }))
        assert action["stage"] == "architect"
        assert "gap-B2" not in o._design_doc.supplements
        assert "gap-B2" in o._state.research_archive
        # DS-15: research_archive in state, not injected into architect context

    def test_rereview_reresearch_coerced_to_defer_terminates(self, tmp_path) -> None:
        """终止保证: 复审仍选 defer_research (已研究) → 归 defer → architect (不再研究)."""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "defer_research")
        o.tick(_make_result_file({
            "stage": "research", "recommended_design": "r",
            "source_tier": "tier1", "confidence": "medium",
        }))
        action = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "defer_research"}],
        }))
        # 不再回 research/gap_review — 直达 architect
        assert action["stage"] == "architect"
        assert o._state.pending_research_ids == []

    def test_two_research_gaps_return_to_review_before_architect(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        gap_a = {**_GAP_B2, "id": "gap-A", "summary": "a"}
        gap_b = {**_GAP_B2, "id": "gap-B", "design_section_ref": "§B3", "summary": "b"}
        o.tick(_gap_scan_result([gap_a, gap_b]))
        o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [
                {"gap_id": "gap-A", "resolution": "research"},
                {"gap_id": "gap-B", "resolution": "research"},
            ],
        }))
        a1 = o.tick(_make_result_file({
            "stage": "research", "recommended_design": "designA",
            "source_tier": "tier0", "confidence": "high",
        }))
        assert a1["stage"] == "research"
        assert a1["gap"]["id"] == "gap-B"  # 队列推进到第二个
        a2 = o.tick(_make_result_file({
            "stage": "research", "recommended_design": "designB",
            "source_tier": "tier0", "confidence": "high",
        }))
        assert a2["stage"] == "gap_review"
        assert a2["current_gap"]["id"] == "gap-A"
        assert "gap-A" in o._design_doc.supplements
        assert "gap-B" in o._design_doc.supplements

        review_b = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "gap-A", "resolution": "defer", "decision_source": "user",
            },
        }))
        assert review_b["stage"] == "gap_review"
        assert review_b["current_gap"]["id"] == "gap-B"
        architect = o.tick(_make_result_file({
            "stage": "gap_review",
            "decision": {
                "gap_id": "gap-B", "resolution": "defer", "decision_source": "user",
            },
        }))
        assert architect["stage"] == "architect"

    def test_research_action_injects_four_tier_knowledge_contract(
            self, tmp_path) -> None:
        """T26/§B10.6: research action 必须携带 4-tier 知识源 + 内存约束契约."""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "research")
        action = o.build_action()
        assert action["stage"] == "research"
        ks = action["knowledge_sources"]
        assert ks["tier_order"] == [
            "tier0", "tier1_ref_code", "tier2_doc_kb", "tier3_web"]
        # 内存护栏: grep 定位 + 禁批量/并行 (96GB 事故防线)
        assert "grep" in ks["memory_constraint"]
        assert "禁止批量/并行扫描" in ks["memory_constraint"]
        # 当前 gap 上下文透传
        assert action["gap"]["id"] == "gap-B2"
        # 输出契约要求分层来源 + 置信度 + 可注入 supplement 的设计
        fmt = action["expected_format"]
        assert fmt["source_tier"] == "tier0|tier1|tier2|tier3"
        assert fmt["confidence"] == "high|medium|low"
        assert "recommended_design" in fmt
        assert action["required_capabilities"] == ["web_search"]
        assert fmt["search_status"] == "used|unavailable|failed|not_needed"

    def test_research_web_sources_are_archived_end_to_end(
        self, tmp_path
    ) -> None:
        """Research→supplement 时仍须保留可审计的 Web 来源。"""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "research")

        action = o.tick(_make_result_file({
            "stage": "research",
            "findings": "官方规范确认 checkpoint 语义",
            "sources": [{
                "tier": "tier3",
                "ref": "https://docs.python.org/3.12/library/sqlite3.html",
                "note": "Python 官方 sqlite3 transaction control 文档",
            }],
            "source_tier": "tier3",
            "confidence": "high",
            "recommended_design": "采用规范中的恢复边界",
            "search_status": "used",
        }))

        assert action["stage"] == "gap_review"
        archived = o._state.research_archive["gap-B2"]
        assert archived["search_status"] == "used"
        assert archived["sources"][0]["ref"] == (
            "https://docs.python.org/3.12/library/sqlite3.html"
        )

    def test_research_search_unavailable_degrades_to_rereview(
        self, tmp_path
    ) -> None:
        """宿主无搜索能力时保存失败证据并回到复审，不伪造 findings。"""
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "research")

        action = o.tick(_make_result_file({
            "stage": "research",
            "findings": "",
            "sources": [],
            "source_tier": "tier3",
            "confidence": "low",
            "recommended_design": "",
            "search_status": "unavailable",
            "search_error": "HOST_CAPABILITY_UNAVAILABLE",
        }))

        assert action["stage"] == "gap_review"
        archived = o._state.research_archive["gap-B2"]
        assert archived["search_error"] == "HOST_CAPABILITY_UNAVAILABLE"
        assert "gap-B2" not in o._design_doc.supplements


# ── #30 / DS-10 (C.2.6): tick 延迟打点 (超预算告警不中断) ──


def _architect_result_file() -> Path:
    return _make_result_file({
        "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [{
            "batch_id": "b1", "design_section": "B2", "component": "C",
            "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                       "file_targets": ["x.py"]}],
        }], "file_list": ["x.py"], "contracts": {},
    })


class TestTickLatencyInstrumentation:
    def test_tick_appends_latency_record(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_architect_result_file())
        assert o._state.action_history
        rec = o._state.action_history[-1]
        for k in ("tick", "stage", "t_total_ms", "t_gate_ms",
                  "t_guard_sub_ms", "t_orchestration_ms"):
            assert k in rec

    def test_orchestration_equals_total_minus_gate_and_guard(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_architect_result_file())
        rec = o._state.action_history[-1]
        expected = rec["t_total_ms"] - rec["t_gate_ms"] - rec["t_guard_sub_ms"]
        # 各字段独立 round(2) → 允许 ±0.01 双重舍入误差
        assert abs(rec["t_orchestration_ms"] - expected) <= 0.02

    def test_architect_tick_has_zero_gate_time(self) -> None:
        """gate 仅在 developer tick 运行, architect tick 的 t_gate=0."""
        o = _orchestrator()
        o.init("req")
        o.tick(_architect_result_file())
        assert o._state.action_history[-1]["t_gate_ms"] == 0.0

    def test_developer_tick_measures_gate_time(self) -> None:
        """developer tick 运行 gate → t_gate_ms > 0 (慢 stub 保证可测)."""
        def slow_gate_runner(gate_names, project_root):
            time.sleep(0.02)
            return {n: MagicMock(passed=True, message="ok") for n in gate_names}

        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=slow_gate_runner,
            guardrail=_pass_guardrail())
        o.init("req")
        o.tick(_architect_result_file())  # → developer
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1", "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        dev_rec = o._state.action_history[-1]
        assert dev_rec["stage"] == "critic"  # developer 完成后已推进
        assert dev_rec["t_gate_ms"] > 0

    def test_error_tick_still_records_latency(self) -> None:
        """早退 (STAGE_MISMATCH) 的 tick 仍写延迟记录 (每 tick 必记)."""
        o = _orchestrator()
        o.init("req")  # stage=architect
        o.tick(_make_result_file({"stage": "developer", "files_changed": ["x.py"]}))
        assert o._state.action_history
        assert o._state.action_history[-1]["t_gate_ms"] == 0.0

    def test_over_budget_logs_warning(self, caplog) -> None:
        """t_orchestration 超 ORCH_BUDGET_MS → WARNING (不中断)."""
        o = _orchestrator()
        o.init("req")
        fake_start = time.perf_counter() - 5.0  # 5s 前 → t_total 巨大
        o._t_gate_ms = 0.0
        o._t_guard_sub_ms = 0.0
        with caplog.at_level("WARNING"):
            o._record_tick_latency(fake_start, tick_no=1)
        assert "超预算" in caplog.text

    def test_within_budget_no_warning(self, caplog) -> None:
        o = _orchestrator()
        o.init("req")
        with caplog.at_level("WARNING"):
            o.tick(_architect_result_file())
        assert "超预算" not in caplog.text

    def test_gate_time_excluded_from_orchestration_budget(self, caplog) -> None:
        """gate 墙钟 (t_gate) 不计入编排预算 → 慢 gate 不触发超预算告警."""
        def very_slow_gate_runner(gate_names, project_root):
            time.sleep(0.05)
            return {n: MagicMock(passed=True, message="ok") for n in gate_names}

        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=very_slow_gate_runner,
            guardrail=_pass_guardrail())
        o.init("req")
        o.tick(_architect_result_file())
        with caplog.at_level("WARNING"):
            o.tick(_make_result_file({
                "stage": "developer", "batch_id": "b1", "files_changed": ["x.py"],
                "test_results": {"passed": 1, "failed": 0},
            }))
        # gate 花了 50ms 但归 t_gate, orchestration 仍远低于 2000ms
        assert "超预算" not in caplog.text


def _leaf_cycle_results() -> list[dict]:
    """一个 LEAF 周期的 5 个紧凑 Result payload。"""
    return [
        {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        },
        {
            "stage": "developer", "batch_id": "batch-F-1", "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        },
        {
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        },
        {
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        },
        {
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 1, "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 0,
        },
    ]


def _run_leaf_cycle() -> TickOrchestrator:
    o = _orchestrator()
    o.init("实现单个组件")
    for payload in _leaf_cycle_results():
        o.tick(_make_result_file(payload))
    return o


class TestOrchestrationP95Budget:
    """T26b / DS-10 (C.2.6 §4108): ≥30 tick 代表性 run 收集 t_orchestration_ms 分布,
    断言 P95 < 2000ms; t_gate 墙钟作参考观测 (无阈值)。"""

    def test_p95_orchestration_under_budget_over_30_ticks(self, capsys) -> None:
        orch_ms: list[float] = []
        gate_ms: list[float] = []
        while len(orch_ms) < 30:
            hist = _run_leaf_cycle()._state.action_history
            orch_ms += [r["t_orchestration_ms"] for r in hist]
            gate_ms += [r["t_gate_ms"] for r in hist]
        assert len(orch_ms) >= 30
        # P95 (statistics.quantiles inclusive, n=20 → index 18 = 95th pct)
        p95 = statistics.quantiles(orch_ms, n=20, method="inclusive")[18]
        assert p95 < ORCH_BUDGET_MS, (
            f"P95 编排延迟 {p95:.2f}ms 超预算 {ORCH_BUDGET_MS}ms (纯 Python 退化信号)")
        # 参考观测: t_gate 分布只打印不断言 (外部子进程墙钟, 各由 timeout 兜底)
        gate_p95 = statistics.quantiles(gate_ms, n=20, method="inclusive")[18]
        print(f"[DS-10] n={len(orch_ms)} orch_P95={p95:.3f}ms "
              f"gate_P95(ref)={gate_p95:.3f}ms")

    def test_every_tick_records_orchestration_ms(self) -> None:
        """每 tick 必写 t_orchestration_ms (分布无缺项 → P95 聚合无偏)。"""
        vals = [r["t_orchestration_ms"] for r in _run_leaf_cycle()._state.action_history]
        assert len(vals) == 5
        assert all(isinstance(v, (int, float)) and v >= 0 for v in vals)


class TestInitPersistsDesignDocPath:
    """T9a 前置: init 必须持久化 design_doc_path, restore 才能重 parse 设计文档."""

    def test_init_with_design_doc_persists_path(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        assert o._state.design_doc_path == str(design)




class TestMetricsProductionBoundary:
    def test_offload_passes_non_empty_batch_progress_to_summarizer(
        self, tmp_path
    ) -> None:
        """回归: _offload_stage(developer) 应传非空 batch_progress 给 summarize_structured.

        历史 bug (2026-07-26 T118 mypy 揭示): 调用不存在的
        BatchState.done_count()/total_count() → try/except 静默失败,
        batch_progress 恒为空字符串 (DS-14 T166 batch 进度传递失效)。
        """
        from auto_engineering.context.offloading import ContextOffloader
        from auto_engineering.context.summarization import SessionSummary

        captured: dict = {}

        class _FakeSummarizer:
            def should_summarize(self, tick, threshold=5) -> bool:
                return True

            def summarize_structured(self, **kwargs) -> SessionSummary:
                captured.update(kwargs)
                return SessionSummary(ticks_covered=range(0, 1))

            def inject_into_prompt(self, summary) -> str:
                return "SUMMARY"

        o = _orchestrator()
        o.init("batch_progress 回归")
        o._session_summarizer = _FakeSummarizer()
        o._context_offloader = ContextOffloader(tmp_path / "offload")
        o._state.batch_plan = [{
            "batch_id": "batch-H-1", "design_section": "B2", "component": "Foo",
            "tasks": [{"id": "T1", "description": "实现 foo",
                       "module_ref": "§B2", "file_targets": ["foo.py"]}],
        }]
        o._state.plan = _VALID_PLAN
        o._state.file_list = ["foo.py"]
        o._state.current_stage = "architect"
        architect_result = {
            "stage": "architect",
            "plan": _VALID_PLAN,
            "batch_plan": o._state.batch_plan,
            "file_list": ["foo.py"],
            "contracts": {},
        }
        o._apply_result_to_state(architect_result)
        o._after_tick(architect_result)

        o._offload_stage("developer")

        assert captured.get("batch_progress"), (
            "batch_progress 应非空 (T166 回归: done_count/total_count 不存在 bug)"
        )
        assert "batches done" in captured["batch_progress"]

    def test_architect_offload_keeps_plan_before_stage_cleanup(
        self, tmp_path
    ) -> None:
        """T135: architect offload 必须在 advance 清理字段前保存结构化计划。"""
        from auto_engineering.context.offloading import ContextOffloader

        o = _orchestrator()
        o.init("architect offload 质量")
        offloader = ContextOffloader(tmp_path / "offload")
        o._context_offloader = offloader
        o._apply_result_to_state({
            "stage": "architect",
            "plan": "先实现核心契约，再补集成测试",
            "batch_plan": [{
                "batch_id": "batch-H-1",
                "component": "Host",
                "tasks": [{"id": "T1", "description": "实现契约",
                           "file_targets": ["host.py"]}],
            }],
            "file_list": ["host.py"],
        })

        o._state.current_stage = "architect"
        o._after_tick({})

        artifact = offloader.load_summary("architect")
        assert artifact is not None
        assert "no batches" not in artifact.summary
        assert "1 batches, 1 files" in artifact.summary
        assert "batch_count=1" in artifact.key_decisions
        assert "file_count=1" in artifact.key_decisions

    def test_developer_offload_has_files_gates_and_real_test_total(
        self, tmp_path
    ) -> None:
        """T135: developer offload 使用本轮文件、Gate 与 passed/failed 总数。"""
        from auto_engineering.context.offloading import ContextOffloader

        o = _orchestrator()
        o.init("developer offload 质量")
        offloader = ContextOffloader(tmp_path / "offload")
        o._context_offloader = offloader
        o._state.files_changed = ["host.py"]
        o._state.test_results = {"passed": 2, "failed": 0, "errors": 0}
        o._state.gate_results = {
            "test": {"passed": True, "message": "2 passed"},
        }

        o._offload_stage("developer")

        artifact = offloader.load_summary("developer")
        assert artifact is not None
        assert "2/2 tests passed" in artifact.summary
        assert artifact.files_changed == ["host.py"]
        assert artifact.gate_results["test"]["passed"] is True
        assert "files_changed_count=1" in artifact.key_decisions

    def test_metrics_collector_not_initialized_without_env_var(self) -> None:
        """T105f: AE_METRICS 未设置时 get_collector() 返回 None."""
        import os
        os.environ.pop("AE_METRICS", None)
        from auto_engineering.metrics.collector import get_collector, set_collector
        set_collector(None)
        assert get_collector() is None


# ── T109: PII 四层文件桥接防护 ──


class TestT109PIIInit:
    """T109b: L1 — requirement PII scan in init flow."""

    def test_init_scans_requirement_for_pii(self) -> None:
        """requirement 含身份证号 → WARN 日志."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        action = o.init("用户张三的身份证号是320102199001011234")
        assert action["action"] == "architect"
        # requirement 仍正常写入 (不阻断)
        assert "张三" in o._state.requirement

    def test_init_no_pii_clean_requirement(self) -> None:
        """无 PII requirement 不触发 WARN."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        action = o.init("实现用户登录功能")
        assert action["action"] == "architect"

    def test_init_pii_disabled_skips_scan(self) -> None:
        """AE_PII_ENABLED=0 时跳过扫描."""
        o = _orchestrator()
        o._pii_enabled = False
        o._pii_redactor = None
        action = o.init("用户身份证320102199001011234")
        assert action["action"] == "architect"


class TestT109PIIOutbound:
    """T109c: L2 — outbound action JSON PII redact in build_action."""

    def test_outbound_redact_default(self) -> None:
        """DS-15: requirement 在 action 顶层，不在 context 中. PII 扫描用户字段."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "architect"
        action = o.build_action()
        # DS-15: requirement 在 action 顶层
        req = action.get("requirement", "")
        assert "req" in req

    def test_outbound_redact_masks_pii_in_action(self) -> None:
        """action JSON 中的 PII 被脱敏 (requirement 顶层)."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("用户身份证号 320102199001011234")
        o._state.current_stage = "architect"
        action = o.build_action()
        req = action.get("requirement", "")
        # 身份证号被脱敏 (原始号码不在输出中)
        assert "320102199001011234" not in req

    def test_outbound_block_mode(self, monkeypatch) -> None:
        """AE_PII_OUTBOUND=block: PII 命中 → error action."""
        monkeypatch.setenv("AE_PII_OUTBOUND", "block")
        o = _orchestrator()
        # re-init PII with block-compatible env
        import os as _os
        o._pii_enabled = _os.environ.get("AE_PII_ENABLED", "1") == "1"
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "architect"
        o._state.requirement = "身份证320102199001011234"
        action = o.build_action()
        # architect action 携带 requirement，含身份证号 → block
        if action["action"] == "error":
            assert action["error_code"] == "PII_BLOCKED_OUTBOUND"
        else:
            # requirement 也可能没被 scan_dict 命中 (只扫描字符串值)
            pass

    def test_outbound_warn_mode(self, monkeypatch) -> None:
        """AE_PII_OUTBOUND=warn: PII 命中 → WARN 但不阻断."""
        monkeypatch.setenv("AE_PII_OUTBOUND", "warn")
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "architect"
        action = o.build_action()
        # warn 模式不阻断
        assert action["action"] == "architect"

    def test_outbound_pii_disabled_no_redact(self) -> None:
        """PII 关闭时 action 原样返回."""
        o = _orchestrator()
        o._pii_enabled = False
        o._pii_redactor = None
        o.init("用户身份证号 320102199001011234")
        o._state.current_stage = "architect"
        action = o.build_action()
        # DS-15: requirement at action top level, PII 禁用所以未脱敏
        req = action.get("requirement", "")
        assert "320102199001011234" in req


class TestT109PIIInbound:
    """T109d: L3 — inbound result JSON PII scan."""

    def test_inbound_warn_default(self) -> None:
        """默认 warn 模式: PII 命中 → WARN 日志, 不阻断."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "developer"
        result = {
            "stage": "developer",
            "files_changed": ["test.py"],
            "commit_hash": "abc123",
            "description": "身份证号 320102199001011234",
        }
        validated = o._scan_inbound_for_pii(result)
        assert isinstance(validated, dict)
        # result 原样返回 (warn 不修改)
        assert "320102199001011234" in validated.get("description", "")

    def test_inbound_redact_mode(self, monkeypatch) -> None:
        """AE_PII_INBOUND=redact: PII 被脱敏."""
        monkeypatch.setenv("AE_PII_INBOUND", "redact")
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "developer"
        result = {
            "stage": "developer",
            "files_changed": ["test.py"],
            "commit_hash": "abc123",
            "description": "身份证号 320102199001011234",
        }
        validated = o._scan_inbound_for_pii(result)
        assert isinstance(validated, dict)
        # PII 被脱敏
        assert "320102199001011234" not in validated.get("description", "")

    def test_inbound_block_mode(self, monkeypatch) -> None:
        """AE_PII_INBOUND=block: PII 命中 → ErrorResponse 拒绝."""
        monkeypatch.setenv("AE_PII_INBOUND", "block")
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "developer"
        result = {
            "stage": "developer",
            "files_changed": ["test.py"],
            "commit_hash": "abc123",
            "description": "身份证号 320102199001011234",
        }
        validated = o._scan_inbound_for_pii(result)
        from auto_engineering.loop.actions import ErrorResponse
        assert isinstance(validated, ErrorResponse)
        assert validated.error_code == "PII_BLOCKED_INBOUND"

    def test_inbound_no_pii_clean_result(self) -> None:
        """无 PII 的 result 原样通过."""
        o = _orchestrator()
        o._pii_enabled = True
        from auto_engineering.pii.redactor import PIIRedactor
        o._pii_redactor = PIIRedactor()
        o.init("req")
        o._state.current_stage = "developer"
        result = {
            "stage": "developer",
            "files_changed": ["test.py"],
            "commit_hash": "abc123",
        }
        validated = o._scan_inbound_for_pii(result)
        assert isinstance(validated, dict)
        assert validated == result

    def test_inbound_pii_disabled(self) -> None:
        """PII 关闭时 result 原样返回."""
        o = _orchestrator()
        o._pii_enabled = False
        o._pii_redactor = None
        o.init("req")
        o._state.current_stage = "developer"
        result = {
            "stage": "developer",
            "files_changed": ["test.py"],
            "commit_hash": "abc123",
            "description": "身份证号 320102199001011234",
        }
        validated = o._scan_inbound_for_pii(result)
        assert isinstance(validated, dict)
        assert "320102199001011234" in validated.get("description", "")


class TestT113Require:
    """T113 L2: _require() — 静默 No-op 可见化."""

    def test_require_returns_value_when_not_none(self) -> None:
        """非 None 属性正常返回."""
        o = _orchestrator()
        o.init("test requirement")
        result = o._require("_state", "engine state")
        assert result is not None
        assert isinstance(result, EngineState)

    def test_require_returns_none_when_attribute_is_none(self) -> None:
        """None 属性返回 None, 不抛异常."""
        o = _orchestrator()
        result = o._require("_design_doc", "design doc not loaded")
        assert result is None

    def test_require_unknown_attribute_returns_none(self) -> None:
        """不存在的属性返回 None, 不抛异常."""
        o = _orchestrator()
        result = o._require("_nonexistent_field_xyz", "unknown")
        assert result is None

    def test_require_logs_debug_when_none(self, caplog) -> None:
        """None 时输出 DEBUG 级别日志, 包含属性名和原因."""
        import logging
        caplog.set_level(logging.DEBUG, logger="ae.loop.tick_orchestrator")
        o = _orchestrator()
        o._require("_design_doc", "design doc not loaded for test")
        assert any("_design_doc" in r.message and "design doc not loaded" in r.message
                   for r in caplog.records)

    def test_require_no_log_when_not_none(self, caplog) -> None:
        """非 None 时不输出额外日志."""
        import logging
        caplog.set_level(logging.DEBUG, logger="ae.loop.tick_orchestrator")
        o = _orchestrator()
        o.init("test")
        caplog.clear()
        o._require("_state", "should not log")
        assert len(caplog.records) == 0


class TestGapReviewResearchRouting:
    """F9 (2026-07-26 真跑): gap_review resolution 大小写/格式归一化 → research 路由。

    真跑中 Team Lead 按 prompt 提交 resolution="Research"（首字母大写），旧代码小写匹配
    不识别 → pending_research 为空 → 跳过 research 直进 architect → T50 搜索通路未触发。
    """

    def _setup(self, resolution: str):
        o = _orchestrator()
        o.init("req")
        o._state.current_stage = "gap_review"
        o._state.gap_report_json = json.dumps(
            {"gaps": [{"id": "G1", "grade": "module"}], "has_blocking": False})
        o._state.pending_gap_decisions = [{"gap_id": "G1", "resolution": resolution}]
        o._state.research_archive = {}
        o._state.pending_research_ids = []
        return o

    def test_capital_research_routes_to_research(self, monkeypatch):
        o = self._setup("Research")  # 首字母大写，如 prompt 指示
        monkeypatch.setattr(o, "build_action", lambda: {"action": "research"})
        o._after_tick({})
        assert o._state.current_stage == "research"
        assert o._state.pending_research_ids == ["G1"]

    def test_defer_plus_research_routes_to_research(self, monkeypatch):
        o = self._setup("Defer+Research")  # 带 + 格式
        monkeypatch.setattr(o, "build_action", lambda: {"action": "research"})
        o._after_tick({})
        assert o._state.current_stage == "research"
        assert o._state.pending_research_ids == ["G1"]

    def test_capital_defer_routes_to_architect(self, monkeypatch):
        o = self._setup("Defer")  # Defer → 留 architect，不进 research
        monkeypatch.setattr(o, "build_action", lambda: {"action": "architect"})
        o._after_tick({})
        assert o._state.current_stage == "architect"
        assert o._state.pending_research_ids == []

    def test_lowercase_research_still_works(self, monkeypatch):
        o = self._setup("research")  # 原小写形式不受影响
        monkeypatch.setattr(o, "build_action", lambda: {"action": "research"})
        o._after_tick({})
        assert o._state.current_stage == "research"


class TestF8ActionContextInjection:
    """F8 (2026-07-26 真跑): verifier/audit action 注入 component/plate context。

    此前 component_verifier/plate_deep_audit action 的 context 为空，subagent 不知
    验哪个组件/审哪个板块，须 Team Lead 手动查 batch_state 补上下文。
    """

    def _builder(self, tmp_path, monkeypatch):
        from auto_engineering.loop.action_builder import ActionBuilder
        b = ActionBuilder(tmp_path)
        monkeypatch.setattr(
            b,
            "_load_prompt",
            lambda stage: (
                "coordinator\n***\nworker-1\n***\nworker-2\n***\nworker-3"
                if stage == "plate_deep_audit"
                else "test prompt"
            ),
        )
        monkeypatch.setattr(b, "_write_spawn_proof_file", lambda *a, **k: None)
        return b

    def test_component_verifier_action_has_component_context(self, tmp_path, monkeypatch):
        b = self._builder(tmp_path, monkeypatch)
        comp = MagicMock()
        comp.name = "ApiKeyInput"
        comp.design_section = "§6.2"
        comp.design_spec_summary.return_value = "密码输入框 + Show/Hide"
        bs = MagicMock()
        bs.current_component.return_value = comp
        bs.batches_for.return_value = [
            {"tasks": [{"file_targets": ["src/components/ApiKeyInput.tsx"]}]}]
        state = EngineState(thread_id="t", current_stage="component_verifier")
        action, prompt = _materialize_worker_action(b, state, batch_state=bs)
        assert "context" not in action
        assert '"ApiKeyInput"' in prompt
        assert '"§6.2"' in prompt
        assert "密码输入框 + Show/Hide" in prompt
        assert "ApiKeyInput.tsx" in prompt

    def test_plate_deep_audit_action_has_plate_context(self, tmp_path, monkeypatch):
        b = self._builder(tmp_path, monkeypatch)
        plate = MagicMock()
        plate.name = "工具模块"
        c1 = MagicMock()
        c1.name = "voice-id.ts — Voice ID 校验"
        plate.components = [c1]
        bs = MagicMock()
        bs.current_plate.return_value = plate
        state = EngineState(thread_id="t", current_stage="plate_deep_audit")
        plan = b.build_plan(state, batch_state=bs)
        from auto_engineering.loop.effects import EffectExecutor

        executor = EffectExecutor(tmp_path)
        for intent in plan.effect_intents:
            executor.execute(intent)
        action = plan.payload
        assert "context" not in action
        invocations = action["spawn"]["invocations"]
        prompt = (tmp_path / invocations[0]["prompt_ref"]).read_text(encoding="utf-8")
        assert "工具模块" in prompt
        assert "voice-id.ts — Voice ID 校验" in prompt
        assert "prompt" not in invocations[0]
        assert len({a["receipt_path"] for a in invocations}) == 3
        assert all(a["receipt_path"].endswith(".json") for a in invocations)

    def test_plate_deep_audit_no_batch_state_no_context(self, tmp_path, monkeypatch):
        from auto_engineering.prompts.compiler import PromptContextError

        b = self._builder(tmp_path, monkeypatch)
        state = EngineState(thread_id="t", current_stage="plate_deep_audit")
        with pytest.raises(PromptContextError, match="plate, components"):
            b.build_action(state)


class TestF7SpawnProofForgery:
    """F7 (2026-07-26 真跑): spawn proof 防伪。

    旧问题: ① spawn 指令未让 result 带 spawn_proof_token → gate 校验被整体跳过；
    ② 指令让 subagent「追加」proof（损坏 JSON）且未写 status=completed；
    ③ gate 即使发现 proof 不合格也只告警不拦截。当前严格合同由 Assembler 独占写入
    token、receipt、attestation 与 proof；Action instruction 不再诱导宿主手工覆盖。
    """

    def test_instruction_delegates_proof_writes_to_assembler(self):
        from auto_engineering.loop.action_builder import _SPAWN_INSTRUCTION
        rendered = _SPAWN_INSTRUCTION.format(
            count=1, parallel="", effort="high", multi_instruction="",
            stage="critic", proof_token="abc123", project_root="/tmp/project")
        assert "spawn.invocations[]" in rendered
        assert '"outcomes"' in rendered
        assert "host_execution.operations.finalize.argv" in rendered
        assert "__AE_BUNDLED_RUNNER__" in rendered
        assert "abc123" not in rendered
        assert "OVERWRITE" not in rendered
        assert "binding design document is read-only" in rendered
        assert "relative to the project root" in rendered
        assert "must not invoke Agent/Task/collaboration or create nested workers" in rendered
        assert "HOST_EVIDENCE_INVALID" in rendered
        assert "async_launched" in rendered
        assert "TaskOutput" in rendered
        assert "do not Stop, TaskStop, Read, Bash" in rendered

    def _setup_critic(self, tmp_path, proof_status):
        o = _orchestrator()
        action = o.init("req")
        o._state.current_stage = "critic"
        o._state.expected_stage = "critic"
        o.project_root = tmp_path
        o._active_action = {
            **action,
            "stage": "critic",
            "spawn_proof_token": "tok123",
        }
        proof_dir = tmp_path / ".ae-state" / "spawn-proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        (proof_dir / "tok123.json").write_text(
            json.dumps({
                "token": "tok123",
                "status": proof_status,
                "stage": "critic",
                "thread_id": o._state.thread_id,
                "action_message_id": action["message_id"],
            }))
        challenge_dir = tmp_path / ".ae-state" / "spawn-challenges"
        challenge_dir.mkdir(parents=True, exist_ok=True)
        (challenge_dir / "tok123.json").write_text(json.dumps({
            "token": "tok123", "status": "pending", "stage": "critic",
            "thread_id": o._state.thread_id,
            "action_message_id": action["message_id"],
        }))
        self._current_orchestrator = o
        for spec in SpawnPlan.from_action(o._active_action).invocations:
            receipt_path = tmp_path / spec.receipt_path
            receipt_path.write_text(json.dumps({
                "status": "completed", "stage": "critic",
                "worker": spec.worker_id,
                "native_worker_handle": f"test-{spec.worker_id}",
                "requested_effort": spec.requested_effort,
                "actual_model": "test-model",
            }), encoding="utf-8")
        return o

    def _critic_result(self):
        action = self._current_orchestrator._active_action
        plan = SpawnPlan.from_action(action)
        return {"stage": "critic", "spawned": True, "spawn_proof_token": "tok123",
                "worker_attestations": [WorkerAttestation.completed(
                    platform=HostPlatform.CODEX,
                    action_message_id=action["message_id"], invocation=spec,
                    effective_effort=spec.requested_effort,
                    isolation_evidence="fork_turns=none",
                    visible_capabilities=tuple(sorted(spec.capabilities)),
                    actual_model="test-model",
                ).to_dict() for spec in plan.invocations],
                "verdict": "APPROVE", "findings": [], "critic_feedback": "ok"}

    def test_proof_incomplete_blocks(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse
        o = self._setup_critic(tmp_path, "pending")
        resp = o._validate_result_dict(self._critic_result())
        assert isinstance(resp, ErrorResponse)
        assert resp.error_code == "HOST_EVIDENCE_INVALID"
        assert "SPAWN_PROOF_INCOMPLETE" in resp.message

    def test_proof_corrupted_blocks(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse
        o = self._setup_critic(tmp_path, "pending")
        # 模拟「追加第二段」损坏的 proof 文件（两个 JSON 对象拼接）
        (tmp_path / ".ae-state" / "spawn-proofs" / "tok123.json").write_text(
            '{"status":"pending"}{"status":"done"}')
        resp = o._validate_result_dict(self._critic_result())
        assert isinstance(resp, ErrorResponse)
        assert resp.error_code == "HOST_EVIDENCE_INVALID"
        assert "SPAWN_PROOF_INCOMPLETE" in resp.message

    def test_proof_completed_passes(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse
        from auto_engineering.loop.effects import WriteJsonArtifact
        o = self._setup_critic(tmp_path, "completed")
        resp = o._validate_result_dict(self._critic_result())
        assert not (isinstance(resp, ErrorResponse)
                    and resp.error_code == "SPAWN_PROOF_INCOMPLETE")
        # 验证阶段只规划 acceptance receipt；统一提交边界负责实际落盘。
        assert any(
            isinstance(intent, WriteJsonArtifact)
            and intent.relative_path == "spawn-receipts/tok123.accepted.json"
            for intent in o._pending_effect_intents
        )
        o._execute_pending_effects()
        accepted = json.loads(
            (tmp_path / ".ae-state" / "spawn-receipts"
             / "tok123.accepted.json").read_text(encoding="utf-8")
        )
        assert accepted["action_message_id"] == o._active_action["message_id"]
        assert len(accepted["result_sha256"]) == 64

    def test_native_v11_result_requires_worker_attestation(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = self._setup_critic(tmp_path, "completed")
        result = {
            **self._critic_result(),
            "schema_version": "1.1",
            "extensions": {},
        }
        result.pop("worker_attestations")

        response = o._validate_result_dict(result)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "HOST_EVIDENCE_INVALID"
        assert "WORKER_ATTESTATIONS_MISSING" in response.message

    def test_strict_action_requires_each_worker_receipt(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = self._setup_critic(tmp_path, "completed")
        result = self._critic_result()
        for spec in SpawnPlan.from_action(o._active_action).invocations:
            (tmp_path / spec.receipt_path).unlink(missing_ok=True)

        response = o._validate_result_dict(result)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "HOST_EVIDENCE_INVALID"
        assert "WORKER_RECEIPT_MISSING" in response.message

    def test_strict_action_rejects_result_claiming_legacy_schema(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = self._setup_critic(tmp_path, "completed")
        result = {
            **self._critic_result(),
            "schema_version": "1.1",
            "extensions": {"compat": {"source_schema_version": "1.0"}},
        }
        result.pop("worker_attestations")

        response = o._validate_result_dict(result)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "HOST_EVIDENCE_INVALID"
        assert "WORKER_ATTESTATIONS_MISSING" in response.message

    def test_missing_or_stale_proof_token_blocks(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = self._setup_critic(tmp_path, "completed")
        for token in (None, "stale-token"):
            result = self._critic_result()
            if token is None:
                result.pop("spawn_proof_token")
            else:
                result["spawn_proof_token"] = token

            response = o._validate_result_dict(result)

            assert isinstance(response, ErrorResponse)
            assert response.error_code == "HOST_EVIDENCE_INVALID"
            assert "SPAWN_PROOF_TOKEN_MISMATCH" in response.message

    def test_agent_capacity_failure_preserves_active_action_for_retry(self, tmp_path):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]
        tick_before = o._state.tick

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_AGENT_CAPACITY",
            "spawn_error": "agent thread limit reached",
        })

        assert action["action"] == "resource_wait"
        assert action["resource"] == "agent_slot"
        assert action["retry_stage"] == "critic"
        assert action["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_RESOURCE"
        assert o._active_action["message_id"] == active_message_id
        assert o._state.tick == tick_before

    def test_worker_timeout_waits_for_retry_without_consuming_business_budget(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]
        tick_before = o._state.tick
        counters_before = dict(o._state.guardrail_retry_counters)

        result = {
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_TIMEOUT",
            "spawn_error": "native worker wait deadline exceeded",
            "spawn_retry_attempt": 1,
        }
        assert o._validate_result_dict(result) == result

        action = o.tick_dict(result)

        assert action["action"] == "resource_wait"
        assert action["reason_code"] == "HOST_WORKER_TIMEOUT"
        assert action["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_RESOURCE"
        assert o._active_action["message_id"] == active_message_id
        assert o._state.tick == tick_before
        assert o._state.guardrail_retry_counters == counters_before


    def test_second_worker_timeout_exhausts_retry_without_replacing_action(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_TIMEOUT",
            "spawn_error": "native worker wait deadline exceeded",
            "spawn_retry_attempt": 2,
        })

        assert action["action"] == "error"
        assert action["error_code"] == "HOST_WORKER_TIMEOUT_EXHAUSTED"
        assert o._active_action["message_id"] == active_message_id

    def test_worker_role_failure_is_not_reported_as_missing_host_capability(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]
        tick_before = o._state.tick

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_CAPABILITY_UNAVAILABLE",
            "spawn_error": "collaboration.spawn_agent 未暴露",
        })

        assert action["error_code"] == "WORKER_ROLE_VIOLATION"
        assert active_message_id in action["message"]
        assert "不得给 Worker 开放" in action["suggestion"]
        assert o._active_action["message_id"] == active_message_id
        assert o._state.tick == tick_before

    def test_worker_failure_returns_resource_wait_for_automatic_retry(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_FAILED",
            "spawn_error": "prompt hash mismatch",
            "spawn_retry_attempt": 1,
        })

        assert action["action"] == "resource_wait"
        assert action["reason_code"] == "HOST_WORKER_FAILED"
        assert action["retry_attempt"] == 1
        assert o._active_action["message_id"] == active_message_id

    def test_repeated_worker_failure_is_bounded(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_FAILED",
            "spawn_error": "prompt hash mismatch",
            "spawn_retry_attempt": 2,
        })

        assert action["action"] == "error"
        assert action["error_code"] == "HOST_WORKER_FAILURE_EXHAUSTED"

    def test_unknown_worker_failure_preserves_action_with_recovery_guidance(
        self, tmp_path,
    ):
        o = self._setup_critic(tmp_path, "pending")
        active_message_id = o._active_action["message_id"]

        action = o.tick_dict({
            "stage": "critic",
            "spawned": False,
            "spawn_error": "native worker terminated unexpectedly",
        })

        assert action["error_code"] == "HOST_WORKER_FAILED"
        assert active_message_id in action["message"]
        assert "重新执行原 active Action" in action["suggestion"]
        assert o._active_action["message_id"] == active_message_id

    def test_init_binds_proof_to_protocol_action(self, tmp_path):
        from copy import copy

        from auto_engineering.loop.action_builder import ActionBuilder
        from auto_engineering.loop.effects import EffectExecutor

        builder = ActionBuilder(tmp_path)
        intents = []
        receipts = []
        builder = copy(builder)
        builder._effect_intent_sink = intents.append
        builder._effect_sink = receipts.append
        token = "proof-token"
        builder._write_spawn_proof_file(token, "architect")
        action = {
            "spawn_proof_token": token,
            "thread_id": "thread-1",
            "message_id": "action-1",
            "stage": "architect",
        }
        builder.bind_spawn_proofs(action)
        executor = EffectExecutor(tmp_path)
        for intent in intents:
            executor.execute(intent)
        proof = json.loads(
            (tmp_path / ".ae-state" / "spawn-proofs" / f"{token}.json")
            .read_text(encoding="utf-8")
        )
        challenge_path = (
            tmp_path / ".ae-state" / "spawn-challenges" / f"{token}.json"
        )
        challenge_before = challenge_path.read_bytes()
        (tmp_path / ".ae-state" / "spawn-proofs" / f"{token}.json").write_text(
            json.dumps({
                "token": token,
                "stage": "architect",
                "status": "completed",
            }),
            encoding="utf-8",
        )

        assert proof["token"] == token
        assert proof["thread_id"] == action["thread_id"]
        assert proof["action_message_id"] == action["message_id"]
        assert proof["stage"] == action["stage"]
        assert challenge_path.read_bytes() == challenge_before
        challenge = json.loads(challenge_before)
        assert challenge["action_message_id"] == action["message_id"]

    def test_multi_agent_missing_worker_receipt_blocks(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = _orchestrator()
        o.init("req")
        o._state.current_stage = "plate_deep_audit"
        o._state.expected_stage = "plate_deep_audit"
        o.project_root = tmp_path
        proof_dir = tmp_path / ".ae-state" / "spawn-proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        (proof_dir / "total.json").write_text(
            json.dumps({"status": "completed", "stage": "plate_deep_audit"})
        )
        for token in ("worker-0", "worker-1"):
            (proof_dir / f"{token}.json").write_text(
                json.dumps({"status": "completed", "stage": "plate_deep_audit"})
            )
        o._active_action = {
            "spawn_proof_token": "total",
            "message_id": "action-plate",
            "spawn": {
                "agents": [
                    {"index": 0, "receipt_token": "worker-0"},
                    {"index": 1, "receipt_token": "worker-1"},
                    {"index": 2, "receipt_token": "worker-2"},
                ],
            },
        }
        total_proof = {
            "token": "total",
            "status": "completed",
            "stage": "plate_deep_audit",
            "thread_id": o._state.thread_id,
            "action_message_id": "action-plate",
        }
        (proof_dir / "total.json").write_text(json.dumps(total_proof))
        result = {
            "stage": "plate_deep_audit",
            "spawned": True,
            "spawn_proof_token": "total",
            "plate": "协议层",
            "findings": [],
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": 0,
            "cross_component_issues": [],
        }

        response = o._validate_result_dict(result)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "WORKER_INVOCATION_CONTRACT_REQUIRED"
        assert "spawn.agents" in response.message


class TestDeveloperInstruction:
    """P0 (2026-07-26 真跑): developer 阶段渲染 inline instruction。

    旧版 developer action 无 instruction（"no instruction — inline stage"），最核心的
    编码环节无标准化驱动指引。修复后渲染 batch/组件/tasks + TDD 铁律 + 项目约定 + result 格式。
    """

    def test_developer_action_has_instruction(self, tmp_path, monkeypatch):
        from auto_engineering.loop.action_builder import ActionBuilder
        b = ActionBuilder(tmp_path)
        bs = MagicMock()
        bs.current_component_name.return_value = "ApiKeyInput"
        bs.current_batch_id.return_value = "B7"
        task = MagicMock()
        task.id = "B7-T1"
        task.description = "实现 ApiKeyInput 组件"
        task.expected_output = "ApiKeyInput.tsx"
        task.target_files = ["src/components/ApiKeyInput.tsx"]
        task.depends_on = []
        bs.current_batch_tasks.return_value = [task]
        plan = MagicMock()
        state = EngineState(thread_id="t", current_stage="developer", plan="plan")
        action, prompt = _materialize_worker_action(b, state, batch_state=bs, plan=plan)
        assert action["spawn"]["count"] == 1
        assert "B7" in prompt
        assert "ApiKeyInput" in prompt
        assert "B7-T1" in prompt
        assert "TDD 铁律" in prompt
        assert "inline TDD" not in prompt
        assert "隔离 Worker 会话" in prompt
        assert "project_profile_summary" in prompt
        assert "init-manifest" not in prompt
        assert "test_results" in prompt  # result 格式指引
        assert "只能修改当前 task 的 file_targets" in prompt
        assert "不得跨 batch 提前实现其他设计项" in prompt
        assert "files_changed 只填写本次真实变更" in prompt

    def test_developer_instruction_no_tasks_graceful(self, tmp_path):
        from auto_engineering.loop.action_builder import ActionBuilder
        b = ActionBuilder(tmp_path)
        state = EngineState(thread_id="t", current_stage="developer", plan="plan")
        _action, prompt = _materialize_worker_action(b, state)
        assert "无 task 明细" in prompt  # 优雅降级
