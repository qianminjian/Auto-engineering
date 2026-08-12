from __future__ import annotations

from auto_engineering.engine.design_doc import Component, DesignDoc, Plate
from auto_engineering.engine.state import EngineState
from auto_engineering.loop import architecture_baseline as baseline_module
from auto_engineering.loop.architect_validation import (
    dry_run_architect_plan,
    validate_architect_obligations,
)
from auto_engineering.loop.architecture_baseline import build_architecture_baseline
from auto_engineering.loop.stage_router import clear_stage_fields


def _baseline() -> dict:
    return build_architecture_baseline(
        revision=1,
        design_doc_path="design/spec.md",
        design_doc_digest="a" * 64,
        plan="实现服务端边界",
        batch_plan=[{"batch_id": "B1", "tasks": []}],
        contracts={"clone": {"path": "/api/clone", "method": "POST"}},
        obligations=[{"id": "O1", "source_ref": "gap-1"}],
        accepted_at_tick=9,
    )


def test_architecture_baseline_digest_is_stable_and_content_bound() -> None:
    first = _baseline()
    second = _baseline()
    changed = build_architecture_baseline(
        revision=1,
        design_doc_path="design/spec.md",
        design_doc_digest="a" * 64,
        plan="不同计划",
        batch_plan=[{"batch_id": "B1", "tasks": []}],
        contracts={"clone": {"path": "/api/clone", "method": "POST"}},
        obligations=[{"id": "O1", "source_ref": "gap-1"}],
        accepted_at_tick=9,
    )

    assert first == second
    assert first["baseline_id"] != changed["baseline_id"]


def test_architecture_baseline_survives_stage_clear_and_round_trip() -> None:
    state = EngineState(
        current_stage="architect",
        plan="临时计划",
        contracts={"temporary": {}},
        architecture_baseline=_baseline(),
    )

    clear_stage_fields(state, "architect")
    restored = EngineState.from_dict(state.to_dict())

    assert state.plan == ""
    assert state.contracts == {}
    assert restored.architecture_baseline == _baseline()


def test_research_requires_implementation_and_verification_obligation() -> None:
    result = {
        "batch_plan": [{
            "batch_id": "B1",
            "tasks": [
                {"id": "T1", "kind": "implementation", "file_targets": ["src/a.ts"]},
                {"id": "T2", "kind": "contract_test", "file_targets": ["tests/a.ts"]},
            ],
        }],
        "contracts": {"api": {"path": "/api/a"}},
        "obligations": [{
            "id": "O1",
            "source_ref": "gap-1",
            "implementation_targets": ["T1"],
            "verification_targets": ["T2"],
            "contract_refs": ["api"],
        }],
    }

    assert validate_architect_obligations(result, {"gap-1": {}}) is None
    assert "gap-1" in (
        validate_architect_obligations({**result, "obligations": []}, {"gap-1": {}})
        or ""
    )


def test_architect_contract_values_must_be_objects() -> None:
    result = {
        "batch_plan": [],
        "contracts": {"api": "POST /api/a"},
        "obligations": [],
    }

    assert "api" in (validate_architect_obligations(result, {}) or "")


def test_architect_accepts_custom_title_with_multiple_valid_plate_keys() -> None:
    doc = DesignDoc(
        plates=[Plate(
            name="核心",
            design_section="§1",
            components=[
                Component(name="类型系统", design_section="§4"),
                Component(name="工具模块", design_section="§8"),
            ],
        )],
        supplements={},
    )
    result = {
        "plan": "以类型系统和工具模块作为基础批次，先建立共享契约与验证边界，再供后续业务组件稳定复用。",
        "file_list": ["src/base.ts", "tests/base.test.ts"],
        "batch_plan": [{
            "batch_id": "B1",
            "batch_title": "自定义基础能力批次",
            "plate_keys": ["类型系统", "工具模块"],
            "design_sections": ["§4", "§8"],
            "tasks": [
                {
                    "id": "B1-T1", "description": "实现基础能力",
                    "kind": "implementation", "module_ref": "§4",
                    "file_targets": ["src/base.ts"], "depends_on": [],
                },
                {
                    "id": "B1-T2", "description": "验证基础能力",
                    "kind": "test", "module_ref": "§4",
                    "file_targets": ["tests/base.test.ts"],
                    "depends_on": ["B1-T1"],
                },
            ],
            "depends_on": [],
        }],
        "contracts": {},
        "obligations": [],
    }

    assert dry_run_architect_plan(doc, result, "实现基础能力") is None


def _refine_baseline() -> dict:
    return build_architecture_baseline(
        revision=1,
        design_doc_path="design/spec.md",
        design_doc_digest="a" * 64,
        plan="实现基础能力",
        batch_plan=[{
            "batch_id": "B1",
            "tasks": [
                {"id": "B1-T1", "kind": "implementation"},
                {"id": "B1-T2", "kind": "test"},
            ],
        }],
        contracts={},
        obligations=[{
            "id": "O1",
            "source_ref": "gap-1",
            "summary": "基础义务",
            "implementation_targets": ["B1-T1"],
            "verification_targets": ["B1-T2"],
            "contract_refs": [],
        }],
        accepted_at_tick=1,
    )


def _refine_result() -> dict:
    return {
        "plan_patch": {
            "base_revision": 1,
            "add_batches": [{
                "batch_id": "B2",
                "tasks": [
                    {"id": "B2-T1", "kind": "implementation"},
                    {"id": "B2-T2", "kind": "test"},
                ],
            }],
        },
        "contracts": {},
        "obligations": [],
    }


def test_refine_candidate_inherits_baseline_obligations() -> None:
    error = dry_run_architect_plan(
        None,
        _refine_result(),
        "修复差异",
        {"gap-1": {}},
        active_revision=1,
        current_baseline=_refine_baseline(),
    )

    assert error is None


def test_refine_candidate_explicitly_extends_obligation_by_source_ref() -> None:
    result = _refine_result()
    result["plan_patch"]["obligation_updates"] = [{
        "source_ref": "gap-1",
        "add_implementation_targets": ["B2-T1"],
        "add_verification_targets": ["B2-T2"],
        "add_contract_refs": [],
    }]

    error = dry_run_architect_plan(
        None,
        result,
        "修复差异",
        {"gap-1": {}},
        active_revision=1,
        current_baseline=_refine_baseline(),
    )

    assert error is None


def test_contract_activates_only_after_all_implementation_targets_reached() -> None:
    select_active_contracts = getattr(
        baseline_module, "select_active_contracts", None
    )
    assert callable(select_active_contracts), "缺少 contract 义务激活选择器"
    baseline = build_architecture_baseline(
        revision=1,
        design_doc_path="design/spec.md",
        design_doc_digest="a" * 64,
        plan="先定义 DTO，再实现 HTTP route",
        batch_plan=[
            {"batch_id": "B1", "tasks": [{"id": "B1-T1"}]},
            {"batch_id": "B2", "tasks": [{"id": "B2-T1"}]},
        ],
        contracts={"clone": {"kind": "http", "path": "/api/clone"}},
        obligations=[{
            "id": "O1",
            "source_ref": "gap-1",
            "implementation_targets": ["B1-T1", "B2-T1"],
            "verification_targets": ["B2-T2"],
            "contract_refs": ["clone"],
        }],
        accepted_at_tick=1,
    )

    assert select_active_contracts(baseline, {"B1"}) == {}
    assert select_active_contracts(baseline, {"B1", "B2"}) == {
        "clone": {"kind": "http", "path": "/api/clone"}
    }


def test_unbound_legacy_contract_remains_immediately_active() -> None:
    select_active_contracts = getattr(
        baseline_module, "select_active_contracts", None
    )
    assert callable(select_active_contracts), "缺少 contract 义务激活选择器"
    baseline = _baseline()

    assert select_active_contracts(baseline, set()) == baseline["contracts"]
