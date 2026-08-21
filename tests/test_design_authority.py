"""Phase 82 T437：设计权威层级。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.design_authority import (
    DesignAuthorityError,
    DesignAuthorityPolicy,
    DesignChangeRequest,
    DesignSourceAuthority,
)
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from auto_engineering.prompts.architect_context import (
    build_architect_research_context,
)


def test_only_explicit_design_and_approved_change_are_binding() -> None:
    policy = DesignAuthorityPolicy.default()

    assert policy.authority_for("explicit_design") is DesignSourceAuthority.BINDING
    assert policy.authority_for("approved_change") is DesignSourceAuthority.BINDING
    assert policy.authority_for("research") is DesignSourceAuthority.ADVISORY
    assert policy.authority_for("agent_assumption") is DesignSourceAuthority.ADVISORY
    assert policy.to_dict()["change_policy"] == "user_gate_required"


def test_research_cannot_promote_itself_to_binding_change() -> None:
    policy = DesignAuthorityPolicy.default()

    with pytest.raises(DesignAuthorityError, match="DESIGN_AUTHORITY_ESCALATION"):
        policy.validate_change(source="research", requested_authority="binding")


def test_design_change_request_builds_deterministic_user_gate() -> None:
    request = DesignChangeRequest.from_dict({
        "source": "research",
        "source_ref": "gap-1",
        "requested_authority": "binding",
        "change_summary": "由纯前端改为 BFF",
        "affected_design_refs": ["§4.1"],
    })

    gate = request.to_gate()

    assert gate["id"] == f"design_change:{request.request_id}"
    assert gate["reason_code"] == "DESIGN_CHANGE_APPROVAL_REQUIRED"
    assert gate["change"]["source_ref"] == "gap-1"
    assert len(gate["change"]["proposed_change_sha256"]) == 64
    assert [item["id"] for item in gate["options"]] == ["approve", "preserve"]


def test_redundant_change_request_for_approved_supplement_reissues_architect(
    tmp_path,
) -> None:
    orchestrator = _orchestrator_at_design_gate(
        tmp_path,
        DesignChangeRequest.from_dict({
            "source": "research",
            "source_ref": "unused",
            "requested_authority": "binding",
            "change_summary": "unused",
            "affected_design_refs": ["§1"],
        }),
    )
    orchestrator._state.design_supplements_json = (
        '{"GAP-M1":{"source":"user","content":"已批准格式补充"}}'
    )
    orchestrator._active_action = {"message_id": "architect-action-1"}

    action = orchestrator._tick_process_result({
        "design_change_requests": [{
            "source": "research",
            "source_ref": "GAP-M1",
            "requested_authority": "binding",
            "change_summary": "再次请求同一格式补充",
            "affected_design_refs": ["§6.5"],
        }]
    })

    assert action["action"] == "architect"
    assert "已经批准" in action["feedback"]
    assert "design_change" not in action


def test_architect_context_preserves_approved_supplement_authority() -> None:
    entries = build_architect_research_context(
        '{"gap-1":{"source":"user","content":"用户批准补齐错误契约"}}',
        {"gap-2": {"recommended_design": "改为服务端"}},
    )

    by_gap = {entry["gap_id"]: entry for entry in entries}
    assert by_gap["gap-1"]["authority"] == "binding"
    assert by_gap["gap-1"]["change_policy"] == "already_approved"
    assert by_gap["gap-2"]["authority"] == "advisory"
    assert by_gap["gap-2"]["change_policy"] == "user_gate_required"


def _orchestrator_at_design_gate(tmp_path, request: DesignChangeRequest):
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    orchestrator = TickOrchestrator(
        gate_runner=lambda names, root: {},
        guardrail=guardrail,
        checkpoint_store=None,
    )
    orchestrator.project_root = tmp_path
    orchestrator._state = EngineState(
        thread_id="thread-1",
        current_stage="architect",
        expected_stage="architect",
    )
    orchestrator._active_action = {
        "message_id": "gate-action-1",
        "gate": request.to_gate(),
    }
    orchestrator._current_result_message_id = "approval-result-1"
    orchestrator._current_result_causation_id = "gate-action-1"
    return orchestrator


def test_design_gate_approval_records_source_bound_event(tmp_path) -> None:
    request = DesignChangeRequest.from_dict({
        "source": "research",
        "source_ref": "gap-1",
        "requested_authority": "binding",
        "change_summary": "由纯前端改为 BFF",
        "affected_design_refs": ["§4.1"],
    })
    orchestrator = _orchestrator_at_design_gate(tmp_path, request)

    action = orchestrator._tick_process_result({
        "gate_resolution": {
            "gate_id": f"design_change:{request.request_id}",
            "resolution": "批准变更",
        }
    })

    assert action["action"] == "architect"
    event = orchestrator._pending_domain_events[-1]
    assert event.event_type is LoopEventType.GATE_RESOLVED
    assert event.payload["source_ref"] == "gap-1"
    assert event.payload["proposed_change_sha256"] == request.proposed_change_sha256


def test_design_gate_preserve_does_not_create_approval(tmp_path) -> None:
    request = DesignChangeRequest.from_dict({
        "source": "research",
        "source_ref": "gap-1",
        "requested_authority": "binding",
        "change_summary": "改变原设计",
        "affected_design_refs": ["§4.1"],
    })
    orchestrator = _orchestrator_at_design_gate(tmp_path, request)

    action = orchestrator._tick_process_result({
        "gate_resolution": {
            "gate_id": f"design_change:{request.request_id}",
            "resolution": "保留原设计",
        }
    })

    assert action["action"] == "architect"
    assert "保留原设计" in action["feedback"]
    assert all(
        event.event_type is not LoopEventType.GATE_RESOLVED
        for event in orchestrator._pending_domain_events
    )
