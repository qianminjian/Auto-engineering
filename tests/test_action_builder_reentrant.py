"""Phase 54 T253：ActionBuilder 交错调用不得泄漏单次上下文。"""

from __future__ import annotations

import json

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuilder


def _state(thread_id: str, refine_source: str) -> EngineState:
    return EngineState(
        thread_id=thread_id,
        current_stage="architect",
        requirement=f"requirement-{thread_id}",
        refine_request_json=json.dumps({"source": refine_source}),
    )


def test_interleaved_build_keeps_outer_context(tmp_path, monkeypatch) -> None:
    builder = ActionBuilder(tmp_path)
    outer = _state("outer", "outer-source")
    inner = _state("inner", "inner-source")
    original = builder._build_action_architect
    nested = False

    def interleave(base: dict) -> dict:
        nonlocal nested
        if not nested:
            nested = True
            inner_action = builder.build_action(inner)
            assert inner_action["thread_id"] == "inner"
        return original(base)

    monkeypatch.setattr(builder, "_build_action_architect", interleave)

    outer_action = builder.build_action(outer)

    assert outer_action["thread_id"] == "outer"
    assert outer_action["requirement"] == "requirement-outer"
    assert outer_action["feedback"]["refine_request"]["source"] == "outer-source"


def test_sequential_optional_dependencies_do_not_leak(tmp_path) -> None:
    builder = ActionBuilder(tmp_path)
    first = EngineState(thread_id="first", current_stage="critic")
    first.files_changed = ["first.py"]
    second = EngineState(thread_id="second", current_stage="critic")

    first_action = builder.build_action(
        first,
        dev_snapshot={"files_changed": ["snapshot.py"]},
    )
    second_action = builder.build_action(second)

    assert '"snapshot.py"' in first_action["subagent_prompt"]
    assert '"snapshot.py"' not in second_action["subagent_prompt"]
    assert '"files_changed": []' in second_action["subagent_prompt"]
    assert "context" not in first_action
    assert "context" not in second_action
