"""T75 Integration tests — PII prompt redaction wired into BaseAgent.execute().

Test layers:
  Layer 1 (Unit) — _redact_prompt_messages() function correctly redacts PII
  Layer 2 (Integration) — BaseAgent.execute() calls prompt redaction BEFORE LLM
  Layer 3 (E2E) — PII in task description is redacted in messages sent to LLM

RED phase: These tests FAIL because:
  - _redact_prompt_messages() does not exist yet
  - BaseAgent.execute() does not call prompt redaction before llm.create_message()
  - T56 (prompt PII redaction) is the MISSING first line of defense

Design ref: v5.6-Design-Loop.md appendix E §E.3.2 (T56).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from auto_engineering.agents.base import BaseAgent
from auto_engineering.providers.base import LLMResponse  # migrated from deprecated anthropic_provider.LLMResponse
from auto_engineering.runtime.context import TaskContext
from auto_engineering.runtime.task import Task


# =============================================================================
# Helpers
# =============================================================================


def _make_llm_response(
    content: str = '{"result": "ok"}',
    stop_reason: str = "end_turn",
    tool_use_blocks: list[dict] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-test",
        usage={"input_tokens": 10, "output_tokens": 5},
        stop_reason=stop_reason,
        tool_use_blocks=tool_use_blocks or [],
    )


def _make_task(description: str = "Implement login") -> Task:
    return Task(
        id="t1",
        description=description,
        expected_output="result",
        tools=[],
        input_channels=[],
        output_channels=[],
    )


def _make_ctx() -> TaskContext:
    from auto_engineering.engine.state import LoopState
    return TaskContext(state=LoopState(), requirement="test")


# =============================================================================
# Layer 1 — Unit: _redact_prompt_messages function
# =============================================================================


class TestRedactPromptMessages:
    """Unit tests for _redact_prompt_messages() — T56 prompt redaction helper."""

    def test_function_exists(self) -> None:
        """_redact_prompt_messages must be importable from agents.base."""
        from auto_engineering.agents.base import _redact_prompt_messages
        assert callable(_redact_prompt_messages)

    def test_redacts_cn_phone_from_text_content(self) -> None:
        """Phone number in message content → redacted."""
        from auto_engineering.agents.base import _redact_prompt_messages

        messages = [{"role": "user", "content": "My phone is 13812345678"}]
        redacted = _redact_prompt_messages(messages)
        assert "13812345678" not in redacted[0]["content"]

    def test_redacts_cn_id_card_from_text_content(self) -> None:
        """ID card number in message content → redacted."""
        from auto_engineering.agents.base import _redact_prompt_messages

        messages = [{"role": "user", "content": "ID: 320102199001011234"}]
        redacted = _redact_prompt_messages(messages)
        assert "320102199001011234" not in redacted[0]["content"]

    def test_redacts_bank_card_from_text_content(self) -> None:
        """Bank card number in message content → redacted."""
        from auto_engineering.agents.base import _redact_prompt_messages

        messages = [{"role": "user", "content": "Card: 6222021234567890123"}]
        redacted = _redact_prompt_messages(messages)
        assert "6222021234567890123" not in redacted[0]["content"]

    def test_redacts_from_content_blocks(self) -> None:
        """PII in content blocks (list of text blocks) → redacted."""
        from auto_engineering.agents.base import _redact_prompt_messages

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Phone: 13812345678"},
                {"type": "text", "text": "Safe content"},
            ],
        }]
        redacted = _redact_prompt_messages(messages)
        assert "13812345678" not in redacted[0]["content"][0]["text"]

    def test_does_not_mutate_original_messages(self) -> None:
        """Redaction returns a copy — original messages are unchanged."""
        from auto_engineering.agents.base import _redact_prompt_messages

        original = [{"role": "user", "content": "Phone: 13812345678"}]
        redacted = _redact_prompt_messages(original)
        assert redacted is not original
        assert "13812345678" in original[0]["content"]  # original unchanged

    def test_clean_messages_pass_through(self) -> None:
        """Messages without PII are returned unchanged (but as a copy)."""
        from auto_engineering.agents.base import _redact_prompt_messages

        messages = [{"role": "user", "content": "Implement a login page"}]
        redacted = _redact_prompt_messages(messages)
        assert redacted[0]["content"] == "Implement a login page"


# =============================================================================
# Layer 2 — Integration: BaseAgent.execute() calls prompt redaction
# =============================================================================


class TestPIIPromptIntegration:
    """Integration tests verifying BaseAgent.execute() redacts PII before LLM call.

    These are the "wiring" tests — they verify that the PII redaction module
    is actually REACHABLE from the production call chain, not just that
    the module itself works in isolation.
    """

    @pytest.fixture(autouse=True)
    def _authz_patch(self):
        """Allow all tool authorizations during test."""
        p = patch("auto_engineering.agents.base.authz_check", return_value=True)
        p.start()
        yield
        p.stop()

    def test_execute_redacts_pii_before_llm_call(self) -> None:
        """BaseAgent.execute() MUST redact PII from messages before calling LLM.

        RED: Currently execute() calls llm.create_message() without scanning
        messages for PII first — T56 is NOT wired. This test verifies that
        _redact_prompt_messages is called during execution.
        """
        task = _make_task(description="User phone: 13812345678, fix the login bug")
        ctx = _make_ctx()

        mock_llm = MagicMock()
        mock_llm.create_message.return_value = _make_llm_response()
        mock_llm.provider_name = "anthropic"

        with patch(
            "auto_engineering.agents.base._redact_prompt_messages",
            side_effect=lambda msgs: msgs,
        ) as mock_redact:
            agent = BaseAgent(
                llm=mock_llm,
                system_prompt="You are a developer.",
                role="developer",
                model="claude-test",
                tools=[],
            )
            from tests.conftest import run_async
            run_async(agent.execute(task, ctx))

            assert mock_redact.called, (
                "T56 NOT WIRED: _redact_prompt_messages() was never called during "
                "BaseAgent.execute(). PII in task description is sent directly to "
                "the LLM without redaction — the first line of defense is MISSING."
            )

    def test_pii_in_task_description_is_redacted_before_llm(self) -> None:
        """PII in task description MUST be redacted in the messages sent to LLM.

        RED: The LLM receives raw PII because T56 prompt redaction is not wired.
        """
        task = _make_task(description="Call 13812345678 to verify account 6222021234567890")
        ctx = _make_ctx()

        mock_llm = MagicMock()
        mock_llm.create_message.return_value = _make_llm_response()
        mock_llm.provider_name = "anthropic"

        agent = BaseAgent(
            llm=mock_llm,
            system_prompt="You are a developer.",
            role="developer",
            model="claude-test",
            tools=[],
        )

        from tests.conftest import run_async
        run_async(agent.execute(task, ctx))

        # Check what messages were sent to the LLM
        call_args_list = mock_llm.create_message.call_args_list
        assert len(call_args_list) >= 1, "LLM was never called"
        first_call = call_args_list[0]
        messages = first_call[1].get("messages", first_call[0][1] if len(first_call[0]) > 1 else [])
        all_text = json.dumps(messages)
        assert "13812345678" not in all_text, (
            "T56 NOT WIRED: Phone number 13812345678 was sent to LLM without redaction. "
            "PII in task description is leaking to the model provider."
        )
        assert "6222021234567890" not in all_text, (
            "T56 NOT WIRED: Bank card 6222021234567890 was sent to LLM without redaction."
        )

    def test_redact_prompt_messages_called_before_llm_in_loop(self) -> None:
        """In the tool_use loop, EVERY llm.create_message() call must have
        messages redacted first. Not just the first call."""
        task = _make_task(description="Refactor: user data includes 13812345678")
        ctx = _make_ctx()

        mock_llm = MagicMock()
        mock_llm.create_message.side_effect = [
            _make_llm_response(
                content="",
                stop_reason="tool_use",
                tool_use_blocks=[{"name": "read_file", "input": {"path": "src/app.py"}, "id": "t1"}],
            ),
            _make_llm_response(content='{"result": "done"}'),
        ]
        mock_llm.provider_name = "anthropic"

        agent = BaseAgent(
            llm=mock_llm,
            system_prompt="You are a developer.",
            role="developer",
            model="claude-test",
            max_tool_calls=3,
            tools=[],
        )

        from tests.conftest import run_async
        run_async(agent.execute(task, ctx))

        # Both LLM calls should have had messages redacted
        assert mock_llm.create_message.call_count >= 2
        for call in mock_llm.create_message.call_args_list:
            messages = call[1].get("messages", call[0][1] if len(call[0]) > 1 else [])
            all_text = json.dumps(messages)
            assert "13812345678" not in all_text, (
                "T56 NOT WIRED: PII leaked to LLM in a subsequent create_message() call. "
                "Prompt redaction must happen on EVERY LLM invocation, not just the first."
            )
