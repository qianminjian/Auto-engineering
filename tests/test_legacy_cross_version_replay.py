"""真实 rc.5 旧 payload 形状的跨版本重放回归。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.projector import EngineStateProjector

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "golden"
    / "legacy_rc5_stage_patch_stream.json"
)


def test_legacy_stage_patch_stream_replays_without_rewriting_history() -> None:
    thread_id = "legacy-rc5-thread"
    seed = LoopEvent.create(
        thread_id=thread_id,
        sequence=0,
        event_type=LoopEventType.LOOP_INITIALIZED,
        payload={"state": EngineState(thread_id=thread_id).to_dict()},
        correlation_id=thread_id,
    )
    raw_events = json.loads(FIXTURE.read_text(encoding="utf-8"))
    events = [
        LoopEvent.create(
            thread_id=thread_id,
            sequence=index,
            event_type=item["event_type"],
            payload=item["payload"],
            correlation_id=thread_id,
        )
        for index, item in enumerate(raw_events, start=1)
    ]

    state = EngineStateProjector().replay([seed, *events])

    assert state.current_stage == "architect"
    assert state.tick == 2
    assert state.round == 2
    assert state.pending_research_ids == []
    assert state.research_archive["gap-1"]["recommended_design"] == "采用服务端边界"
