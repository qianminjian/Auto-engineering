"""Phase 54 T254：StageHandler 契约与唯一注册。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from auto_engineering.loop.stages.base import (
    StageHandler,
    StageName,
    TransitionContext,
    TransitionDecision,
)
from auto_engineering.loop.stages.registry import (
    DuplicateStageHandlerError,
    MissingStageHandlerError,
    StageHandlerRegistry,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


class _Handler:
    def __init__(self, stage: StageName) -> None:
        self.stage = stage

    def apply(
        self,
        state: object,
        result: dict[str, object],
        context: TransitionContext,
    ) -> TransitionDecision:
        return TransitionDecision(next_stage=self.stage)


def test_registry_returns_exact_registered_handler() -> None:
    handler = _Handler("gap_scan")
    registry = StageHandlerRegistry([handler])

    assert registry.get("gap_scan") is handler
    assert registry.stages == frozenset({"gap_scan"})
    assert isinstance(handler, StageHandler)


def test_duplicate_stage_registration_fails_closed() -> None:
    with pytest.raises(DuplicateStageHandlerError, match="gap_scan"):
        StageHandlerRegistry([_Handler("gap_scan"), _Handler("gap_scan")])


def test_missing_or_unknown_stage_lookup_fails_closed() -> None:
    registry = StageHandlerRegistry()

    with pytest.raises(MissingStageHandlerError, match="developer"):
        registry.get("developer")
    with pytest.raises(ValueError, match="未知 stage"):
        registry.get("not-a-stage")  # type: ignore[arg-type]


def test_transition_decision_and_context_are_immutable() -> None:
    context = TransitionContext(thread_id="thread-1", tick=3)
    decision = TransitionDecision(next_stage="developer", terminal=False)

    with pytest.raises(FrozenInstanceError):
        context.tick = 4  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.terminal = True  # type: ignore[misc]


def test_all_stage_names_match_current_engine_contract() -> None:
    assert set(StageName.__args__) == {
        "gap_scan",
        "gap_review",
        "research",
        "architect",
        "developer",
        "critic",
        "component_verifier",
        "plate_deep_audit",
        "system_verifier",
        "system_deep_audit",
        "plan_refine",
    }


def test_orchestrator_registers_exactly_one_handler_for_every_stage(
    tmp_path,
) -> None:
    orchestrator = TickOrchestrator(tmp_path)

    assert orchestrator._stage_handlers.stages == frozenset(StageName.__args__)
    assert [
        name
        for name in vars(TickOrchestrator)
        if name.startswith("_after_")
    ] == ["_after_tick"]
