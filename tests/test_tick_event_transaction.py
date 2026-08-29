"""Phase 53 T250：单 Tick 事件、投影、Action 原子提交。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.effects import EffectReceipt
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.kernel import TickKernel
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from tests.host_runtime.trajectory_runner import HostTrajectoryRunner


def _event() -> LoopEvent:
    state = _state()
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.LOOP_INITIALIZED,
        payload={"state": state.to_dict()},
        correlation_id="thread-1",
    )


def _state() -> EngineState:
    return EngineState(
        thread_id="thread-1",
        requirement="原子提交",
        current_stage="architect",
    )


def _action() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "action-1",
        "thread_id": "thread-1",
        "tick": 0,
        "stage": "architect",
        "correlation_id": "thread-1",
        "extensions": {},
        "action": "architect",
    }


def test_commit_tick_atomically_writes_event_projection_and_action() -> None:
    state = _state()
    with SQLiteEventStore(":memory:") as store:
        store.commit_tick(events=[_event()], state=state, action=_action())

        assert len(store.load_stream("thread-1")) == 1
        assert store.load_projection("thread-1").to_dict() == state.to_dict()
        assert store.load_action_snapshot("thread-1") == _action()


def test_commit_tick_atomically_writes_result_replay_receipt() -> None:
    state = _state()
    with SQLiteEventStore(":memory:") as store:
        store.commit_tick(
            events=[_event()],
            state=state,
            action=_action(),
            result_causation_id="previous-action",
            result_hash="a" * 64,
        )

        assert store.load_protocol_result(
            "thread-1", "previous-action"
        ) == ("a" * 64, _action())


def test_result_replay_receipt_rolls_back_with_tick() -> None:
    def fail_after_result(point: str) -> None:
        if point == "after_result":
            raise RuntimeError("fault:after_result")

    with SQLiteEventStore(":memory:", fault_injector=fail_after_result) as store:
        with pytest.raises(RuntimeError, match="after_result"):
            store.commit_tick(
                events=[_event()],
                state=_state(),
                action=_action(),
                result_causation_id="previous-action",
                result_hash="b" * 64,
            )

        assert store.load_protocol_result("thread-1", "previous-action") is None
        assert store.load_stream("thread-1") == []


def test_effect_receipts_commit_with_action_snapshot() -> None:
    receipt = EffectReceipt(
        kind="prompt",
        relative_path=".ae-state/effects/prompt/a.txt",
        sha256="a" * 64,
        bytes=12,
    )
    with SQLiteEventStore(":memory:") as store:
        store.commit_tick(
            events=[_event()],
            state=_state(),
            action=_action(),
            effect_receipts=[receipt],
        )

        assert store.load_effect_receipts("thread-1", "action-1") == [receipt]


def test_effect_receipts_roll_back_with_tick() -> None:
    def fail_after_effects(point: str) -> None:
        if point == "after_effects":
            raise RuntimeError("fault:after_effects")

    receipt = EffectReceipt(
        kind="json",
        relative_path=".ae-state/spawn-proofs/p.json",
        sha256="b" * 64,
        bytes=10,
    )
    with SQLiteEventStore(":memory:", fault_injector=fail_after_effects) as store:
        with pytest.raises(RuntimeError, match="after_effects"):
            store.commit_tick(
                events=[_event()],
                state=_state(),
                action=_action(),
                effect_receipts=[receipt],
            )

        assert store.load_effect_receipts("thread-1", "action-1") == []
        assert store.load_stream("thread-1") == []


def test_effect_receipt_path_and_digest_are_fail_closed() -> None:
    invalid = EffectReceipt(
        kind="json",
        relative_path="../outside.json",
        sha256="not-a-digest",
        bytes=1,
    )
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="EFFECT_RECEIPT_INVALID"):
            store.commit_tick(
                events=[_event()],
                state=_state(),
                action=_action(),
                effect_receipts=[invalid],
            )

        assert store.load_stream("thread-1") == []


@pytest.mark.parametrize(
    "failure_point",
    ["after_events", "after_projection", "after_action"],
)
def test_failure_at_any_write_rolls_back_whole_tick(failure_point: str) -> None:
    def fail_at(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"fault:{point}")

    state = _state()
    with SQLiteEventStore(":memory:", fault_injector=fail_at) as store:
        with pytest.raises(RuntimeError, match=f"fault:{failure_point}"):
            store.commit_tick(events=[_event()], state=state, action=_action())

        assert store.load_stream("thread-1") == []
        assert store.load_projection("thread-1") is None
        assert store.load_action_snapshot("thread-1") is None


@pytest.mark.parametrize(
    "failure_point",
    ["after_events", "after_projection", "after_action"],
)
def test_retry_after_injected_failure_commits_exactly_once(
    failure_point: str,
) -> None:
    armed = True

    def fail_once(point: str) -> None:
        nonlocal armed
        if armed and point == failure_point:
            armed = False
            raise RuntimeError(f"fault:{point}")

    state = _state()
    with SQLiteEventStore(":memory:", fault_injector=fail_once) as store:
        with pytest.raises(RuntimeError, match=f"fault:{failure_point}"):
            store.commit_tick(events=[_event()], state=state, action=_action())

        store.commit_tick(events=[_event()], state=state, action=_action())

        assert len(store.load_stream("thread-1")) == 1
        assert store.load_projection("thread-1").to_dict() == state.to_dict()
        assert store.load_action_snapshot("thread-1") == _action()


def test_commit_rejects_cross_thread_projection_and_action() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="thread_id"):
            store.commit_tick(
                events=[_event()],
                state=EngineState(thread_id="other"),
                action=_action(),
            )
        wrong_action = {**_action(), "thread_id": "other"}
        with pytest.raises(ValueError, match="thread_id"):
            store.commit_tick(
                events=[_event()],
                state=EngineState(thread_id="thread-1"),
                action=wrong_action,
            )


def test_commit_rejects_projection_that_does_not_match_replay() -> None:
    with SQLiteEventStore(":memory:") as store:
        divergent = EngineState(thread_id="thread-1", requirement="不一致")
        with pytest.raises(ValueError, match=r"channels=.*requirement"):
            store.commit_tick(events=[_event()], state=divergent, action=_action())


def test_orchestrator_init_uses_event_transaction_without_checkpoint_write(
    tmp_path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        orchestrator = TickOrchestrator(
            tmp_path,
            checkpoint_store=None,
            event_store=store,
        )

        action = orchestrator.init("通过事件启动")

        stream = store.load_stream(action["thread_id"])
        assert [event.event_type for event in stream] == [
            LoopEventType.LOOP_INITIALIZED,
            LoopEventType.PROJECT_SETUP_REQUIRED,
            LoopEventType.ACTION_ISSUED,
        ]
        assert store.load_projection(action["thread_id"]).to_dict() == (
            orchestrator._state.to_dict()
        )
        assert store.load_action_snapshot(action["thread_id"]) == action


def test_orchestrator_restores_projection_and_active_action_from_event_store(
    tmp_path,
) -> None:
    checkpoints = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    try:
        with SQLiteEventStore(tmp_path / "events.db") as events:
            first = TickOrchestrator(
                tmp_path,
                checkpoint_store=checkpoints,
                event_store=events,
            )
            action = first.init("事件恢复")

            restored = TickOrchestrator.restore(
                tmp_path,
                checkpoints,
                event_store=events,
                thread_id=action["thread_id"],
            )

            assert restored._state.to_dict() == first._state.to_dict()
            assert restored._active_action == action
            assert restored._round_history == []
    finally:
        checkpoints.close()


def test_orchestrator_restores_projection_when_commit_compilation_fails(
    tmp_path,
    monkeypatch,
) -> None:
    """提交候选编译失败也不得留下半推进的内存投影。"""
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            tmp_path,
            checkpoint_store=None,
            event_store=events,
        )
        action = orchestrator.init("事件恢复")
        persisted = events.load_projection(action["thread_id"])
        orchestrator._state.current_stage = "developer"

        def reject_compile(*args, **kwargs):
            raise ValueError("UNMAPPED_PROJECTION_CHANNEL: current_stage")

        monkeypatch.setattr(TickKernel, "compile_commit", reject_compile)

        with pytest.raises(ValueError, match="UNMAPPED_PROJECTION_CHANNEL"):
            orchestrator._commit_event_action(action)

        assert orchestrator._state.to_dict() == persisted.to_dict()


def test_orchestrator_clears_uncommitted_effects_after_commit_failure(tmp_path) -> None:
    """失败 Tick 不得把旧 pending effect 带入下一次重试。"""
    armed = False

    def fail_after_events(point: str) -> None:
        if armed and point == "after_events":
            raise RuntimeError("fault:after_events")

    with SQLiteEventStore(
        tmp_path / "events.db", fault_injector=fail_after_events
    ) as events:
        orchestrator = TickOrchestrator(
            tmp_path, checkpoint_store=None, event_store=events
        )
        action = orchestrator.init("清理未提交副作用")
        armed = True
        orchestrator._pending_effect_receipts.append(EffectReceipt(
            kind="prompt",
            relative_path=".ae-state/effects/prompt/uncommitted.txt",
            sha256="a" * 64,
            bytes=1,
        ))
        with pytest.raises(RuntimeError, match="fault:after_events"):
            orchestrator._commit_event_action(action)

        assert orchestrator._pending_effect_receipts == []
        assert orchestrator._pending_effect_intents == []


def test_gap_wizard_restores_at_first_undecided_gap(tmp_path) -> None:
    """跨进程恢复必须依赖 Core 投影，而不是宿主聊天内存中的批量选择。"""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='wizard-test'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "wizard_test").mkdir()
    design = tmp_path / "design.md"
    design.write_text("## §1 接口边界\n", encoding="utf-8")
    gap_base = {
        "design_section_ref": "§1",
        "grade": "component",
        "clarity": "vague",
        "summary": "接口边界不清",
        "depends_on": [],
        "evidence": ["§1 未定义输入输出"],
        "problem_statement": "接口无法唯一实现",
        "impact": ["影响契约测试"],
        "dependencies": [],
        "recommendation": {
            "resolution": "Fill",
            "reason": "用户可直接明确契约",
            "confidence": "high",
        },
        "options": [{
            "resolution": "Fill",
            "meaning": "补充设计",
            "enabled": True,
        }],
        "blocking_rule": "component gap 可 Fill",
    }
    checkpoints = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    try:
        with SQLiteEventStore(tmp_path / "events.db") as events:
            guardrail = MagicMock()
            guardrail.check.return_value = MagicMock(action="pass")
            orchestrator = TickOrchestrator(
                tmp_path,
                gate_runner=lambda names, root: {
                    name: MagicMock(passed=True, message="ok") for name in names
                },
                guardrail=guardrail,
                checkpoint_store=checkpoints,
                event_store=events,
            )
            initial = orchestrator.init("实现接口", design_doc_path=str(design))
            orchestrator.tick_dict({
                "stage": "gap_scan",
                "gaps": [
                    {**gap_base, "id": "gap-A"},
                    {**gap_base, "id": "gap-B"},
                ],
                "scanned_sections": 1,
                "has_blocking": False,
                "design_doc_digest": orchestrator._state.design_doc_digest,
                "scan_coverage": [{
                    "design_section_ref": "§1 接口边界",
                    "verdict": "gap",
                    "evidence": ["§1 未定义输入输出"],
                }],
            })
            action = orchestrator.tick_dict({
                "stage": "gap_review",
                "decision": {
                    "gap_id": "gap-A",
                    "resolution": "Fill",
                    "fill_content": "输入 string，输出 Result",
                    "decision_source": "user",
                },
            })

            restored = TickOrchestrator.restore(
                tmp_path,
                checkpoints,
                event_store=events,
                thread_id=initial["thread_id"],
            )

            assert action.get("action") == "gap_review", action
            assert action["current_gap"]["id"] == "gap-B"
            assert restored._active_action == action
            assert restored._state.pending_gap_decisions[0]["gap_id"] == "gap-A"
            assert events.load_projection(initial["thread_id"]).to_dict() == (
                restored._state.to_dict()
            )
    finally:
        checkpoints.close()


def test_critic_major_replays_to_developer_without_projection_drift(tmp_path) -> None:
    """真跑 Critic MAJOR 返工必须原子进入 developer 且可事件重放。"""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='critic-retry'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )
    (tmp_path / "critic_retry").mkdir()
    (tmp_path / "tests").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")

    checkpoints = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    try:
        with SQLiteEventStore(tmp_path / "events.db") as events:
            orchestrator = TickOrchestrator(
                tmp_path,
                gate_runner=lambda names, root: {
                    name: MagicMock(passed=True, message="ok") for name in names
                },
                guardrail=guardrail,
                checkpoint_store=checkpoints,
                event_store=events,
            )
            architect = orchestrator.init("实现功能")
            runner = HostTrajectoryRunner(
                tmp_path, HostPlatform.CODEX, core=orchestrator, event_store=events
            )
            developer = runner.run(architect, workers=[lambda invocation: {
                "plan": (
                    "实现完整功能并执行 Red Green Refactor、静态检查、单元测试、"
                    "契约验证和构建验收，保留可重放证据。"
                ),
                "batch_plan": [{
                    "batch_id": "B01",
                    "component": "核心组件",
                    "tasks": [{
                        "id": "B01-T1",
                        "description": "实现核心功能",
                        "file_targets": ["critic_retry/core.py"],
                    }],
                }],
                "file_list": ["critic_retry/core.py"],
                "contracts": {},
            }]).next_action
            assert developer.get("action") == "developer", developer
            critic = runner.run(developer, workers=[lambda invocation: {
                "batch_id": "B01",
                "files_changed": ["critic_retry/core.py"],
                "commit_hash": "",
                "test_results": {"passed": 1, "failed": 0, "total": 1},
                "red_evidence": [],
            }]).next_action
            retry = runner.run(critic, workers=[lambda invocation: {
                "verdict": "MAJOR",
                "findings": [{
                    "file": "critic_retry/core.py",
                    "line": 1,
                    "severity": "P1",
                    "issue": "缺少边界处理",
                    "suggestion": "补充异常分支",
                }],
                "strengths": [{"description": "接口边界清晰"}],
                "assessment": "Needs rework",
            }]).next_action

            projection = events.load_projection(architect["thread_id"])
            assert retry["action"] == "developer"
            assert projection.current_stage == "developer"
            assert projection.strengths is None
            assert projection.assessment is None
            assert events.load_action_snapshot(architect["thread_id"]) == retry
    finally:
        checkpoints.close()
