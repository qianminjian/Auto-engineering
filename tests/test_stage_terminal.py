"""Phase 54 T259：Stage 终态统一契约。"""

from __future__ import annotations

from auto_engineering.loop.stages.terminal import resolve_terminal_action


def test_resolves_error_terminal() -> None:
    action = resolve_terminal_action(
        {
            "error": {
                "error_code": "INVALID_RESULT",
                "message": "结果非法",
            }
        }
    )

    assert action == {
        "action": "error",
        "error_code": "INVALID_RESULT",
        "message": "结果非法",
    }


def test_resolves_done_terminal() -> None:
    action = resolve_terminal_action(
        {
            "terminal_action": {
                "verdict": "HARD_LIMIT",
                "reason": "已达到上限",
            }
        }
    )

    assert action["action"] == "done"
    assert action["verdict"] == "HARD_LIMIT"
    assert action["verdict_reason"] == "已达到上限"


def test_non_terminal_context_returns_none() -> None:
    assert resolve_terminal_action({"state_patch": {}}) is None
