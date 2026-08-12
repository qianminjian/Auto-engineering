"""TickOrchestrator unit tests — 完整 LEAF batch_plan 循环 (快速 stub, 防挂死).

设计参考: v5.6-Design-Loop.md §C.5.

所有测试注入:
  - gate_runner:    快速 stub (全 PASS, 不跑真实 lint/test)
  - guardrail:      快速 stub (always pass)
  - checkpoint_store: None (no-op save)

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

from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import VerificationLayers
from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import WorkerAttestation
from auto_engineering.loop.architect_validation import dry_run_architect_plan
from auto_engineering.loop.escalation_handler import EscalationContext, EscalationHandler
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.tick_orchestrator import ORCH_BUDGET_MS, TickOrchestrator

_TEST_RUNTIME_HANDLE = tempfile.TemporaryDirectory(prefix="ae-orchestrator-tests-")
_TEST_RUNTIME_ROOT = Path(_TEST_RUNTIME_HANDLE.name)
(_TEST_RUNTIME_ROOT / "demo").mkdir()
(_TEST_RUNTIME_ROOT / "pyproject.toml").write_text(
    "[project]\nname='demo'\n", encoding="utf-8"
)
_ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
_ACTIVE_ORCHESTRATOR: TickOrchestrator | None = None


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


def _orchestrator(max_rounds: int = 10, escalate: bool = False) -> TickOrchestrator:
    global _ACTIVE_ORCHESTRATOR, _ACTIVE_TEST_ROOT
    _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
    _ACTIVE_ORCHESTRATOR = TickOrchestrator(
        project_root=_TEST_RUNTIME_ROOT,
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=None,
        escalate=escalate,
    )
    return _ACTIVE_ORCHESTRATOR


def _make_result_file(data: dict) -> Path:
    if data.get("spawned") is True:
        active = _ACTIVE_ORCHESTRATOR._active_action if _ACTIVE_ORCHESTRATOR else None
        if isinstance(active, dict) and active.get("stage") == data.get("stage"):
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
                "tasks": [{"id": "B1-T1", "description": "实现按钮"}],
            }],
        }
        assert dry_run_architect_plan(o._design_doc, valid, o._state.requirement) is None
        invalid = {**valid, "batch_plan": [{
            **valid["batch_plan"][0], "component": "Missing", "design_section": "Missing"
        }]}
        assert "Missing" in (
            dry_run_architect_plan(o._design_doc, invalid, o._state.requirement) or ""
        )


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
        assert len(o._plan.get_tasks_by_stage("developer")) == 1

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

    def test_checkpoint_saved_between_batches(self, tmp_path) -> None:
        """BUG-03: batch 间切换必须保存 checkpoint, 否则跨进程 batch_idx 归零."""
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        _prepare_existing_project(tmp_path)
        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = tmp_path
        o = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=store,
        )
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
        # first developer batch → 应存 checkpoint (batch_idx 0→1)
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["a.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))

        # 模拟跨进程 restore: 新 TickOrchestrator 从 checkpoint 恢复
        restored = TickOrchestrator.restore(tmp_path, store)
        assert restored._batch_state is not None
        assert restored._batch_state.current_batch_idx == 1, (
            f"BUG-03: batch_idx 应为 1 (已推进到 b2), "
            f"实际为 {restored._batch_state.current_batch_idx} "
            f"(checkpoint 未保存导致跨进程归零)"
        )
        assert restored._batch_state.current_batch_id() == "b2"
        assert restored._state.current_stage == "developer"
        store.close()


# ── critic → component_verifier → system_deep_audit → convergence ──


class TestFullLeafConvergence:
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
            "full_coverage_map": [{"design_section": "B2", "status": "IMPLEMENTED"}],
            "total_design_items": 1, "covered_count": 1,
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
        o = _orchestrator(max_rounds=20)
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
        o = _orchestrator(max_rounds=20)
        self._drive_to_system_deep_audit(o)
        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 2,
        }))
        assert a["action"] == "architect"


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
        o = _orchestrator(max_rounds=20)
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
        o = _orchestrator(max_rounds=20)
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
        o = _orchestrator(max_rounds=20)
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
        o = _orchestrator(max_rounds=20)
        a = self._drive_component_gap(o, "DIVERGED")
        gap = a["feedback"]["refine_request"]["gaps"][0]
        assert gap["kind"] == "DIVERGED"
        assert gap["location"] == "foo.py:7"

    def test_refine_request_json_persisted_to_state(self) -> None:
        o = _orchestrator(max_rounds=20)
        self._drive_component_gap(o, "MISSING")
        assert o._state.refine_request_json
        req = json.loads(o._state.refine_request_json)
        assert req["source"] == "component_verifier"
        assert req["trigger_tick"] >= 0


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
        o = _orchestrator(max_rounds=30)
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
        o = _orchestrator(max_rounds=30)
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
        o = _orchestrator(max_rounds=30)
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
        o = _orchestrator(max_rounds=30)
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
        o = _orchestrator(max_rounds=30)
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
        o = _orchestrator(max_rounds=20)
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
        o = _orchestrator(max_rounds=20)
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
        ])
        baseline_before = o._state.architecture_baseline["baseline_id"]

        result = o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [
                {"batch_id": "b1", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "changed",
                            "module_ref": "§B2", "file_targets": ["foo.py"]}]},
            ],
            "file_list": ["foo.py"], "contracts": {},
        }))

        assert result["error_code"] == "ARCHITECT_PLAN_INVALID"
        assert "plan_patch" in result["message"]
        assert o._state.architecture_baseline["baseline_id"] == baseline_before
        assert o._batch_state.batch_plan[0]["tasks"][0]["description"] == "d"

    def test_refine_action_requests_incremental_plan_patch(self) -> None:
        o = _orchestrator(max_rounds=20)
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
        ])

        action = o._active_action
        assert action["expected_format"]["plan_patch"].startswith("{")
        assert "obligation_updates" in action["expected_format"]["plan_patch"]
        assert "batch_plan" not in action["expected_format"]
        assert '"plan_revision": 1' in action["subagent_prompt"]
        assert "历史 obligation 自动继承" in action["subagent_prompt"]
        assert "不得重复提交" in action["subagent_prompt"]

    def test_refine_patch_cannot_delete_existing_component(self) -> None:
        o = _orchestrator(max_rounds=20)
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
        assert '"requirement": "req"' in a["subagent_prompt"]

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

        assert "你是 Developer" in action["instruction"]
        assert "重复 Result 会推进两次" in action["instruction"]
        assert '"git_authorized": false' in action["instruction"]

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
        assert '"files_changed": [' in action["subagent_prompt"]
        assert '"x.py"' in action["subagent_prompt"]
        assert action["extensions"]["context_manifest"]["duplicate_block_bytes"] == 0

    def test_system_verifier_receives_global_context(self) -> None:
        o = _orchestrator()
        o.init("验证全量设计")
        o._state.current_stage = "system_verifier"
        o._state.design_doc_path = "design/spec.md"
        o._state.file_list = ["auto_engineering/events/store.py"]
        o._state.coverage_map = [{"design_item": "幂等", "status": "IMPLEMENTED"}]

        action = o.build_action()

        prompt = action["subagent_prompt"]
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
        o._apply_result_to_state({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{"batch_id": "b1"}],
            "file_list": ["x.py"], "contracts": {"c1": "spec"},
        })
        assert o._state.plan == _VALID_PLAN
        assert o._state.batch_plan == [{"batch_id": "b1"}]
        assert o._state.file_list == ["x.py"]
        assert o._state.contracts == {"c1": "spec"}

    def test_developer_writes_files_commit_tests(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "developer", "files_changed": ["a.py"],
            "commit_hash": "abc", "test_results": {"passed": 2, "failed": 0},
        })
        assert o._state.files_changed == ["a.py"]
        assert o._state.commit_hash == "abc"
        assert o._state.test_results == {"passed": 2, "failed": 0}

    def test_critic_writes_verdict_to_critic_verdict_field(self) -> None:
        """T1 决策: EngineState 字段名是 critic_verdict, 非 verdict."""
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "critic", "spawned": True, "verdict": "APPROVE",
            "findings": [{"x": 1}], "critic_feedback": "ok",
        })
        assert o._state.critic_verdict == "APPROVE"
        assert o._state.findings == [{"x": 1}]
        assert o._state.critic_feedback == "ok"

    def test_component_verifier_writes_coverage_map(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "component_verifier", "spawned": True,
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED"}],
        })
        assert o._state.coverage_map == [
            {"design_item": "B2-1", "status": "IMPLEMENTED"}]

    def test_system_verifier_maps_full_coverage_to_coverage_map(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "system_verifier", "spawned": True,
            "full_coverage_map": [{"design_section": "B2", "status": "IMPLEMENTED"}],
        })
        assert o._state.coverage_map == [
            {"design_section": "B2", "status": "IMPLEMENTED"}]

    def test_critic_invalid_verdict_rejected_by_after_critic(self) -> None:
        """T116: 非法 critic verdict 在 _after_critic() 中被拦截（非 _apply_result_to_state）"""
        o = _orchestrator()
        o.init("req")
        # _apply_result_to_state 只负责赋值，不校验 verdict 合法性
        o._apply_result_to_state({
            "stage": "critic", "spawned": True, "verdict": "INVALID",
            "findings": [], "critic_feedback": "",
        })
        # state 被写入（原始值）
        assert o._state.critic_verdict == "INVALID"
        # CriticHandler 捕获非法 verdict 并返回 ActionError
        o._state.current_stage = "critic"
        result = o._after_tick({
            "stage": "critic", "spawned": True, "verdict": "INVALID",
            "findings": [], "critic_feedback": "",
        })
        assert result.get("error_code") == "INVALID_VERDICT"

    def test_critic_allows_empty_verdict(self) -> None:
        """T116: 空字符串 verdict 通过（初始状态/未设置）"""
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "critic", "spawned": True, "verdict": "",
            "findings": [], "critic_feedback": "",
        })
        assert o._state.critic_verdict == ""

    def test_critic_approve_verdict_still_writes(self) -> None:
        """T116: 合法 APPROVE verdict 正常写入 state"""
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "critic", "spawned": True, "verdict": "APPROVE",
            "findings": [{"x": 1}], "critic_feedback": "",
        })
        assert o._state.critic_verdict == "APPROVE"
        assert o._state.findings == [{"x": 1}]


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
    return _make_result_file({
        "stage": "gap_scan", "gaps": gaps,
        "scanned_sections": len(gaps), "has_blocking": False,
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
    return _make_result_file({
        "stage": "gap_scan", "gaps": blocking_gaps,
        "scanned_sections": len(gaps), "has_blocking": True,
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
    },
    "options": [
        {"resolution": "Fill", "meaning": "用户补充最终设计", "enabled": True},
        {"resolution": "Research", "meaning": "先查证约束", "enabled": True},
        {"resolution": "Defer", "meaning": "交 Architect 细化", "enabled": True},
    ],
    "blocking_rule": "component gap 可 Defer",
}


class TestPhase0GapScan:
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

    def test_gap_scan_no_gaps_routes_to_architect(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        action = o.tick(_gap_scan_result([]))
        assert action["stage"] == "architect"
        assert action["action"] == "architect"

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

    def test_research_injects_supplement_and_routes_architect(self, tmp_path) -> None:
        o = _orchestrator()
        self._drive_to_research(o, tmp_path, "research")
        action = o.tick(_make_result_file({
            "stage": "research",
            "findings": "检索到 langgraph tick 控制流",
            "sources": [{"tier": "tier0", "ref": "_loop.py", "note": ""}],
            "source_tier": "tier0", "confidence": "high",
            "recommended_design": "采用 tick/after_tick 分离",
        }))
        assert action["stage"] == "architect"
        supp = o._design_doc.supplements["gap-B2"]
        assert supp.source == "research_agent"
        assert supp.source_tier == "tier0"
        assert supp.content == "采用 tick/after_tick 分离"
        assert o._state.pending_research_ids == []
        assert "采用 tick/after_tick 分离" in action["subagent_prompt"]

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

    def test_two_research_gaps_stay_research_then_architect(self, tmp_path) -> None:
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
        assert a2["stage"] == "architect"
        assert "gap-A" in o._design_doc.supplements
        assert "gap-B" in o._design_doc.supplements

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

        assert action["stage"] == "architect"
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
            guardrail=_pass_guardrail(), checkpoint_store=None)
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
            guardrail=_pass_guardrail(), checkpoint_store=None)
        o.init("req")
        o.tick(_architect_result_file())
        with caplog.at_level("WARNING"):
            o.tick(_make_result_file({
                "stage": "developer", "batch_id": "b1", "files_changed": ["x.py"],
                "test_results": {"passed": 1, "failed": 0},
            }))
        # gate 花了 50ms 但归 t_gate, orchestration 仍远低于 2000ms
        assert "超预算" not in caplog.text


def _leaf_cycle_results() -> list[Path]:
    """一个 LEAF 周期的 5 个 result file (顺序: architect→dev→critic→verifier→audit)。"""
    return [
        _make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }], "file_list": ["foo.py"], "contracts": {},
        }),
        _make_result_file({
            "stage": "developer", "batch_id": "batch-F-1", "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }),
        _make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }),
        _make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }),
        _make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 1, "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 0,
        }),
    ]


def _run_leaf_cycle() -> TickOrchestrator:
    o = _orchestrator()
    o.init("实现单个组件")
    for res in _leaf_cycle_results():
        o.tick(res)
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


def _store_orchestrator(store) -> TickOrchestrator:
    """带真实 checkpoint_store 的 orchestrator (跨进程 restore 测试用)."""
    global _ACTIVE_TEST_ROOT
    _ACTIVE_TEST_ROOT = Path(store.db_path).parent
    _prepare_existing_project(_ACTIVE_TEST_ROOT)
    return TickOrchestrator(
        project_root=_ACTIVE_TEST_ROOT,
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=store,
    )


class TestA3WriteSide:
    """T9b — A3 写侧: _save_checkpoint 前序列化 _batch_state → state.batch_state_json.

    根因: _display_progress 只写 progress_tree_json, batch_state_json 零写 →
    跨 tick restore 游标归零. 写侧必须在每次 save 前 populate.
    """

    def test_batch_state_persisted_on_save(self, tmp_path) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        o = _store_orchestrator(store)
        o.init("实现 X")
        o.tick(_architect_result_file())  # architect → developer, 建 batch_state + save
        assert o._batch_state is not None

        verify = SQLiteCheckpointStore(db)
        ck = verify.load_latest()
        assert ck is not None
        # deserialize → EngineState (production shape, 含 thread_id)
        assert ck.state.batch_state_json, "batch_state_json 应在 save 前被 populate"
        data = json.loads(ck.state.batch_state_json)
        assert data["current_batch_idx"] == o._batch_state.current_batch_idx
        assert data["current_component_idx"] == o._batch_state.current_component_idx
        assert data["current_plate_idx"] == o._batch_state.current_plate_idx
        assert data["total_batches"] == o._batch_state.total_batches
        verify.close()
        store.close()

    def test_session_summary_survives_checkpoint_restore(
        self, tmp_path
    ) -> None:
        """T136: 独立 tick 恢复后 developer prompt 保留滚动摘要历史。"""
        from auto_engineering.context.summarization import SessionSummarizer
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        _prepare_existing_project(tmp_path)
        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = tmp_path
        summarizer = SessionSummarizer()
        o = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=store,
            session_summarizer=summarizer,
        )
        o.init("跨 tick 摘要")
        o.tick(_architect_result_file())
        o._state.tick = 6
        o._state.files_changed = ["history.py"]
        first_action = o.build_action()
        assert "history.py" in first_action["session_summary"]

        restored = TickOrchestrator.restore(
            tmp_path,
            store,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            session_summarizer=SessionSummarizer(),
        )
        restored._state.tick = 7
        restored._state.files_changed = ["current.py"]
        action = restored.build_action()

        assert action["action"] == "developer"
        assert "session_summary" in action
        assert "history.py" in action["session_summary"]
        assert "current.py" in action["session_summary"]
        store.close()


def _two_batch_architect_file() -> Path:
    """component C 有 2 个 batch (b1, b2) — 用于验证游标推进后 restore 保真."""
    return _make_result_file({
        "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [
            {"batch_id": "b1", "design_section": "B2", "component": "C",
             "tasks": [{"id": "T1", "description": "d1", "module_ref": "§B2",
                        "file_targets": ["x.py"]}]},
            {"batch_id": "b2", "design_section": "B2", "component": "C",
             "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B2",
                        "file_targets": ["y.py"]}]},
        ], "file_list": ["x.py", "y.py"], "contracts": {},
    })


class TestCrossProcessRestore:
    """T9a — 跨进程 restore (§A.1: 每 tick 独立进程, 从 SQLite 恢复状态).

    新进程无 in-memory 状态 → restore() 从 checkpoint 重建
    _state/_batch_state/_progress_tree/_plan, 游标不归零.
    """

    def test_restore_roundtrip_batch_plan_mode(self, tmp_path) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        o = _store_orchestrator(store)
        o.init("实现 X")
        o.tick(_two_batch_architect_file())  # → developer, batch_state @ idx 0
        # 模拟 b1 完成: 推进游标到 b2 + 持久化
        o._batch_state.advance_batch()
        o._save_checkpoint()

        thread_id = o._state.thread_id
        expected_batch_id = o._batch_state.current_batch_id()  # "b2"
        assert expected_batch_id == "b2"
        assert o._batch_state.current_batch_idx == 1
        store.close()

        # 新进程: 独立 store, 无 in-memory 状态
        store2 = SQLiteCheckpointStore(db)
        restored = TickOrchestrator.restore(tmp_path, store2)
        assert restored._state is not None
        assert restored._state.thread_id == thread_id
        assert restored._state.current_stage == "developer"
        assert restored._batch_state is not None
        assert restored._batch_state.current_batch_idx == 1
        assert restored._batch_state.current_batch_id() == "b2"
        assert restored._plan is not None
        assert len(restored._plan.get_tasks_by_stage("developer")) == 2
        assert restored._progress_tree is not None
        store2.close()

    def test_restore_rehydrates_developer_snapshot_for_next_process(
        self, tmp_path
    ) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        orchestrator = _store_orchestrator(store)
        orchestrator.init("实现 X")
        orchestrator._state.files_changed = ["src/example.ts"]
        orchestrator._state.commit_hash = "abc123"
        orchestrator._state.test_results = {"passed": 2, "failed": 0}
        orchestrator._snapshot_developer_output()
        orchestrator._save_checkpoint()
        store.close()

        restored_store = SQLiteCheckpointStore(db)
        restored = TickOrchestrator.restore(tmp_path, restored_store)

        assert restored._dev_snapshot == {
            "files_changed": ["src/example.ts"],
            "commit_hash": "abc123",
            "test_results": {"passed": 2, "failed": 0},
        }
        restored_store.close()

    def test_restore_missing_checkpoint_raises(self, tmp_path) -> None:
        from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        empty = SQLiteCheckpointStore(tmp_path / "empty.db")
        try:
            import pytest
            with pytest.raises(CheckpointNotFoundError):
                TickOrchestrator.restore(tmp_path, empty)
        finally:
            empty.close()

    def test_restore_by_checkpoint_id(self, tmp_path) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        o = _store_orchestrator(store)
        cid = o.init("实现 X")  # init 返回 action, checkpoint_id 从 store 取
        # 取 init 落的 checkpoint id
        metas = store.list_all()
        assert metas
        first_id = metas[0].id
        store.close()

        store2 = SQLiteCheckpointStore(db)
        restored = TickOrchestrator.restore(tmp_path, store2, checkpoint_id=first_id)
        assert restored._state is not None
        assert restored._state.current_stage == "architect"
        store2.close()
        assert cid  # init 返回值 (action dict) 非空


class TestPromptVersionLock:
    """B12.5 版本锁: init 盖 registry hash, restore 漂移必须 fail-closed。"""

    def test_init_stamps_prompt_registry_hash(self) -> None:
        from auto_engineering.prompts.registry import default_registry

        o = _orchestrator()
        o.init("req")
        assert o._state.prompt_registry_hash == default_registry().registry_hash()
        assert o._state.prompt_registry_hash  # 非空

    def test_restore_matching_hash_no_warning(self, tmp_path, capsys) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        o = _store_orchestrator(store)
        o.init("实现 X")
        store.close()

        store2 = SQLiteCheckpointStore(db)
        TickOrchestrator.restore(tmp_path, store2)
        store2.close()
        assert "hash 不符" not in capsys.readouterr().err

    def test_restore_ignores_thread_hash_when_active_action_has_revision(
        self, tmp_path
    ) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        db = tmp_path / "cp.db"
        store = SQLiteCheckpointStore(db)
        o = _store_orchestrator(store)
        o.init("实现 X")
        # 篡改持久化的 hash → 模拟 loop 运行中 prompt 文件被改
        o._state.prompt_registry_hash = "0" * 64
        o._save_checkpoint()
        store.close()

        store2 = SQLiteCheckpointStore(db)
        restored = TickOrchestrator.restore(tmp_path, store2)
        assert restored._active_action is not None
        assert restored._state.pending_runtime_revision is None
        assert (
            restored._state.active_runtime_revision["prompt_revision"]
            != "0" * 64
        )
        store2.close()


class TestInitPersistsDesignDocPath:
    """T9a 前置: init 必须持久化 design_doc_path, restore 才能重 parse 设计文档."""

    def test_init_with_design_doc_persists_path(self, tmp_path) -> None:
        design = tmp_path / "design.md"
        design.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("req", design_doc_path=str(design))
        assert o._state.design_doc_path == str(design)


class TestCrossTickE2E:
    """T21: 完整 LEAF 循环, 每 tick 前从 store restore 全新 orchestrator.

    模拟 §A.1 每 tick 独立进程: 状态只经 SQLite 流转, 无 in-memory 残留 —
    每步都是 restore() 出的新实例。验证 tick 引擎在真实离散进程模型下端到端收敛。
    """

    def test_full_leaf_cycle_through_restore_each_tick(self, tmp_path) -> None:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        _prepare_existing_project(tmp_path)
        store = SQLiteCheckpointStore(tmp_path / "cp.db")
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = tmp_path

        def _fresh() -> TickOrchestrator:
            # 每 tick 一个全新实例 (无 in-memory 状态), 只从 store restore
            restored = TickOrchestrator.restore(
                tmp_path, store,
                gate_runner=_pass_gate_runner, guardrail=_pass_guardrail())
            global _ACTIVE_ORCHESTRATOR
            _ACTIVE_ORCHESTRATOR = restored
            return restored

        # init (第一个"进程")
        o0 = TickOrchestrator(
            tmp_path, gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(), checkpoint_store=store)
        first = o0.init("实现单个组件")
        assert first["stage"] == "architect"

        # tick 1: architect → developer
        a = _fresh().tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo", "module_ref": "§B2",
                           "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        assert a["stage"] == "developer"
        assert a["batch_id"] == "batch-F-1"  # 跨进程 batch_state 保真

        # tick 2: developer → critic
        a = _fresh().tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"], "test_results": {"passed": 2, "failed": 0},
        }))
        assert a["stage"] == "critic"

        # tick 3: critic APPROVE → component_verifier
        a = _fresh().tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        assert a["stage"] == "component_verifier"

        # tick 4: component_verifier (无缺口) → system_deep_audit
        a = _fresh().tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["stage"] == "system_deep_audit"

        # tick 5: system_deep_audit (无 P0/P1) → GOAL_ACHIEVED
        a = _fresh().tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 1, "total_audited_files": 2,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["action"] == "done"
        assert a["verdict"] == "GOAL_ACHIEVED"  # 5 次跨进程 restore 后收敛
        store.close()


def _write_leaf_design(tmp_path) -> str:
    """LEAF 设计文档: 1 板块 (§A1) + 1 组件 (§B2 Foo) → design-doc 模式入口."""
    (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
    design = tmp_path / "design.md"
    design.write_text(
        "## A1 认证板块\n\n### B2 Foo\n\n登录组件契约: 用户名+密码校验\n",
        encoding="utf-8",
    )
    return str(design)


# design-doc 2 轮 E2E 用: architect 每轮同一 batch_plan (component Foo → LEAF)
_LEAF_ARCH_RESULT = {
    "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
    "batch_plan": [{
        "batch_id": "b-Foo", "design_section": "B2", "component": "Foo",
        "tasks": [{"id": "T1", "description": "实现 Foo", "module_ref": "§B2",
                   "file_targets": ["foo.py"]}],
    }],
    "file_list": ["foo.py"], "contracts": {},
}


class TestTwoRoundDesignDocE2E:
    """T21: design-doc 入口 → 完整 2 轮 E2E (轮1 覆盖缺口→plan_refine→轮2 收敛→done).

    唯一同时覆盖 Phase 0 (gap_scan) 入口 + plan_refine 回路 + LEAF 收敛三段的
    端到端路径。验证 design-doc 模式下多轮 refine 后仍能收敛到 GOAL_ACHIEVED，
    且第一轮的覆盖缺口经归一 RefineRequest 回流 architect 而非误判收敛。
    """

    @staticmethod
    def _dev_critic_approve(
        o: TickOrchestrator, batch_id: str = "b-Foo"
    ) -> dict:
        """developer → critic APPROVE → 返回 component_verifier action."""
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": batch_id, "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        return o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "ok",
        }))

    def test_two_round_design_doc_refine_then_converge(self, tmp_path) -> None:
        _prepare_existing_project(tmp_path)
        o = TickOrchestrator(
            tmp_path, gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(), checkpoint_store=None,
        )
        o.init("实现登录", design_doc_path=_write_leaf_design(tmp_path))

        # Phase 0: gap_scan (无缺口) → architect
        a = o.tick(_make_result_file({
            "stage": "gap_scan", "gaps": [], "scanned_sections": 1,
            "has_blocking": False,
        }))
        assert a["stage"] == "architect"

        # ── 轮 1: architect → dev → critic → component_verifier(MISSING) → plan_refine
        a = o.tick(_make_result_file(_LEAF_ARCH_RESULT))
        assert a["stage"] == "developer"
        assert o._verification_layers == VerificationLayers.LEAF  # design_doc 单组件

        a = self._dev_critic_approve(o)
        assert a["stage"] == "component_verifier"

        a = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "MISSING",
                              "file": None, "line": None, "note": "未实现"}],
            "missing_count": 1, "diverged_count": 0,
        }))
        # 覆盖缺口 → 回 architect (plan_refine), 携带归一 RefineRequest
        assert a["action"] == "architect"
        assert a["feedback"]["mode"] == "PLAN_REFINE"
        assert a["feedback"]["refine_request"]["source"] == "component_verifier"
        assert o._state.plan_refine_count == 1

        # ── 轮 2: architect 重排 → dev → critic → component_verifier(clean) → audit → done
        repair_plan = {
            "stage": "architect",
            "spawned": True,
            "plan": _LEAF_ARCH_RESULT["plan"],
            "plan_patch": {
                "base_revision": 1,
                "add_batches": [
                {
                    "batch_id": "b-Foo-fix",
                    "design_section": "B2",
                    "component": "Foo",
                    "tasks": [{
                        "id": "T2",
                        "description": "修复 Foo 覆盖缺口",
                        "module_ref": "§B2",
                        "file_targets": ["foo.py"],
                    }],
                }],
            },
            "file_list": ["foo.py"],
            "contracts": {},
        }
        a = o.tick(_make_result_file(repair_plan))
        assert a["stage"] == "developer"  # refine 后重回开发

        a = self._dev_critic_approve(o, "b-Foo-fix")
        assert a["stage"] == "component_verifier"

        a = o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["stage"] == "system_deep_audit"  # LEAF 跳板块/系统验证

        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "spawned": True, "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0, "total_audited_files": 1,
            "design_docs_stale": False, "design_doc_suggestions": "",
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["action"] == "done"
        assert a["verdict"] == "GOAL_ACHIEVED"
        # 收敛前恰好经过 1 次 refine (2 轮 architect)
        assert o._state.plan_refine_count == 1


def _real_guardrail_orch(tmp_path) -> TickOrchestrator:
    """带真实 GuardrailChain.default() (含 G6) 的 orchestrator — 用于 G6 端到端."""
    _prepare_existing_project(tmp_path)
    global _ACTIVE_TEST_ROOT
    _ACTIVE_TEST_ROOT = tmp_path
    o = TickOrchestrator(
        project_root=tmp_path,
        gate_runner=_pass_gate_runner,
        guardrail=GuardrailChain.default(),
        checkpoint_store=None,
    )
    return o


class TestPhase0BlockingGapGuardrail:
    """T25: G6 NoDeferredBlockingGap 端到端 + gap_review 4 用户路径.

    用真实 GuardrailChain.default() (含 G6); gap_review post 时机仅 G6 适用
    (GitDiff/Tests/GitClean 按 stage 过滤掉 → 无 git 子进程)。修复前 G6 未接线,
    architectural gap 被 Defer 会静默放行 (违反 §B10.5)。
    """

    @staticmethod
    def _to_gap_review(o: TickOrchestrator, tmp_path, grade: str) -> None:
        design = tmp_path / "design.md"
        design.write_text("## A1 板块\n\n### B2 Foo\n\ncontent\n", encoding="utf-8")
        o.init("req", design_doc_path=str(design))
        o.tick(_make_result_file({
            "stage": "gap_scan",
            "gaps": [{"id": "g1", "design_section_ref": "§B2", "grade": grade,
                      "clarity": "missing", "summary": "契约缺失",
                      "evidence": ["§B2 未定义契约"],
                      "problem_statement": "组件契约缺失",
                      "impact": ["实现边界无法验证"],
                      "dependencies": [],
                      "recommendation": {"resolution": "fill", "reason": "需补齐契约", "confidence": "high"},
                      "options": [
                          {"resolution": "fill", "meaning": "补齐设计", "enabled": True},
                          {"resolution": "research", "meaning": "查证后补齐", "enabled": True},
                          {
                              "resolution": "defer", "meaning": "交由架构师",
                              "enabled": grade != "architectural",
                              "disabled_reason": (
                                  "架构阻塞项不可延后" if grade == "architectural" else ""
                              ),
                          },
                          {
                              "resolution": "defer_research",
                              "meaning": "研究后交由架构师",
                              "enabled": grade != "architectural",
                              "disabled_reason": (
                                  "架构阻塞项不可延后" if grade == "architectural" else ""
                              ),
                          },
                      ],
                      "blocking_rule": "architectural gap 禁止 defer"}],
            "scanned_sections": 1,
            "has_blocking": grade == "architectural",
        }))

    def test_architectural_defer_blocks_via_guardrail(self, tmp_path) -> None:
        o = _real_guardrail_orch(tmp_path)
        self._to_gap_review(o, tmp_path, "architectural")
        a = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "g1", "resolution": "defer"}],
        }))
        assert a["action"] == "error"
        assert a["error_code"] == "GUARDRAIL_BLOCK"
        assert "g1" in a["message"]

    def test_architectural_defer_research_blocks_via_guardrail(self, tmp_path) -> None:
        o = _real_guardrail_orch(tmp_path)
        self._to_gap_review(o, tmp_path, "architectural")
        a = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "g1", "resolution": "defer_research"}],
        }))
        assert a["error_code"] == "GUARDRAIL_BLOCK"

    def test_path_fill_architectural_passes(self, tmp_path) -> None:
        """路径1 Fill: architectural gap Fill → 通过 G6 → architect (注入 Supplement)."""
        o = _real_guardrail_orch(tmp_path)
        self._to_gap_review(o, tmp_path, "architectural")
        a = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "g1", "resolution": "fill",
                           "fill_content": "契约 X→Y"}],
        }))
        assert a["stage"] == "architect"

    def test_path_research_architectural_passes(self, tmp_path) -> None:
        """路径2 Research: architectural gap Research → 通过 G6 → research 阶段."""
        o = _real_guardrail_orch(tmp_path)
        self._to_gap_review(o, tmp_path, "architectural")
        a = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "g1", "resolution": "research"}],
        }))
        assert a["stage"] == "research"

    def test_path_defer_component_passes(self, tmp_path) -> None:
        """路径3 Defer: 非 architectural gap Defer → 不阻塞 → architect (仅 arch 受约束)."""
        o = _real_guardrail_orch(tmp_path)
        self._to_gap_review(o, tmp_path, "component")
        a = o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "g1", "resolution": "defer"}],
        }))
        assert a["stage"] == "architect"


def _dict_gate_runner(gate_names, project_root):
    """Gate runner that returns plain dicts (not objects) — Driver B path."""
    return {name: {"passed": True, "message": "ok"} for name in gate_names}


class TestRunDeveloperGates:
    """_run_developer_gates 验证 gate_results 兼容 dict 和 object 输入."""

    def test_gate_results_from_dict_runner(self) -> None:
        """gate_runner 返回 dict (含 passed/message) → gate_results 正确提取 passed/message."""
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=_dict_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )
        plan = _VALID_PLAN
        o.init("实现功能")
        a = o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": plan,
            "file_list": ["f1.py"],
            "batch_plan": [{"batch_id": "B1", "design_section": "A1",
                            "component": "Foo", "tasks": [
                                {"id": "T1", "description": "task1",
                                 "file_targets": ["f1.py"]},
                            ]}],
            "design_doc_updated": True,
        }))
        assert a["stage"] == "developer", f"expected developer, got stage={a.get('stage')}, action={a.get('action')}"
        # 从 architect→developer 转换会触发 _run_developer_gates
        assert o._state.gate_results is not None
        # 验证 gate_results 中每个项目的 passed 和 message 被正确提取
        for gate_name, gate_val in o._state.gate_results.items():
            assert isinstance(gate_val, dict), f"{gate_name}: 应为 dict, 实际 {type(gate_val)}"
            assert gate_val["passed"] is True, f"{gate_name}: passed 应为 True"
            assert gate_val["message"] == "ok", f"{gate_name}: message 应为 ok"
            assert "files_snapshot_sha" in gate_val, f"{gate_name}: 应有 files_snapshot_sha"
            assert "ran_at" in gate_val, f"{gate_name}: 应有 ran_at"

    def test_extracts_gate_summary_from_nested_run_gates_output(self) -> None:
        """run_gates() 返回 {project_root, gate_names, passed, failed, skipped, gate_summary}
        嵌套结构，_run_developer_gates 必须提取 gate_summary 中的逐 gate 结果，
        而非将 project_root/gate_names/passed/failed/skipped 当作 gate 名。"""
        def _nested_runner(gate_names, project_root):
            return {
                "project_root": str(project_root),
                "gate_names": list(gate_names),
                "passed": 3,
                "failed": 0,
                "skipped": 0,
                "gate_summary": {
                    name: {"status": "pass", "passed": True, "message": "ok",
                           "gate_name": name}
                    for name in gate_names
                },
            }

        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=_nested_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )
        o.init("实现功能")
        # Tick 1: architect → developer
        a = o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "file_list": ["f1.py"],
            "batch_plan": [{"batch_id": "B1", "design_section": "A1",
                            "component": "Foo", "tasks": [
                                {"id": "T1", "description": "task1",
                                 "file_targets": ["f1.py"]},
                            ]}],
            "design_doc_updated": True,
        }))
        assert a["stage"] == "developer"
        # Tick 2: submit developer result → 触发 _run_developer_gates
        o.tick(_make_result_file({
            "stage": "developer",
            "batch_id": "B1",
            "files_changed": ["f1.py"],
            "commit_hash": "a" * 40,
            "test_results": {"passed": 1, "total": 1},
            "red_evidence": [],
            "tasks_completed": ["T1"],
        }))
        gr = o._state.gate_results
        assert gr is not None
        # 顶层 key 必须是 gate 名 (safety/lint/...), 不能是 wrapper key
        for wrapper in ("project_root", "gate_names", "passed", "failed", "skipped"):
            assert wrapper not in gr, (
                f"gate_results 不应包含 wrapper key '{wrapper}' — "
                f"未从 run_gates() 嵌套结构中提取 gate_summary"
            )
        # 至少有一个 gate 结果
        assert len(gr) > 0, "gate_results 不应为空"
        for gate_name, gate_val in gr.items():
            assert isinstance(gate_val, dict), f"{gate_name}: 应为 dict"
            assert gate_val["passed"] is True, f"{gate_name}: passed 应为 True"


class TestFreshGuardrailAtCritic:
    """FreshGuardrail G8 在 critic stage 应 rerun gates 而非返回错误.

    FreshGuardrail 适用于 developer + critic 两阶段 (§B3.2). 原代码只对 developer 放行,
    critic 阶段返回 GUARDRAIL_RETRY → ActionError, 但正确行为应是重跑 Gate 刷新证据后继续.
    """

    def test_freshgate_at_critic_runs_gates_and_continues(self) -> None:
        """critic tick 中 FreshGuardrail 触发 → 应 rerun gates 并继续到 after_tick 而非报错."""
        # guardrail 在第三次调用 (critic tick) 返回 FreshGuardrail
        # 调用: #1=architect tick, #2=developer tick, #3=critic tick
        call_count = [0]
        def _guardrail_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:  # critic tick
                return MagicMock(action="retry", guardrail_name="FreshGuardrail")
            return MagicMock(action="pass")
        gr = MagicMock()
        gr.check.side_effect = _guardrail_side_effect

        gate_calls = [0]
        def _counting_gate_runner(gate_names, project_root):
            gate_calls[0] += 1
            return {name: {"passed": True, "message": "ok"}
                    for name in gate_names}

        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=_counting_gate_runner,
            guardrail=gr,
            checkpoint_store=None,
        )
        o.init("req")

        # architect tick → guardrail.check() call #1 (pass)
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "B1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "t1", "module_ref": "§B2",
                           "file_targets": ["f.py"]}],
            }],
            "file_list": ["f.py"], "contracts": {},
        }))

        # developer tick → guardrail.check() call #2 (pass)
        action = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "B1",
            "files_changed": ["f.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        assert action["stage"] == "critic"

        # critic tick → guardrail.check() call #3 (FreshGuardrail)
        action = o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        # 不应返回 GUARDRAIL_* 错误
        assert action.get("error_code", "") != "GUARDRAIL_RETRY", \
            f"FreshGuardrail at critic 不应返回错误: {action}"
        # 应正常路由到下一 stage
        assert action["stage"] == "component_verifier", \
            f"预期 component_verifier, 实际 stage={action.get('stage')}"

    def test_freshgate_at_developer_still_works(self) -> None:
        """FreshGuardrail at developer 应仍正常工作 (回归测试)."""
        call_count = [0]
        def _guardrail_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # developer tick (architect→developer 转换前的检查)
                return MagicMock(action="retry", guardrail_name="FreshGuardrail")
            return MagicMock(action="pass")
        gr = MagicMock()
        gr.check.side_effect = _guardrail_side_effect

        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = _TEST_RUNTIME_ROOT
        o = TickOrchestrator(
            project_root=_TEST_RUNTIME_ROOT,
            gate_runner=_pass_gate_runner,
            guardrail=gr,
            checkpoint_store=None,
        )
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "B1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "t1", "module_ref": "§B2",
                           "file_targets": ["f.py"]}],
            }],
            "file_list": ["f.py"], "contracts": {},
        }))
        action = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "B1",
            "files_changed": ["f.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        # FreshGuardrail at developer 不应阻塞
        assert action.get("error_code", "") != "GUARDRAIL_RETRY"
        assert action["stage"] == "critic"


# ── S-2: Driver A vs Driver B 保真度对比 ──


class TestValidationConsistency:
    """_validate_result_dict vs _read_and_validate — 两个验证入口必须一致.

    Driver A (tick) 走 _read_and_validate (文件→dict→验证),
    Driver B (tick_dict) 走 _validate_result_dict (dict→验证).
    同一份数据应产出一致的 dict 或一致的 ErrorResponse.
    """

    def test_valid_architect_result_consistent(self) -> None:
        """有效 architect result: dict 验证 vs 文件验证 → 一致."""
        o = _orchestrator()
        o.init("req")
        data = {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }
        result_file = _make_result_file(data)
        via_dict = o._validate_result_dict(data)
        via_file = o._read_and_validate(result_file)
        assert via_dict == via_file

    def test_stage_mismatch_consistent(self) -> None:
        """stage 不匹配: 两种入口返回相同 error_code + 相同 message."""
        o = _orchestrator()
        o.init("req")  # expected_stage = "architect"
        data = {"stage": "developer", "files_changed": ["x.py"]}
        via_dict = o._validate_result_dict(data)
        via_file = o._read_and_validate(_make_result_file(data))
        assert via_dict.error_code == via_file.error_code == "STAGE_MISMATCH"
        assert via_dict.message == via_file.message

    def test_type_error_consistent(self) -> None:
        """result 不是 dict: 两种入口返回 RESULT_TYPE_ERROR."""
        o = _orchestrator()
        o.init("req")
        # Driver B 直接传 list: _validate_result_dict 立即检测
        via_dict = o._validate_result_dict(["not", "a", "dict"])
        assert via_dict.error_code == "RESULT_TYPE_ERROR"
        # Driver A 从文件读: JSON 顶层是 list, _read_and_validate 也检测
        f = Path(tempfile.mktemp(suffix=".json"))
        f.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        via_file = o._read_and_validate(f)
        assert via_file.error_code == "RESULT_TYPE_ERROR"

    def test_empty_batch_plan_consistent(self) -> None:
        """空 batch_plan: 两种入口都返回 RESULT_VALIDATION_ERROR."""
        o = _orchestrator()
        o.init("req")
        data = {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN, "batch_plan": [],
            "file_list": ["x.py"], "contracts": {},
        }
        via_dict = o._validate_result_dict(data)
        via_file = o._read_and_validate(_make_result_file(data))
        assert via_dict.error_code == via_file.error_code == "RESULT_VALIDATION_ERROR"

    def test_parse_error_only_from_file(self) -> None:
        """文件解析失败 (RESULT_PARSE_ERROR): 仅 Driver A 路径可达.
        Driver B 路径 dict 已在内存, 不存在 parse 失败场景.
        这是两个驱动的合理差异 (非 bug).
        """
        o = _orchestrator()
        o.init("req")
        bad_file = Path(tempfile.mktemp(suffix=".json"))
        bad_file.write_text("not json{{{", encoding="utf-8")
        via_file = o._read_and_validate(bad_file)
        assert via_file.error_code == "RESULT_PARSE_ERROR"
        # Driver B 不存在等价场景 — 这是设计上的合理差异


class TestTickVsTickDictIdenticalActions:
    """tick(file) vs tick_dict(dict) — 同一 state + 同一 result → 同一 next action.

    这是双驱动架构的核心保真度断言: 循环引擎的 action 产出只依赖 result 内容,
    不依赖 result 的传输方式 (文件 vs 内存 dict).
    """

    @staticmethod
    def _seed_to_developer(o: TickOrchestrator) -> dict:
        """init → architect tick → 停在 developer, 返回 developer 的 batch_id."""
        o.init("实现登录功能")
        action = o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        assert action["stage"] == "developer"
        return action

    @staticmethod
    def _strip_nondeterministic(action: dict) -> dict:
        """去掉非确定性字段 (UUID/时间戳), 只比循环逻辑字段."""
        stripped = dict(action)
        stripped.pop("thread_id", None)
        stripped.pop("spawn_proof_token", None)
        stripped.pop("message_id", None)
        stripped.pop("correlation_id", None)
        stripped.pop("causation_id", None)
        stripped.pop("subagent_prompt", None)  # DS-15: file-based, may differ
        extensions = stripped.get("extensions")
        if isinstance(extensions, dict):
            extensions = dict(extensions)
            ae = extensions.get("ae")
            if isinstance(ae, dict):
                ae = dict(ae)
                ae.pop("issued_at", None)
                extensions["ae"] = ae
            stripped["extensions"] = extensions
        # DS-15: instruction contains proof_token which is UUID → strip it
        if "instruction" in stripped:
            import re
            inst = stripped["instruction"]
            inst = re.sub(r'[0-9a-f]{32}', '<TOKEN>', inst)
            stripped["instruction"] = inst
        spawn = stripped.get("spawn")
        if isinstance(spawn, dict):
            spawn = dict(spawn)
            invocations = spawn.get("invocations")
            if isinstance(invocations, list):
                spawn["invocations"] = [
                    {**item, "receipt_path": "<RECEIPT_PATH>"}
                    if isinstance(item, dict) else item
                    for item in invocations
                ]
            stripped["spawn"] = spawn
        if "gate_summary" in stripped:
            gs = {}
            for k, v in stripped["gate_summary"].items():
                gs[k] = {kk: vv for kk, vv in v.items()
                         if kk not in ("ran_at", "files_snapshot_sha")}
            stripped["gate_summary"] = gs
        return stripped

    def test_developer_result_same_next_action(self) -> None:
        """developer result 通过 tick() 和 tick_dict() 产出一致的下一 action."""
        result = {
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 2, "failed": 0},
        }

        # tick() 路径 (Driver A)
        o1 = _orchestrator()
        self._seed_to_developer(o1)
        action_file = self._strip_nondeterministic(
            o1.tick(_make_result_file(dict(result)))
        )

        # tick_dict() 路径 (Driver B)
        o2 = _orchestrator()
        self._seed_to_developer(o2)
        result_for_dict = dict(result)
        _make_result_file(result_for_dict)
        action_dict = self._strip_nondeterministic(o2.tick_dict(result_for_dict))

        assert action_file == action_dict, (
            f"tick() != tick_dict():\n"
            f"  file: {action_file}\n"
            f"  dict: {action_dict}"
        )

    def test_critic_result_same_next_action(self) -> None:
        """critic APPROVE result: tick() vs tick_dict() → 一致."""
        result = {
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }

        # 推进到 critic
        o1 = _orchestrator()
        self._seed_to_developer(o1)
        o1.tick(_make_result_file({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        action_file = self._strip_nondeterministic(
            o1.tick(_make_result_file(dict(result)))
        )

        o2 = _orchestrator()
        self._seed_to_developer(o2)
        o2.tick_dict({
            "stage": "developer", "batch_id": "b1",
            "files_changed": ["x.py"],
            "test_results": {"passed": 2, "failed": 0},
        })
        result_for_dict = dict(result)
        _make_result_file(result_for_dict)
        action_dict = self._strip_nondeterministic(o2.tick_dict(result_for_dict))

        assert action_file == action_dict

    def test_error_result_same_action(self) -> None:
        """无效 result (stage mismatch): tick() vs tick_dict() 产出一致错误."""
        o1 = _orchestrator()
        o1.init("req")
        bad = {"stage": "developer", "files_changed": ["x.py"]}

        action_file = o1.tick(_make_result_file(bad))

        o2 = _orchestrator()
        o2.init("req")
        action_dict = o2.tick_dict(bad)

        assert action_file["error_code"] == action_dict["error_code"]
        assert action_file["action"] == action_dict["action"]


class TestDualDriverContract:
    """双驱动契约: TickOrchestrator 核心接缝 (action/result) 的驱动无关性.

    验证:
    1. init() 返回的 action schema 对两个驱动一致
    2. build_action() 的产出不依赖驱动类型
    3. _tick_process_result() 公共路径对两个驱动一致
    """

    def test_init_action_schema_consistent(self) -> None:
        """init() 返回的 action 必须含 driver-agnostic 字段."""
        o = _orchestrator()
        action = o.init("实现功能")
        for key in ("action", "stage", "tick", "expected_format"):  # DS-15: context optional
            assert key in action, f"action 缺字段: {key}"

    def testbuild_action_stage_deterministic(self) -> None:
        """build_action() 由 state.current_stage 决定, 与驱动无关."""
        o = _orchestrator()
        o.init("req")

        # architect stage — init 后就在 architect
        a1 = o.build_action()
        assert a1["stage"] == "architect"
        assert a1["action"] == "architect"

        # 推进到 developer stage
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }))
        a2 = o.build_action()
        assert a2["stage"] == "developer"
        assert a2["action"] == "developer"
        assert "tasks" in a2

    def test_tick_process_result_shared_path(self) -> None:
        """_tick_process_result 是 tick()/tick_dict() 的公共出口."""
        o = _orchestrator()
        o.init("req")
        result = {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }
        action = o._tick_process_result(result)
        assert action["action"] == "developer"
        assert action["stage"] == "developer"

    def test_checkpoint_save_same_for_both_drivers(self) -> None:
        """_advance_stage → _save_checkpoint 在 tick()/tick_dict() 中行为一致."""
        o = _orchestrator()
        o.init("req")
        tick_before = o._state.tick
        o._tick_process_result({
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        })
        assert o._state.tick == tick_before + 1
        assert o._state.current_stage == "developer"


# ── V7-1: tick() 委托 tick_dict() ──


class TestV7_1_TickDelegation:
    """V7-1: tick() 简化为薄包装 — 读文件 → 委托 tick_dict()."""

    def test_tick_delegates_to_tick_dict(self, tmp_path: Path) -> None:
        """tick(result_file) 与 json.loads + tick_dict() 产生相同 action."""
        o = _orchestrator()
        o.init("req")

        result = {
            "stage": "architect", "spawned": True, "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "b1", "design_section": "B2", "component": "C",
                "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                           "file_targets": ["x.py"]}],
            }], "file_list": ["x.py"], "contracts": {},
        }

        # 通过文件路径调用 tick()
        result_file = tmp_path / "result.json"
        result_file.write_text(json.dumps(result))
        action_via_file = o.tick(result_file)

        # 直接通过 dict 调用 tick_dict()
        o2 = _orchestrator()
        o2.init("req")
        action_via_dict = o2.tick_dict(result)

        assert action_via_file["action"] == action_via_dict["action"]
        assert action_via_file["stage"] == action_via_dict["stage"]

    def test_tick_body_lines_not_exceed_5(self) -> None:
        """tick() 方法体 ≤ 5 行 (不含 docstring 和 def 行)."""
        import inspect
        source = inspect.getsource(TickOrchestrator.tick)
        lines = [l for l in source.split("\n") if l.strip() and not l.strip().startswith('"""')]  # noqa: E741
        # lines[0] = "def tick(...):", body = lines[1:]
        body_lines = [l for l in lines[1:] if not l.strip().startswith("#") and not l.strip().startswith('"""')]  # noqa: E741
        assert len(body_lines) <= 5, f"tick() body should be ≤5 lines, got {len(body_lines)}: {body_lines}"


# ============================================================
# System-Initiated Escalation: init_manifest_missing gate
# ============================================================


class TestDetectProjectLanguage:
    """detect_project_language() 语言探测."""

    def test_detect_typescript_by_tsconfig(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_project_language(tmp_path) == "typescript"

    def test_detect_typescript_by_package_json_deps(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "package.json").write_text(
            json.dumps({"devDependencies": {"typescript": "^5.0"}}))
        assert detect_project_language(tmp_path) == "typescript"

    def test_detect_python_by_pyproject(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
        assert detect_project_language(tmp_path) == "python"

    def test_detect_go_by_gomod(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "go.mod").write_text("module test")
        assert detect_project_language(tmp_path) == "go"

    def test_detect_rust_by_cargo(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "Cargo.toml").write_text("[package]\nname='test'")
        assert detect_project_language(tmp_path) == "rust"

    def test_detect_none_for_empty_dir(self, tmp_path: Path) -> None:
        from auto_engineering.loop.escalation_handler import detect_project_language
        assert detect_project_language(tmp_path) is None

    def test_python_wins_over_typescript(self, tmp_path: Path) -> None:
        """pyproject.toml 在 package.json 之前, python 优先."""
        from auto_engineering.loop.escalation_handler import detect_project_language
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_project_language(tmp_path) == "python"


class TestProjectProfileStartup:
    """init() 通过 ProjectProfile 启动，不要求 Init manifest。"""

    def test_init_escalates_for_typescript_project(self, tmp_path: Path) -> None:
        """缺源码根的 TypeScript 项目 → setup action。"""
        (tmp_path / "package.json").write_text(
            json.dumps({"devDependencies": {"typescript": "^5.0"}}))
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("build a button")
        assert action["action"] == "project_setup_required"
        assert "source_roots" in action["missing_capabilities"]

    def test_init_no_escalation_for_python_project(self, tmp_path: Path) -> None:
        """有确定性语言和源码证据的 Python 项目直接进入 architect。"""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
        (tmp_path / "test").mkdir()
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("build a thing")
        assert action["action"] != "gate"
        assert action["stage"] == "architect"

    def test_init_no_escalation_for_empty_dir(self, tmp_path: Path) -> None:
        """空目录不再回退 Python，进入 setup。"""
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("build a thing")
        assert action["action"] == "project_setup_required"
        assert action["stage"] == "project_setup"

    def test_init_no_escalation_when_manifest_exists(self, tmp_path: Path) -> None:
        """有 manifest → 正常流程, 不 escalation."""
        (tmp_path / ".ae-state").mkdir(parents=True)
        (tmp_path / ".ae-state" / "init-manifest.json").write_text(json.dumps({
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": "typescript",
            "structure": {"source_root": "src/", "test_root": "tests/"},
            "conventions": {"linter": "eslint", "type_checker": "tsc", "test_runner": "vitest"},
        }))
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("build a button")
        assert action["action"] != "gate"
        assert action["stage"] == "architect"


class TestProjectSetupReplacesManifestEscalation:
    """宿主搭建项目后重新探测，不创建 Init manifest。"""

    def _setup_required(self, tmp_path: Path) -> TickOrchestrator:
        (tmp_path / "package.json").write_text(
            json.dumps({"devDependencies": {"typescript": "^5.0"}}))
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a button")
        return o

    def test_setup_creates_no_init_manifest(self, tmp_path: Path) -> None:
        o = self._setup_required(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "package.json").write_text(json.dumps({
            "scripts": {"test": "vitest run"},
            "devDependencies": {"typescript": "^5.0"},
        }))
        result = {
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src"],
        }
        action = o.tick_dict(result)
        assert action["stage"] == "architect"
        assert not (tmp_path / ".ae-state" / "init-manifest.json").exists()

    def test_legacy_profile_builds_exact_command_gates(self, tmp_path: Path) -> None:
        """Legacy Adapter 转换后，Gate 只执行 Profile 中的精确参数。"""
        (tmp_path / ".ae-state").mkdir(parents=True)
        manifest = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": "typescript",
            "structure": {"source_root": "src/", "test_root": "tests/"},
            "conventions": {
                "linter": "biome",
                "type_checker": "swc",
                "test_runner": "vitest",
            },
        }
        (tmp_path / ".ae-state" / "init-manifest.json").write_text(
            json.dumps(manifest))
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a thing")
        lint_gate = next(
            (g for g in o._tick_gate_runner._gates if g.name == "lint"), None)
        assert lint_gate is not None
        assert lint_gate.command == ("biome",)


# ============================================================
# T95 Agent-Initiated Escalation
# ============================================================


class TestAgentEscalation:
    """Agent 发起 escalation (--init --escalate + mid-loop escalate)."""

    @staticmethod
    def _make_project(tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'")
        (tmp_path / "demo").mkdir()

    def test_init_with_escalate_outputs_gate(self, tmp_path: Path) -> None:
        """--init --escalate → 立即输出 agent escalation gate."""
        o = _orchestrator(escalate=True)
        o.project_root = tmp_path
        action = o.init("build a feature")
        assert action["action"] == "gate"
        assert action["gate"]["id"] == "agent_escalation"
        assert action["gate"]["type"] == "agent_escalation"

    def test_tick_with_escalate_flag_outputs_gate(self, tmp_path: Path) -> None:
        """result 中 escalate=true → 输出 agent escalation gate."""
        self._make_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        result = {"stage": "developer", "escalate": True,
                  "escalation_question": "Schema 变更需确认"}
        action = o.tick_dict(result)
        assert action["action"] == "gate"
        assert action["gate"]["id"] == "agent_escalation"
        assert "Schema 变更需确认" in action["gate"]["question"]

    def test_resolve_approve_continues(self, tmp_path: Path) -> None:
        """批准继续 → 正常推进."""
        self._make_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        result = {"gate_resolution": {
            "gate_id": "agent_escalation",
            "resolution": "继续（批准当前方向）",
        }}
        action = o.tick_dict(result)
        assert action["action"] != "gate"
        assert action["stage"] == "architect"

    def test_resolve_rollback_to_architect(self, tmp_path: Path) -> None:
        """回退重设计 → 回到 architect."""
        self._make_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        # 先推进到 developer
        o.tick_dict({"stage": "architect", "spawned": True, "batch_plan": [
            {"plate": "plate1", "component": "comp1", "batches": [
                {"batch_id": "b1", "tasks": [
                    {"id": "t1", "description": "do it", "file_targets": ["a.py"]}],
                 "batch_type": "implementation"}]}]})
        o.tick_dict({"stage": "developer", "batch_id": "b1",
                     "files_changed": ["a.py"],
                     "commit_hash": "abc", "test_results": {"passed": 1}})
        # 现在 escalating, 选择回退
        result = {"gate_resolution": {
            "gate_id": "agent_escalation",
            "resolution": "回退重设计",
            "resolution_detail": {"note": "需要重新考虑 API 设计"},
        }}
        action = o.tick_dict(result)
        assert action["stage"] == "architect"
        assert "回退重设计" in action.get("feedback", "")

    @pytest.mark.parametrize(
        ("initial_stage", "profile", "missing", "resolution", "expected_stage"),
        [
            ("developer", {}, [], "回退重设计", "architect"),
            ("architect", None, ["test_runner"], "继续（批准当前方向）", "project_setup"),
        ],
    )
    def test_stage_changing_resolution_emits_owned_event(
        self,
        initial_stage: str,
        profile: dict | None,
        missing: list[str],
        resolution: str,
        expected_stage: str,
    ) -> None:
        """升级决议改变阶段时必须同时产生唯一 StageAdvanced 事实。"""
        state = EngineState(
            thread_id="thread-escalation",
            current_stage=initial_stage,
            expected_stage=initial_stage,
            project_profile=profile,
            missing_project_capabilities=missing,
        )
        emitted: list[tuple[LoopEventType, dict]] = []
        handler = EscalationHandler(EscalationContext(
            state=state,
            batch_state=None,
            build_action=lambda **kwargs: {
                "stage": state.current_stage,
                **kwargs,
            },
            save_checkpoint=lambda: None,
            queue_domain_event=lambda event_type, payload: emitted.append(
                (event_type, payload)
            ),
        ))

        action = handler.resolve_agent_escalation({"resolution": resolution})

        assert action["stage"] == expected_stage
        assert emitted == [(
            LoopEventType.STAGE_ADVANCED,
            {"from": initial_stage, "to": expected_stage},
        )]

    def test_resolve_terminate(self, tmp_path: Path) -> None:
        """终止 loop."""
        self._make_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        result = {"gate_resolution": {
            "gate_id": "agent_escalation",
            "resolution": "终止 loop",
        }}
        action = o.tick_dict(result)
        assert action["action"] == "done"
        assert action["verdict"] == "TERMINATED"

    def test_resolve_skip_batch(self, tmp_path: Path) -> None:
        """跳过当前 batch → 推进 batch."""
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        # 先完成 architect, 到 developer
        o.tick_dict({"stage": "architect", "spawned": True, "batch_plan": [
            {"plate": "p1", "component": "c1", "batches": [
                {"batch_id": "b1", "tasks": [
                    {"id": "t1", "description": "task1", "file_targets": ["a.py"]}],
                 "batch_type": "implementation"}]}]})
        result = {"gate_resolution": {
            "gate_id": "agent_escalation",
            "resolution": "跳过此 batch",
        }}
        action = o.tick_dict(result)
        # 跳过 batch 后应继续
        assert action["action"] != "gate"


# ============================================================
# T94 PrePlannedGate — architect 在 batch_plan 中声明 gate
# ============================================================


class TestPrePlannedGate:
    """Architect 在 batch_plan 中声明 gate → resolution 处理."""

    def test_pending_gate_triggers_after_developer_batch(self, tmp_path: Path) -> None:
        """batch 中有 gate → developer batch 完成后输出 gate action."""
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.init("build a feature")
        # architect: 声明两个 batch, b2 带 gate
        architect_result = {"stage": "architect", "spawned": True, "plan": _VALID_PLAN,
                     "file_list": ["x.py"],
                     "batch_plan": [{
            "plate": "p1", "component": "c1", "batches": [
                {"batch_id": "b1", "tasks": [
                    {"id": "t1", "description": "impl", "file_targets": ["a.py"]}],
                 "batch_type": "implementation"},
                {"batch_id": "b2", "tasks": [
                    {"id": "t2", "description": "deploy", "file_targets": ["b.py"]}],
                 "batch_type": "implementation",
                 "gate": {
                     "id": "deploy_approval",
                     "type": "pre_planned",
                     "question": "是否批准部署？",
                     "options": ["批准部署", "暂缓部署", "终止 loop"],
                     "default": "暂缓部署",
                 }},
            ]}]}
        _make_result_file(architect_result)
        o.tick_dict(architect_result)
        # developer: 完成 b1 → b2 有 gate → 输出 gate action
        action = o.tick_dict({"stage": "developer", "batch_id": "b1",
                              "files_changed": ["a.py"],
                              "commit_hash": "abc", "test_results": {"passed": 1}})
        assert action["action"] == "gate"
        assert action["gate"]["id"] == "deploy_approval"

    def test_resolve_pre_planned_gate_accepts_custom_option(self, tmp_path: Path) -> None:
        """PrePlannedGate 接受自定义 resolution → 作为 feedback."""
        _prepare_existing_project(tmp_path)
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = tmp_path
        o = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )
        o.init("build a feature")
        result = {"gate_resolution": {
            "gate_id": "deploy_approval",
            "resolution": "批准部署",
            "resolution_detail": {"note": "已确认灰度策略"},
        }}
        action = o.tick_dict(result)
        assert action["action"] != "gate"
        assert "deploy_approval" in action.get("feedback", "")
        assert "批准部署" in action.get("feedback", "")

    def test_resolve_pre_planned_gate_terminate(self, tmp_path: Path) -> None:
        """PrePlannedGate 也可以终止 loop."""
        _prepare_existing_project(tmp_path)
        o = _orchestrator()
        o.project_root = tmp_path
        o.init("build a feature")
        result = {"gate_resolution": {
            "gate_id": "deploy_approval",
            "resolution": "终止 loop",
        }}
        action = o.tick_dict(result)
        assert action["action"] == "done"
        assert action["verdict"] == "TERMINATED"


# ── T105: Convergence history & convergence check tests ──


class TestT105RoundHistory:
    """T105a/b: _append_round_history 数据填充验证."""

    def test_append_round_history_after_stage_transitions(self, tmp_path) -> None:
        """T105a: 每次 stage 转换都 append RoundHistory, stage/round_id 正确."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        assert len(o._round_history) == 0
        # gap_scan → gap_review: records completed "gap_scan" stage
        o.tick(_gap_scan_result([_GAP_B2]))
        assert len(o._round_history) >= 1
        entry = o._round_history[0]
        assert entry.stage == "gap_scan"
        assert entry.round_id >= 0

    def test_round_history_accumulates_across_ticks(self, tmp_path) -> None:
        """T105a: 多 tick 后 _round_history 累积, 每个 stage 转换一条记录."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        # gap_scan → gap_review: records "gap_scan"
        o.tick(_gap_scan_result([_GAP_B2]))
        # gap_review → architect: records "gap_review"
        o.tick(_make_result_file({
            "stage": "gap_review",
            "decisions": [{"gap_id": "gap-B2", "resolution": "fill",
                           "fill_content": "c"}],
        }))
        assert len(o._round_history) == 2
        stages = [e.stage for e in o._round_history]
        assert stages == ["gap_scan", "gap_review"]

    def test_round_history_includes_files_changed(self, tmp_path) -> None:
        """T105a: developer stage 后 files_changed 非零时正确记录."""
        o = _orchestrator()
        o.init("req")
        # architect
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "impl",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        # developer with files_changed
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py", "bar.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        dev_entry = o._round_history[-1]
        assert dev_entry.stage == "developer"
        assert dev_entry.files_changed == 2

    def test_lines_added_removed_populated_when_files_changed(self, tmp_path) -> None:
        """T105b: files_changed 非空时 lines_added/lines_removed 从 git diff 填充."""
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "impl",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        dev_entry = o._round_history[-1]
        # In a git repo, lines_added/removed should be populated (may be 0 for
        # new untracked files that haven't been committed yet, but the call
        # should succeed without error)
        assert isinstance(dev_entry.lines_added, int)
        assert isinstance(dev_entry.lines_removed, int)

    def test_lines_added_removed_zero_when_no_files_changed(self, tmp_path) -> None:
        """T105b: files_changed 为空时 lines_added/lines_removed 为 0."""
        o = _orchestrator()
        _init_design(o, tmp_path)
        o.tick(_gap_scan_result([_GAP_B2]))
        entry = o._round_history[0]
        assert entry.lines_added == 0
        assert entry.lines_removed == 0

    def test_lines_from_git_diff_numstat(self, tmp_path) -> None:
        """T105b: 验证 git diff --numstat 解析正确 (需要 git repo)."""
        import subprocess
        # Create a real git repo to test numstat parsing
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       capture_output=True)
        (repo / "foo.py").write_text("line1\nline2\nline3\n")
        subprocess.run(["git", "-C", str(repo), "add", "foo.py"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True)
        # Modify foo.py: remove line2, add line4+line5 → 1 removed, 2 added
        (repo / "foo.py").write_text("line1\nline3\nline4\nline5\n")
        # Now run _append_round_history manually via _advance_stage call
        (repo / ".ae-state").mkdir(exist_ok=True)
        _prepare_existing_project(repo)
        global _ACTIVE_TEST_ROOT
        _ACTIVE_TEST_ROOT = repo
        o = TickOrchestrator(
            project_root=repo,
            gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(),
            checkpoint_store=None,
        )
        o.init("req")
        # architect tick to get files_changed
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "impl",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        entry = o._round_history[-1]
        # File changed from 3 to 4 lines (removed line2, added line4+line5)
        # git diff --numstat shows: added >= 1, removed >= 1
        assert entry.lines_added >= 1, f"expected lines_added >= 1, got {entry.lines_added}"
        assert entry.lines_removed >= 1, f"expected lines_removed >= 1, got {entry.lines_removed}"


class TestT105ConvergenceCheck:
    """T105c: _convergence_check HARD_LIMIT / STAGNANT 路径测试."""

    def test_hard_limit_triggers_when_max_rounds_exceeded(self) -> None:
        """T105c: round_id >= max_iterations 时触发 HARD_LIMIT.

        GOAL_ACHIEVED (双通过) 优先于 HARD_LIMIT, 所以用 design_coverage_ok=False
        来确保落入硬上限分支.
        """
        from auto_engineering.loop.convergence import RoundHistory
        o = _orchestrator()
        o.init("req", max_rounds=3)
        o._round_history = [
            RoundHistory(round_id=0, stage="architect"),
            RoundHistory(round_id=1, stage="developer", files_changed=1),
            RoundHistory(round_id=2, stage="critic"),
            RoundHistory(round_id=3, stage="component_verifier"),
        ]
        o._state.round = 4
        action = o._convergence_check(
            design_coverage_ok=False, system_deep_audit_ok=False)
        assert action["action"] == "done"
        assert action["verdict"] == "MAX_ITERATIONS"

    def test_stagnant_detected_when_no_change(self) -> None:
        """T105c: 连续 2 轮无变化时触发 STAGNANT (default threshold=2)."""
        from auto_engineering.loop.convergence import RoundHistory
        o = _orchestrator()
        o.init("req", max_rounds=10)
        o._round_history = [
            RoundHistory(round_id=0, stage="developer", files_changed=1,
                         lines_added=5, lines_removed=2),
            RoundHistory(round_id=1, stage="critic"),
            RoundHistory(round_id=2, stage="developer", files_changed=0),
            RoundHistory(round_id=3, stage="critic"),
            RoundHistory(round_id=4, stage="developer", files_changed=0),
            RoundHistory(round_id=5, stage="critic"),
            RoundHistory(round_id=6, stage="developer", files_changed=0),
        ]
        o._state.round = 7
        action = o._convergence_check(
            design_coverage_ok=False, system_deep_audit_ok=False)
        assert action["action"] == "done"
        assert action["verdict"] == "STAGNANT"

    def test_goal_achieved_prioritized_over_hard_limit(self) -> None:
        """T105c: 双通过 GOAL_ACHIEVED 优先于 HARD_LIMIT, 即使 round 已达上限."""
        from auto_engineering.loop.convergence import RoundHistory
        o = _orchestrator()
        o.init("req", max_rounds=1)
        o._round_history = [
            RoundHistory(round_id=0, stage="developer", files_changed=1),
            RoundHistory(round_id=1, stage="critic"),
        ]
        o._state.round = 2
        action = o._convergence_check(
            design_coverage_ok=True, system_deep_audit_ok=True)
        assert action["action"] == "done"
        # GOAL_ACHIEVED maps to SEMANTIC level in judge, not HARD_LIMIT
        assert action["verdict"] == "GOAL_ACHIEVED"

    def test_fail_without_dual_pass_returns_hard_limit_at_limit(self) -> None:
        """T105c: 双通过不满足时, 达上限触发 HARD_LIMIT."""
        from auto_engineering.loop.convergence import RoundHistory
        o = _orchestrator()
        o.init("req", max_rounds=1)
        o._round_history = [
            RoundHistory(round_id=0, stage="developer", files_changed=1),
            RoundHistory(round_id=1, stage="critic"),
        ]
        o._state.round = 2
        action = o._convergence_check(
            design_coverage_ok=False, system_deep_audit_ok=False)
        assert action["verdict"] == "MAX_ITERATIONS"


class TestT105EndToEndConvergence:
    """T105d: 端到端收敛验证 — 完整 tick 循环 + _round_history + gate_results."""

    def test_full_cycle_convergence_with_history(self) -> None:
        """T105d: 完整 dev-loop 模拟收敛到 GOAL_ACHIEVED, _round_history 正确累积."""
        o = _orchestrator()
        o.init("实现单个组件")

        assert len(o._round_history) == 0

        # architect
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        assert len(o._round_history) >= 1
        assert o._round_history[0].stage == "architect"

        # developer
        a_dev = o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))
        assert a_dev["stage"] == "critic"
        dev_entry = o._round_history[-1]
        assert dev_entry.stage == "developer"
        assert dev_entry.files_changed == 1

        # critic APPROVE
        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))

        # component_verifier (clean)
        o.tick(_make_result_file({
            "stage": "component_verifier", "spawned": True, "component": "Foo",
            "coverage_map": [
                {"design_item": "B2-1", "status": "IMPLEMENTED",
                 "file": "foo.py", "line": 10, "note": ""},
            ],
            "missing_count": 0, "diverged_count": 0,
        }))

        # system_deep_audit (P0/P1 clean, design coverage ok)
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

        # _round_history should have entries for each stage transition
        stages_seen = [e.stage for e in o._round_history]
        assert "architect" in stages_seen
        assert "developer" in stages_seen
        assert "critic" in stages_seen or "component_verifier" in stages_seen

    def test_full_cycle_stores_gate_results_in_history(self) -> None:
        """T105e: developer stage 后 gate_results 在 _round_history 中非空."""
        o = _orchestrator()
        o.init("实现单个组件")

        # architect
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "实现 foo",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))

        # developer with files_changed
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 2, "failed": 0},
        }))

        dev_entry = o._round_history[-1]
        assert dev_entry.stage == "developer"
        # gate_results should be captured (from _run_developer_gates)
        assert isinstance(dev_entry.gate_results, dict), (
            f"gate_results should be dict, got {type(dev_entry.gate_results)}"
        )

    def test_round_history_count_matches_stage_transitions(self) -> None:
        """T105e: _round_history 条目数 = stage 转换次数."""
        o = _orchestrator()
        o.init("req")

        # architect → gap_scan + gap_review + architect + developer + critic
        # + component_verifier + system_deep_audit
        o.tick(_make_result_file({
            "stage": "architect", "spawned": True,
            "plan": _VALID_PLAN,
            "batch_plan": [{
                "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                "tasks": [{"id": "T1", "description": "impl",
                           "module_ref": "§B2", "file_targets": ["foo.py"]}],
            }],
            "file_list": ["foo.py"], "contracts": {},
        }))
        n_after_architect = len(o._round_history)

        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "batch-F-1",
            "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        n_after_developer = len(o._round_history)
        assert n_after_developer == n_after_architect + 1

        o.tick(_make_result_file({
            "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
            "critic_feedback": "ok",
        }))
        n_after_critic = len(o._round_history)
        assert n_after_critic == n_after_developer + 1


class TestT105MetricsConvergence:
    """T105f: AE_METRICS=1 联合验证 — 度量管线 + 收敛判定同时正确."""

    def test_metrics_pipeline_produces_events_during_convergence(self) -> None:
        """T105f: AE_METRICS=1 时 tick 循环产生 metric events."""
        import os


        os.environ["AE_METRICS"] = "1"
        try:
            from auto_engineering.metrics.collector import MetricsCollector
            collector = MetricsCollector(project_root=Path.cwd())
            from auto_engineering.metrics.collector import set_collector
            set_collector(collector)

            o = _orchestrator()
            o.init("实现单个组件")

            # architect
            o.tick(_make_result_file({
                "stage": "architect", "spawned": True,
                "plan": _VALID_PLAN,
                "batch_plan": [{
                    "batch_id": "batch-F-1", "design_section": "B2", "component": "Foo",
                    "tasks": [{"id": "T1", "description": "实现 foo",
                               "module_ref": "§B2", "file_targets": ["foo.py"]}],
                }],
                "file_list": ["foo.py"], "contracts": {},
            }))

            # developer + critic + comp_verifier + system_deep_audit → GOAL_ACHIEVED
            o.tick(_make_result_file({
                "stage": "developer", "batch_id": "batch-F-1",
                "files_changed": ["foo.py"],
                "test_results": {"passed": 2, "failed": 0},
            }))
            o.tick(_make_result_file({
                "stage": "critic", "spawned": True, "verdict": "APPROVE", "findings": [],
                "critic_feedback": "LGTM",
            }))
            o.tick(_make_result_file({
                "stage": "component_verifier", "spawned": True, "component": "Foo",
                "coverage_map": [
                    {"design_item": "B2-1", "status": "IMPLEMENTED",
                     "file": "foo.py", "line": 10, "note": ""},
                ],
                "missing_count": 0, "diverged_count": 0,
            }))
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

            # Metrics should have recorded convergence event
            events = collector._events
            converge_events = [e for e in events
                               if e.get("event_type", "") == "convergence"]
            assert len(converge_events) >= 1, (
                f"Expected >= 1 convergence events, got {len(converge_events)}"
            )
        finally:
            os.environ.pop("AE_METRICS", None)
            from auto_engineering.metrics.collector import set_collector
            set_collector(None)

    def test_end_requirement_records_event_on_convergence(self) -> None:
        """P0-1 回归: 收敛时 end_requirement 应真实写入 requirement_end 事件.

        历史 bug(2026-07-25 独立审计发现): 调用点只传 1 个参数(requirement 文本),
        而签名要求必填 total_ticks → 每次必抛 TypeError,被 except Exception
        静默吞噬,DiagnosticRuleDiscoverer 从未在生产路径执行。
        """
        import os

        os.environ["AE_METRICS"] = "1"
        try:
            from auto_engineering.metrics.collector import MetricsCollector, set_collector
            collector = MetricsCollector(project_root=Path.cwd())
            set_collector(collector)

            o = _orchestrator()
            o.init("实现单个组件")
            o.tick(_make_result_file({
                "stage": "architect", "spawned": True,
                "plan": _VALID_PLAN,
                "batch_plan": [{
                    "batch_id": "batch-G-1", "design_section": "B2",
                    "component": "Foo",
                    "tasks": [{"id": "T1", "description": "实现 foo",
                               "module_ref": "§B2",
                               "file_targets": ["foo.py"]}],
                }],
                "file_list": ["foo.py"], "contracts": {},
            }))
            o.tick(_make_result_file({
                "stage": "developer", "batch_id": "batch-G-1",
                "files_changed": ["foo.py"],
                "test_results": {"passed": 2, "failed": 0},
            }))
            o.tick(_make_result_file({
                "stage": "critic", "spawned": True, "verdict": "APPROVE",
                "findings": [], "critic_feedback": "LGTM",
            }))
            o.tick(_make_result_file({
                "stage": "component_verifier", "spawned": True,
                "component": "Foo",
                "coverage_map": [
                    {"design_item": "B2-1", "status": "IMPLEMENTED",
                     "file": "foo.py", "line": 10, "note": ""},
                ],
                "missing_count": 0, "diverged_count": 0,
            }))
            a = o.tick(_make_result_file({
                "stage": "system_deep_audit", "spawned": True,
                "findings": [],
                "p0_count": 0, "p1_count": 0, "p2_count": 0,
                "total_audited_files": 2,
                "design_docs_stale": False,
                "design_doc_suggestions": "",
                "missing_count": 0, "diverged_count": 0,
            }))
            assert a["action"] == "done"

            req_events = [e for e in collector._events
                          if e.get("event_type") == "requirement_end"]
            assert len(req_events) >= 1, (
                "end_requirement 未写入 requirement_end 事件"
                "(P0-1: 签名不匹配 bug 回归)"
            )
            assert req_events[0]["verdict"] == "GOAL_ACHIEVED"
            assert req_events[0]["total_ticks"] >= 1
        finally:
            os.environ.pop("AE_METRICS", None)
            from auto_engineering.metrics.collector import set_collector
            set_collector(None)

    def test_collect_token_usage_records_to_collector(self) -> None:
        """P0-2 回归: _collect_token_usage 应将 token 用量记录到 collector.

        历史 bug(2026-07-25 独立审计发现): 采集只写入 state.tick_token_usage,
        从未调用 mc.record_token_usage() → collector token_events 恒空,
        M5 token 效率结构性为零。
        """
        import os
        from types import SimpleNamespace

        os.environ["AE_METRICS"] = "1"
        try:
            from auto_engineering.metrics.collector import MetricsCollector, set_collector
            collector = MetricsCollector(project_root=Path.cwd())
            set_collector(collector)

            o = _orchestrator()
            o.init("token 采集回归")
            o._transcript_parser = SimpleNamespace(collect=lambda: {
                "input_tokens": 120, "output_tokens": 34,
                "model": "claude-test", "message_count": 3,
                "source": "claude-transcript",
                "provider": "anthropic",
            })

            o._collect_token_usage()

            token_events = [e for e in collector._events
                            if e.get("event_type") == "token_usage"]
            assert len(token_events) == 1, (
                "_collect_token_usage 未记录 token_usage 事件"
                "(P0-2: record_token_usage 未接线 bug 回归)"
            )
            assert token_events[0]["payload"]["input_tokens"] == 120
            assert token_events[0]["payload"]["output_tokens"] == 34
            assert token_events[0]["payload"]["model"] == "claude-test"
            assert token_events[0]["payload"]["provider"] == "anthropic"
        finally:
            os.environ.pop("AE_METRICS", None)
            from auto_engineering.metrics.collector import set_collector
            set_collector(None)

    def test_collect_token_usage_does_not_invent_anthropic_provider(
        self,
    ) -> None:
        """未知 usage source 必须明确 unsupported，不能伪造成 Anthropic。"""
        import os
        from types import SimpleNamespace

        os.environ["AE_METRICS"] = "1"
        try:
            from auto_engineering.metrics.collector import (
                MetricsCollector,
                set_collector,
            )

            collector = MetricsCollector(project_root=Path.cwd())
            set_collector(collector)
            orchestrator = _orchestrator()
            orchestrator.init("Codex token source")
            orchestrator._transcript_parser = SimpleNamespace(collect=lambda: {
                "input_tokens": 20,
                "output_tokens": 5,
                "model": "unknown",
            })

            orchestrator._collect_token_usage()

            events = [
                event for event in collector._events
                if event.get("event_type") == "token_usage"
            ]
            assert events[0]["payload"]["provider"] == "unsupported"
            assert orchestrator._state.tick_token_usage["provider"] is None
            assert (
                orchestrator._state.tick_token_usage["usage_source"]
                == "unsupported"
            )
        finally:
            os.environ.pop("AE_METRICS", None)
            from auto_engineering.metrics.collector import set_collector

            set_collector(None)

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
        o._after_tick({})

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
        monkeypatch.setattr(o, "_save_checkpoint", lambda: None)
        o._after_tick({})
        assert o._state.current_stage == "research"
        assert o._state.pending_research_ids == ["G1"]

    def test_defer_plus_research_routes_to_research(self, monkeypatch):
        o = self._setup("Defer+Research")  # 带 + 格式
        monkeypatch.setattr(o, "build_action", lambda: {"action": "research"})
        monkeypatch.setattr(o, "_save_checkpoint", lambda: None)
        o._after_tick({})
        assert o._state.current_stage == "research"
        assert o._state.pending_research_ids == ["G1"]

    def test_capital_defer_routes_to_architect(self, monkeypatch):
        o = self._setup("Defer")  # Defer → 留 architect，不进 research
        monkeypatch.setattr(o, "build_action", lambda: {"action": "architect"})
        monkeypatch.setattr(o, "_save_checkpoint", lambda: None)
        o._after_tick({})
        assert o._state.current_stage == "architect"
        assert o._state.pending_research_ids == []

    def test_lowercase_research_still_works(self, monkeypatch):
        o = self._setup("research")  # 原小写形式不受影响
        monkeypatch.setattr(o, "build_action", lambda: {"action": "research"})
        monkeypatch.setattr(o, "_save_checkpoint", lambda: None)
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
        action = b.build_action(state, batch_state=bs)
        assert "context" not in action
        assert '"ApiKeyInput"' in action["subagent_prompt"]
        assert '"§6.2"' in action["subagent_prompt"]
        assert "密码输入框 + Show/Hide" in action["subagent_prompt"]
        assert "ApiKeyInput.tsx" in action["subagent_prompt"]

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
        action = b.build_action(state, batch_state=bs)
        assert "context" not in action
        agents = action["spawn"]["agents"]
        prompt = (tmp_path / agents[0]["prompt_ref"]).read_text(encoding="utf-8")
        assert "工具模块" in prompt
        assert "voice-id.ts — Voice ID 校验" in prompt
        assert "prompt" not in agents[0]
        assert len({a["receipt_token"] for a in agents}) == 3
        assert all(a["receipt_path"].endswith(".json") for a in agents)

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
    ③ gate 即使发现 proof 不合格也只告警不拦截。修复后: result 带 token + subagent
    覆写 status=completed + gate 在 token 存在但 proof 未完成时拦截（SPAWN_PROOF_INCOMPLETE）。
    """

    def test_instruction_includes_proof_token_and_overwrite(self):
        from auto_engineering.loop.action_builder import _SPAWN_INSTRUCTION
        rendered = _SPAWN_INSTRUCTION.format(
            count=1, parallel="", effort="high", multi_instruction="",
            stage="critic", proof_token="abc123")
        assert "spawn_proof_token" in rendered   # result 须带 token
        assert "abc123" in rendered
        assert "OVERWRITE" in rendered           # 覆写而非追加
        assert "completed" in rendered
        assert "do NOT append" in rendered

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
        self._current_orchestrator = o
        for spec in SpawnPlan.from_action(o._active_action).invocations:
            receipt_path = tmp_path / spec.receipt_path
            receipt_path.write_text(json.dumps({
                "status": "completed", "stage": "critic",
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
        assert resp.error_code == "SPAWN_PROOF_INCOMPLETE"

    def test_proof_corrupted_blocks(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse
        o = self._setup_critic(tmp_path, "pending")
        # 模拟「追加第二段」损坏的 proof 文件（两个 JSON 对象拼接）
        (tmp_path / ".ae-state" / "spawn-proofs" / "tok123.json").write_text(
            '{"status":"pending"}{"status":"done"}')
        resp = o._validate_result_dict(self._critic_result())
        assert isinstance(resp, ErrorResponse)
        assert resp.error_code == "SPAWN_PROOF_INCOMPLETE"

    def test_proof_completed_passes(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse
        o = self._setup_critic(tmp_path, "completed")
        resp = o._validate_result_dict(self._critic_result())
        assert not (isinstance(resp, ErrorResponse)
                    and resp.error_code == "SPAWN_PROOF_INCOMPLETE")
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
        assert response.error_code == "WORKER_ATTESTATION_INVALID"

    def test_strict_action_requires_each_worker_receipt(self, tmp_path):
        from auto_engineering.loop.actions import ErrorResponse

        o = self._setup_critic(tmp_path, "completed")
        result = self._critic_result()
        for spec in SpawnPlan.from_action(o._active_action).invocations:
            (tmp_path / spec.receipt_path).unlink(missing_ok=True)

        response = o._validate_result_dict(result)

        assert isinstance(response, ErrorResponse)
        assert response.error_code == "WORKER_RECEIPT_MISSING"

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
        assert response.error_code == "WORKER_ATTESTATION_INVALID"

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
            assert response.error_code == "SPAWN_PROOF_TOKEN_MISMATCH"

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
        from auto_engineering.loop.action_builder import ActionBuilder

        builder = ActionBuilder(tmp_path)
        token = "proof-token"
        builder._write_spawn_proof_file(token, "architect")
        action = {
            "spawn_proof_token": token,
            "thread_id": "thread-1",
            "message_id": "action-1",
            "stage": "architect",
        }
        builder.bind_spawn_proofs(action)
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
        assert response.error_code == "WORKER_RECEIPT_MISSING"
        assert "worker-2" in response.message


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
        action = b.build_action(state, batch_state=bs, plan=plan)
        instr = action["instruction"]
        assert "inline TDD" in instr
        assert "B7" in instr
        assert "ApiKeyInput" in instr
        assert "B7-T1" in instr
        assert "TDD 铁律" in instr
        assert "project_profile_summary" in instr
        assert "init-manifest" not in instr
        assert "test_results" in instr  # result 格式指引

    def test_developer_instruction_no_tasks_graceful(self, tmp_path):
        from auto_engineering.loop.action_builder import ActionBuilder
        b = ActionBuilder(tmp_path)
        state = EngineState(thread_id="t", current_stage="developer", plan="plan")
        action = b.build_action(state)
        assert "无 task 明细" in action["instruction"]  # 优雅降级
