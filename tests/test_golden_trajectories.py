"""Phase 56 T266：黄金轨迹格式与语义比较器。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden.runner import (
    compare_host_trajectories,
    compare_trajectory,
    load_fixtures,
    normalize_semantics,
)


def test_normalizer_ignores_only_nondeterministic_and_host_display_fields() -> None:
    trajectory = {
        "events": [{
            "event_id": "random-1",
            "created_at": "2026-01-01T00:00:00Z",
            "event_type": "StageAdvanced",
            "payload": {"to": "developer"},
        }],
        "action": {
            "action": "developer",
            "message_id": "random-2",
            "extensions": {
                "host": {"label": "Codex"},
                "business": {"gate": "test"},
            },
        },
    }

    normalized = normalize_semantics(trajectory)

    assert normalized["events"] == [{
        "event_type": "StageAdvanced",
        "payload": {"to": "developer"},
    }]
    assert normalized["action"]["extensions"] == {
        "business": {"gate": "test"}
    }


def test_compare_trajectory_validates_business_semantics() -> None:
    expected = {
        "events": [{"event_type": "StageAdvanced", "payload": {"to": "critic"}}],
        "projection": {"current_stage": "critic"},
        "action": {"action": "critic"},
        "verdict": None,
    }
    actual = {
        **expected,
        "events": [{
            "event_id": "random",
            "timestamp": "2026-01-01T00:00:00Z",
            **expected["events"][0],
        }],
    }

    compare_trajectory(actual, expected)

    changed = {**actual, "projection": {"current_stage": "developer"}}
    with pytest.raises(AssertionError, match="projection"):
        compare_trajectory(changed, expected)


def test_all_ten_required_golden_trajectories_pass() -> None:
    fixtures = load_fixtures(
        Path(__file__).parent / "golden" / "critical-trajectories.json"
    )

    assert {fixture["name"] for fixture in fixtures} == {
        "normal_completion",
        "gate_pause_resume",
        "skip",
        "guardrail_block",
        "verification_refine",
        "duplicate_result",
        "conflicting_result",
        "checkpoint_import",
        "crash_recovery",
        "terminal_replay",
    }
    for fixture in fixtures:
        compare_trajectory(fixture["actual"], fixture["expected"])


def test_claude_and_codex_golden_trajectories_are_semantically_equal() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    action = {
        "action": "developer",
        "message_id": "msg-1",
        "extensions": {"business": {"batch_id": "B1"}},
    }
    trajectories = []
    for platform in (HostPlatform.CLAUDE_CODE, HostPlatform.CODEX):
        adapter = adapter_for(platform)
        profile = adapter.probe(
            detected=adapter.capabilities,
            authorized=adapter.capabilities,
        )
        mapped = adapter.map_action(action, profile=profile)
        trajectories.append({
            "events": [{"event_type": "StageAdvanced"}],
            "projection": {"current_stage": "developer"},
            "action": {
                **mapped.payload,
                "extensions": {
                    **mapped.payload["extensions"],
                    "host": {"platform": mapped.platform.value},
                },
            },
            "verdict": None,
        })

    compare_host_trajectories(trajectories[0], trajectories[1])

    trajectories[1]["projection"] = {"current_stage": "critic"}
    with pytest.raises(AssertionError, match="projection"):
        compare_host_trajectories(trajectories[0], trajectories[1])
