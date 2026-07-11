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

from auto_engineering.engine.verification_layers import VerificationLayers
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.tick_orchestrator import ORCH_BUDGET_MS, TickOrchestrator


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    g = MagicMock()
    g.check.return_value = MagicMock(action="pass")
    return g


def _orchestrator(max_rounds: int = 10) -> TickOrchestrator:
    return TickOrchestrator(
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=None,
    )


def _make_result_file(data: dict) -> Path:
    f = Path(tempfile.mktemp(suffix=".json"))
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


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
        assert "requirement" in action["context"]
        assert action["context"]["requirement"] == "实现登录功能"

    def test_init_sets_expected_stage(self) -> None:
        o = _orchestrator()
        o.init("req")
        assert o._state.expected_stage == "architect"

    def test_init_with_design_doc_starts_gap_scan(self, tmp_path) -> None:
        (tmp_path / ".ae-state").mkdir(parents=True, exist_ok=True)
        design = tmp_path / "design.md"
        design.write_text("## B2 StageRouter\n\ncontent\n", encoding="utf-8")
        o = _orchestrator()
        o.project_root = tmp_path
        action = o.init("req", design_doc_path=str(design))
        assert action["stage"] == "gap_scan"
        assert action["action"] == "gap_scan"
        assert "gaps" in action["expected_format"]
        assert o._design_doc is not None


# ── tick: architect → developer ──


class TestTickArchitectToDeveloper:
    def test_architect_result_builds_batch_state_and_advances(self) -> None:
        o = _orchestrator()
        o.init("实现 StageRouter")
        # feed nested batch_plan architect result
        r = _make_result_file({
            "stage": "architect",
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
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [],
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
            "stage": "architect",
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
            "stage": "architect",
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
    def test_full_leaf_cycle_reaches_goal_achieved(self) -> None:
        """LEAF: architect→dev→critic→comp_verifier→system_deep_audit→GOAL_ACHIEVED."""
        o = _orchestrator()
        o.init("实现单个组件")

        # 1. architect
        o.tick(_make_result_file({
            "stage": "architect",
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        assert a_critic["stage"] == "component_verifier"

        # 4. component_verifier (all covered, no gaps)
        a_verifier = o.tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
            "coverage_map": [
                {"design_item": "B2-1", "status": "IMPLEMENTED",
                 "file": "foo.py", "line": 10, "note": ""},
            ],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a_verifier["stage"] == "system_deep_audit"

        # 5. system_deep_audit (no P0/P1, design_coverage_ok)
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit",
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "ok",
        }))
        assert a_critic["stage"] == "component_verifier"
        return o.tick(_make_result_file({
            "stage": "component_verifier", "component": component,
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "plate_deep_audit", "plate": "(single)", "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "cross_component_issues": [], "total_audited_files": 2,
        }))
        assert a_plate["stage"] == "system_deep_audit"

        # system_deep_audit clean → GOAL_ACHIEVED
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "plate_deep_audit", "plate": "(single)", "findings": [],
            "p0_count": 0, "p1_count": 0, "p2_count": 0,
            "cross_component_issues": [], "total_audited_files": 2,
        }))
        assert a_plate["stage"] == "system_verifier"

        # system_verifier clean → system_deep_audit
        a_sysv = o.tick(_make_result_file({
            "stage": "system_verifier",
            "full_coverage_map": [{"design_section": "B2", "status": "IMPLEMENTED"}],
            "total_design_items": 1, "covered_count": 1,
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a_sysv["stage"] == "system_deep_audit"

        # system_deep_audit clean → GOAL_ACHIEVED
        a_audit = o.tick(_make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        return o.tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
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
            "stage": "system_deep_audit", "findings": [],
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
            "stage": "system_deep_audit", "findings": [],
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
            "stage": "architect",
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
            "stage": "critic", "verdict": "MAJOR",
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
            "stage": "architect",
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
            "stage": "critic", "verdict": "INVALID", "findings": [],
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
            "stage": "architect",
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        a1 = o.tick(_make_result_file({
            "stage": "component_verifier", "component": "C",
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
            "stage": "architect",
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "component": "C",
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
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        return o.tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "plate_deep_audit", "plate": "(single)",
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

    def test_plate_audit_recounts_not_trusting_inflated_agent_count(self) -> None:
        """B6.7a: Agent 自报 p1_count 膨胀但去重后 ≤ 阈值 → 不误触发 plan_refine."""
        o = _orchestrator(max_rounds=30)
        self._seed_two_component_plate(o)
        TestPlateConvergence._approve_component(o, "Foo", "b-Foo")
        a_bar = TestPlateConvergence._approve_component(o, "Bar", "b-Bar")
        assert a_bar["stage"] == "plate_deep_audit"
        dup = {"severity": "P1", "dimension": "code_quality",
               "file": "foo.py", "line": 5, "description": "同一 P1", "suggested_fix": "fix"}
        a = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "plate": "(single)",
            "findings": [
                {**dup, "agent_source": "architecture"},
                {**dup, "agent_source": "code_quality"},  # 同一问题, 去重后 1 条
            ],
            "p0_count": 0, "p1_count": 99,  # Agent 膨胀自报
            "p2_count": 0, "total_audited_files": 2, "cross_component_issues": [],
        }))
        # 去重后仅 1 条 P1 ≤ 阈值 6 → 推进到 system_deep_audit (非 architect refine)
        assert a["stage"] == "system_deep_audit"

    def test_plate_audit_recount_detects_p0_despite_agent_zero_count(self) -> None:
        """B6.7a: Agent 漏报 p0_count=0 但 findings 含 P0 → Python 重算触发 plan_refine."""
        o = _orchestrator(max_rounds=30)
        self._seed_two_component_plate(o)
        TestPlateConvergence._approve_component(o, "Foo", "b-Foo")
        a_bar = TestPlateConvergence._approve_component(o, "Bar", "b-Bar")
        assert a_bar["stage"] == "plate_deep_audit"
        a = o.tick(_make_result_file({
            "stage": "plate_deep_audit", "plate": "(single)",
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
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "component": "C",
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
            "stage": "architect", "plan": _VALID_PLAN,
            "batch_plan": batch_plan_v1,
            "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": first_batch,
            "files_changed": ["foo.py"], "test_results": {"passed": 1, "failed": 0},
        }))
        o.tick(_make_result_file({
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        a = o.tick(_make_result_file({
            "stage": "component_verifier", "component": first_comp,
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

        # architect v2 (PLAN-REFINE): 保留 Foo + 新增 Bar
        o.tick(_make_result_file({
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [
                {"batch_id": "b1", "design_section": "B2", "component": "Foo",
                 "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                            "file_targets": ["foo.py"]}]},
                {"batch_id": "b2", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ], "file_list": ["foo.py", "bar.py"], "contracts": {},
        }))
        names_after = {n.name for n in o._progress_tree.nodes.values()}
        assert "Foo" in names_after  # 增量: 旧节点保留
        assert "Bar" in names_after  # added

    def test_refine_marks_dropped_component_removed_not_deleted(self) -> None:
        o = _orchestrator(max_rounds=20)
        self._refine_to_architect(o, [
            {"batch_id": "b1", "design_section": "B2", "component": "Foo",
             "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                        "file_targets": ["foo.py"]}]},
            {"batch_id": "b2", "design_section": "B3", "component": "Bar",
             "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B3",
                        "file_targets": ["bar.py"]}]},
        ])
        # architect v2: 丢掉 Foo, 只剩 Bar
        o.tick(_make_result_file({
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [
                {"batch_id": "b2", "design_section": "B3", "component": "Bar",
                 "tasks": [{"id": "T2", "description": "d2", "module_ref": "§B3",
                            "file_targets": ["bar.py"]}]},
            ], "file_list": ["bar.py"], "contracts": {},
        }))
        foo_nodes = [n for n in o._progress_tree.nodes.values() if n.name == "Foo"]
        assert len(foo_nodes) == 1  # 未删除
        assert foo_nodes[0].design_status == "removed"  # 标记 removed


class TestVerifierRecheck:
    """T26c/DS-9 (B6.6a): Haiku verifier action 携带 Sonnet 窄范围复核指令.

    负判定 (MISSING/DIVERGED) 触发 Sonnet 二次确认, 消除假阳无谓 plan_refine.
    """

    def test_component_verifier_action_carries_recheck(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
        }))
        assert a["stage"] == "component_verifier"
        rc = a["recheck"]
        assert rc["enabled"] is True
        assert rc["trigger"] == "on_negative"
        assert rc["scope"] == "narrow"
        assert "sonnet" in rc["model"].lower()

    def test_system_verifier_action_carries_recheck(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._state.current_stage = "system_verifier"
        a = o._build_action()
        assert a["stage"] == "system_verifier"
        rc = a["recheck"]
        assert rc["enabled"] is True
        assert rc["trigger"] == "on_negative"
        assert "sonnet" in rc["model"].lower()

    def test_non_verifier_action_has_no_recheck(self) -> None:
        # architect action 无 recheck (仅 Haiku verifier 需要)
        o = _orchestrator()
        a = o.init("req")
        assert a["stage"] == "architect"
        assert "recheck" not in a


# ── _build_action context checks ──


class TestBuildActionContexts:
    def test_architect_action_has_expected_format(self) -> None:
        o = _orchestrator()
        a = o.init("req")
        assert "expected_format" in a
        assert "batch_plan" in a["expected_format"]

    def test_developer_action_has_tasks(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect",
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

    def test_critic_action_has_context_fields(self) -> None:
        o = _orchestrator()
        o.init("req")
        o.tick(_make_result_file({
            "stage": "architect",
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
        # developer 完成后进入 critic, context 含快照的开发信息
        assert action["action"] == "critic"
        assert action["stage"] == "critic"
        assert action["context"]["files_changed"] == ["x.py"]
        assert action["context"]["batch_id"] == "b1"


# ── T7: _apply_result_to_state (result → EngineState) ──


def _seed_architect(o: TickOrchestrator) -> None:
    """init + architect tick → 建立 batch_state + progress_tree, 进入 developer."""
    o.init("req")
    o.tick(_make_result_file({
        "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "critic", "verdict": "APPROVE",
            "findings": [{"x": 1}], "critic_feedback": "ok",
        })
        assert o._state.critic_verdict == "APPROVE"
        assert o._state.findings == [{"x": 1}]
        assert o._state.critic_feedback == "ok"

    def test_component_verifier_writes_coverage_map(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "component_verifier",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED"}],
        })
        assert o._state.coverage_map == [
            {"design_item": "B2-1", "status": "IMPLEMENTED"}]

    def test_system_verifier_maps_full_coverage_to_coverage_map(self) -> None:
        o = _orchestrator()
        o.init("req")
        o._apply_result_to_state({
            "stage": "system_verifier",
            "full_coverage_map": [{"design_section": "B2", "status": "IMPLEMENTED"}],
        })
        assert o._state.coverage_map == [
            {"design_section": "B2", "status": "IMPLEMENTED"}]


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
            "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        o.tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
    o.project_root = tmp_path
    o.init("req", design_doc_path=str(design))


def _gap_scan_result(gaps: list[dict]) -> Path:
    return _make_result_file({
        "stage": "gap_scan", "gaps": gaps,
        "scanned_sections": len(gaps), "has_blocking": False,
    })


_GAP_B2 = {"id": "gap-B2", "design_section_ref": "§B2", "grade": "component",
           "clarity": "vague", "summary": "边界未定义", "depends_on": []}


class TestPhase0GapScan:
    def test_gap_scan_with_gaps_routes_to_gap_review(self, tmp_path) -> None:
        o = _orchestrator()
        _init_design(o, tmp_path)
        action = o.tick(_gap_scan_result([_GAP_B2]))
        assert action["stage"] == "gap_review"
        assert action["action"] == "gap_review"
        assert action["gaps"][0]["id"] == "gap-B2"

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
        # architect action 携带 supplements (下游消费)
        assert "gap-B2" in action["context"]["design_supplements"]

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
        assert "gap-B2" in action["context"]["design_supplements"]

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
        assert "gap-B2" in action["context"]["research_archive"]

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
        gap_a = {"id": "gap-A", "design_section_ref": "§B2", "grade": "component",
                 "clarity": "vague", "summary": "a", "depends_on": []}
        gap_b = {"id": "gap-B", "design_section_ref": "§B3", "grade": "component",
                 "clarity": "vague", "summary": "b", "depends_on": []}
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
        action = o._build_action()
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


# ── #30 / DS-10 (C.2.6): tick 延迟打点 (超预算告警不中断) ──


def _architect_result_file() -> Path:
    return _make_result_file({
        "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [{
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
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }),
        _make_result_file({
            "stage": "component_verifier", "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }),
        _make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
    return TickOrchestrator(
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


def _two_batch_architect_file() -> Path:
    """component C 有 2 个 batch (b1, b2) — 用于验证游标推进后 restore 保真."""
    return _make_result_file({
        "stage": "architect", "plan": _VALID_PLAN, "batch_plan": [
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
    """B12.5 版本锁: init 盖 registry hash, restore 校验漂移 (警告非致命)."""

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

    def test_restore_mismatched_hash_warns(self, tmp_path, capsys) -> None:
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
        TickOrchestrator.restore(tmp_path, store2)
        store2.close()
        assert "hash 不符" in capsys.readouterr().err


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

        store = SQLiteCheckpointStore(tmp_path / "cp.db")

        def _fresh() -> TickOrchestrator:
            # 每 tick 一个全新实例 (无 in-memory 状态), 只从 store restore
            return TickOrchestrator.restore(
                tmp_path, store,
                gate_runner=_pass_gate_runner, guardrail=_pass_guardrail())

        # init (第一个"进程")
        o0 = TickOrchestrator(
            tmp_path, gate_runner=_pass_gate_runner,
            guardrail=_pass_guardrail(), checkpoint_store=store)
        first = o0.init("实现单个组件")
        assert first["stage"] == "architect"

        # tick 1: architect → developer
        a = _fresh().tick(_make_result_file({
            "stage": "architect", "plan": _VALID_PLAN,
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
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "LGTM",
        }))
        assert a["stage"] == "component_verifier"

        # tick 4: component_verifier (无缺口) → system_deep_audit
        a = _fresh().tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["stage"] == "system_deep_audit"

        # tick 5: system_deep_audit (无 P0/P1) → GOAL_ACHIEVED
        a = _fresh().tick(_make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
    "stage": "architect", "plan": _VALID_PLAN,
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
    def _dev_critic_approve(o: TickOrchestrator) -> dict:
        """developer → critic APPROVE → 返回 component_verifier action."""
        o.tick(_make_result_file({
            "stage": "developer", "batch_id": "b-Foo", "files_changed": ["foo.py"],
            "test_results": {"passed": 1, "failed": 0},
        }))
        return o.tick(_make_result_file({
            "stage": "critic", "verdict": "APPROVE", "findings": [],
            "critic_feedback": "ok",
        }))

    def test_two_round_design_doc_refine_then_converge(self, tmp_path) -> None:
        o = _orchestrator(max_rounds=20)
        o.project_root = tmp_path
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
            "stage": "component_verifier", "component": "Foo",
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
        a = o.tick(_make_result_file(_LEAF_ARCH_RESULT))
        assert a["stage"] == "developer"  # refine 后重回开发

        a = self._dev_critic_approve(o)
        assert a["stage"] == "component_verifier"

        a = o.tick(_make_result_file({
            "stage": "component_verifier", "component": "Foo",
            "coverage_map": [{"design_item": "B2-1", "status": "IMPLEMENTED",
                              "file": "foo.py", "line": 10, "note": ""}],
            "missing_count": 0, "diverged_count": 0,
        }))
        assert a["stage"] == "system_deep_audit"  # LEAF 跳板块/系统验证

        a = o.tick(_make_result_file({
            "stage": "system_deep_audit", "findings": [],
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
    o = TickOrchestrator(
        gate_runner=_pass_gate_runner,
        guardrail=GuardrailChain.default(),
        checkpoint_store=None,
    )
    o.project_root = tmp_path
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
                      "clarity": "missing", "summary": "契约缺失", "depends_on": []}],
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
