"""宿主返回边界自动续驱动的纯决策测试。"""

from __future__ import annotations

from auto_engineering.host.continuation_driver import main, should_resume_host


def _status(*, active: bool = True, operation: str = "resume_active_action") -> dict:
    payload: dict[str, object] = {
        "thread_id": "thread-1",
        "next_operation": {
            "operation": operation,
            "thread_id": "thread-1",
        },
    }
    if active:
        payload["active_action"] = {"message_id": "action-1", "stage": "critic"}
    return payload


def _lease(
    *,
    disposition: str = "CONTINUE",
    continuation_required: bool = True,
    yield_allowed: bool = False,
) -> dict[str, object]:
    return {
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "disposition": disposition,
        "continuation_required": continuation_required,
        "yield_allowed": yield_allowed,
    }


def test_resumes_only_when_core_has_active_continue_action() -> None:
    assert should_resume_host(_status(), _lease()) is True


def test_does_not_resume_without_active_action_or_resume_operation() -> None:
    assert should_resume_host(_status(active=False), _lease()) is False
    assert should_resume_host(_status(operation="stop"), _lease()) is False


def test_does_not_resume_user_wait_terminal_or_yieldable_lease() -> None:
    assert should_resume_host(_status(), _lease(disposition="WAIT_USER")) is False
    assert should_resume_host(_status(), _lease(disposition="TERMINAL")) is False
    assert should_resume_host(_status(), _lease(yield_allowed=True)) is False


def test_does_not_resume_when_action_result_repair_is_exhausted(tmp_path) -> None:
    import json

    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()
    (journal_dir / "action-1.json").write_text(
        json.dumps({
            "status": "assembly_rejected",
            "action_message_id": "action-1",
            "repairable": False,
        }),
        encoding="utf-8",
    )

    assert should_resume_host(_status(), _lease(), journal_dir) is False


def test_resumes_when_action_result_repair_is_still_available(tmp_path) -> None:
    import json

    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()
    (journal_dir / "action-1.json").write_text(
        json.dumps({
            "status": "assembly_rejected",
            "action_message_id": "action-1",
            "repairable": True,
        }),
        encoding="utf-8",
    )

    assert should_resume_host(_status(), _lease(), journal_dir) is True


def test_does_not_resume_after_host_protocol_failure(tmp_path) -> None:
    """协议终态即使暂留 CONTINUE lease，也不得重复喂给同一坏 Action。"""
    import json

    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()
    (journal_dir / "action-1.json").write_text(
        json.dumps({
            "status": "protocol_failed",
            "failure_kind": "protocol",
            "action_message_id": "action-1",
            "result": {
                "spawned": False,
                "spawn_error_code": "HOST_PROTOCOL_FAILURE",
            },
        }),
        encoding="utf-8",
    )

    assert should_resume_host(_status(), _lease(), journal_dir) is False


def test_does_not_resume_when_journal_is_corrupt_or_identity_is_unsafe(tmp_path) -> None:
    import json

    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()
    journal = journal_dir / "action-1.json"
    journal.write_text("not-json", encoding="utf-8")
    assert should_resume_host(_status(), _lease(), journal_dir) is False
    journal.write_text(json.dumps({"status": "worker_failed"}), encoding="utf-8")
    assert should_resume_host(_status(), _lease(), journal_dir) is False
    unsafe_status = _status()
    unsafe_status["active_action"] = {"message_id": "../escape"}
    assert should_resume_host(unsafe_status, _lease(), journal_dir) is False


def test_does_not_resume_for_protocol_failure_kind_or_result_code(tmp_path) -> None:
    import json

    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()
    journal = journal_dir / "action-1.json"
    journal.write_text(
        json.dumps({
            "action_message_id": "action-1",
            "failure_kind": "protocol",
            "status": "worker_failed",
        }),
        encoding="utf-8",
    )
    assert should_resume_host(_status(), _lease(), journal_dir) is False
    journal.write_text(
        json.dumps({
            "action_message_id": "action-1",
            "status": "worker_failed",
            "result": {"spawn_error_code": "HOST_PROTOCOL_FAILURE"},
        }),
        encoding="utf-8",
    )
    assert should_resume_host(_status(), _lease(), journal_dir) is False


def test_cli_emits_machine_decision_without_mutating_inputs(tmp_path) -> None:
    import json

    status_path = tmp_path / "status.json"
    lease_path = tmp_path / "lease.json"
    status_path.write_text(json.dumps(_status()), encoding="utf-8")
    lease_path.write_text(json.dumps(_lease()), encoding="utf-8")
    journal_dir = tmp_path / "outcomes"
    journal_dir.mkdir()

    assert main([
        "--status-file", str(status_path),
        "--lease-file", str(lease_path),
        "--outcome-journal-dir", str(journal_dir),
    ]) == 0
    assert status_path.read_text(encoding="utf-8") == json.dumps(_status())
    assert lease_path.read_text(encoding="utf-8") == json.dumps(_lease())
