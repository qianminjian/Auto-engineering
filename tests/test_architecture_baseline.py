from __future__ import annotations

from auto_engineering.engine.state import EngineState
from auto_engineering.loop import architecture_baseline as baseline_module
from auto_engineering.loop.architect_validation import validate_architect_obligations
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
