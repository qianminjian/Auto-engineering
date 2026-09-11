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


def test_cli_emits_machine_decision_without_mutating_inputs(tmp_path) -> None:
    import json

    status_path = tmp_path / "status.json"
    lease_path = tmp_path / "lease.json"
    status_path.write_text(json.dumps(_status()), encoding="utf-8")
    lease_path.write_text(json.dumps(_lease()), encoding="utf-8")

    assert main([
        "--status-file", str(status_path),
        "--lease-file", str(lease_path),
    ]) == 0
    assert status_path.read_text(encoding="utf-8") == json.dumps(_status())
    assert lease_path.read_text(encoding="utf-8") == json.dumps(_lease())
