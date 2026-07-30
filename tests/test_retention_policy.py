"""v5.8 T317：保留策略 dry-run 与引用完整性。"""

from __future__ import annotations

import json

from auto_engineering.loop.retention import RetentionPlanner, RetentionPolicy


def test_plan_never_marks_event_facts_for_cleanup(tmp_path) -> None:
    state = tmp_path / ".ae-state"
    (state / "events").mkdir(parents=True)
    (state / "checkpoints").mkdir()
    (state / "events" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    for index in range(4):
        (state / "checkpoints" / f"{index}.json").write_text(
            json.dumps({"index": index}), encoding="utf-8"
        )

    plan = RetentionPlanner(state).plan(RetentionPolicy(
        keep_checkpoint_copies=2,
        keep_prompt_logs=2,
    ))

    assert all("events" not in item.path.parts for item in plan.candidates)
    assert len([
        item for item in plan.candidates if item.kind == "checkpoint_copy"
    ]) == 2
    assert (state / "events" / "events.jsonl").exists()


def test_dry_run_does_not_mutate_files(tmp_path) -> None:
    state = tmp_path / ".ae-state"
    prompts = state / "prompt-log"
    prompts.mkdir(parents=True)
    for index in range(5):
        (prompts / f"{index}.json").write_text("{}", encoding="utf-8")
    before = sorted(path.name for path in prompts.iterdir())

    plan = RetentionPlanner(state).plan(RetentionPolicy(
        keep_checkpoint_copies=1,
        keep_prompt_logs=2,
    ))

    assert len(plan.candidates) == 3
    assert sorted(path.name for path in prompts.iterdir()) == before


def test_referenced_artifact_is_retained_and_missing_ref_reported(tmp_path) -> None:
    state = tmp_path / ".ae-state"
    artifacts = state / "artifacts"
    artifacts.mkdir(parents=True)
    kept = "a" * 64
    orphan = "b" * 64
    (artifacts / f"{kept}.json").write_text("{}", encoding="utf-8")
    (artifacts / f"{orphan}.json").write_text("{}", encoding="utf-8")
    planner = RetentionPlanner(state)

    plan = planner.plan(
        RetentionPolicy(keep_checkpoint_copies=1, keep_prompt_logs=1),
        referenced_artifact_ids={kept},
    )
    missing = planner.verify_artifact_references({kept, "c" * 64})

    assert not any(kept in item.path.name for item in plan.candidates)
    assert any(orphan in item.path.name for item in plan.candidates)
    assert missing == ["c" * 64]
