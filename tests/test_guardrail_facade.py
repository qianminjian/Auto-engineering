"""Tests for GuardrailFacade — PRE/POST guardrail delegation (P1-9)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from auto_engineering.loop.guardrail import GuardrailChain, GuardrailResult
from auto_engineering.loop.guardrail_facade import GuardrailFacade


class TestGuardrailFacadeInit:
    """Constructor tests."""

    def test_default_chain_none(self) -> None:
        facade = GuardrailFacade()
        assert facade._chain is None
        assert facade._project_root is not None

    def test_explicit_chain(self) -> None:
        chain = GuardrailChain([])
        facade = GuardrailFacade(chain=chain)
        assert facade._chain is chain

    def test_explicit_project_root(self, tmp_path) -> None:
        facade = GuardrailFacade(project_root=tmp_path)
        assert facade._project_root == tmp_path

    def test_retry_counters_initialized_empty(self) -> None:
        facade = GuardrailFacade()
        assert facade._retry_counters == {}


class TestGuardrailFacadeNullChain:
    """None chain -> return 'pass' (backward compat, bypasses handle_guardrail_result)."""

    def test_check_pre_null_chain_returns_pass(self) -> None:
        facade = GuardrailFacade(chain=None)
        assert facade.check_pre("developer", MagicMock()) == "pass"

    def test_check_post_null_chain_returns_pass(self) -> None:
        facade = GuardrailFacade(chain=None)
        assert facade.check_post("developer", MagicMock()) == "pass"

    def test_do_check_null_chain_returns_pass(self) -> None:
        facade = GuardrailFacade(chain=None)
        assert facade._do_check("pre", "developer", MagicMock()) == "pass"


class TestGuardrailFacadeDelegation:
    """Chain delegation -> handle_guardrail_result translates actions."""

    @pytest.fixture
    def state(self) -> MagicMock:
        s = MagicMock()
        s.major_count = 0
        s.block_count = 0
        s.consecutive_block_count = 0
        return s

    def test_pass_action_becomes_continue(self, state) -> None:
        g = MagicMock()
        g.timing = "pre"
        g.applies_to_stages = ("developer",)
        g.name = "TestGuard"
        g.check.return_value = GuardrailResult(action="pass")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_pre("developer", state)
        assert result == "continue"  # handle_guardrail_result maps pass -> continue

    def test_block_action_becomes_stop(self, state) -> None:
        g = MagicMock()
        g.timing = "pre"
        g.applies_to_stages = ("developer",)
        g.name = "TestBlockGuard"
        g.check.return_value = GuardrailResult(action="block", message="blocked")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_pre("developer", state)
        assert result == "stop"  # handle_guardrail_result maps block -> stop

    def test_retry_action_preserved(self, state) -> None:
        g = MagicMock()
        g.timing = "post"
        g.applies_to_stages = ("developer",)
        g.name = "TestRetryGuard"
        g.check.return_value = GuardrailResult(action="retry", guardrail_name="TestRetryGuard")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_post("developer", state)
        assert result == "retry"

    def test_guardrail_filtered_by_timing_mismatch(self, state) -> None:
        g = MagicMock()
        g.timing = "post"  # Not "pre"
        g.applies_to_stages = ("developer",)
        g.name = "PostOnly"
        g.check.return_value = GuardrailResult(action="block")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_pre("developer", state)
        assert result == "continue"  # pass -> continue (no guard matched)

    def test_guardrail_filtered_by_stage_mismatch(self, state) -> None:
        g = MagicMock()
        g.timing = "pre"
        g.applies_to_stages = ("architect",)  # Not "developer"
        g.name = "ArchitectOnly"
        g.check.return_value = GuardrailResult(action="block")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_pre("developer", state)
        assert result == "continue"  # pass -> continue (no guard matched)

    def test_post_timing_delegates_correctly(self, state) -> None:
        g = MagicMock()
        g.timing = "post"
        g.applies_to_stages = ("developer",)
        g.name = "PostGuard"
        g.check.return_value = GuardrailResult(action="pass")
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        result = facade.check_post("developer", state)
        assert result == "continue"


class TestGuardrailFacadeRetryTracking:
    """Retry counter state management (key = stage:name)."""

    def test_retry_counter_increments(self) -> None:
        g = MagicMock()
        g.timing = "pre"
        g.applies_to_stages = ("developer",)
        g.name = "FrequentRetry"
        g.check.side_effect = [
            GuardrailResult(action="retry", guardrail_name="FrequentRetry"),
            GuardrailResult(action="pass"),
        ]
        chain = GuardrailChain([g])
        facade = GuardrailFacade(chain=chain)
        state = MagicMock(major_count=0, block_count=0, consecutive_block_count=0)

        r1 = facade.check_pre("developer", state)
        assert r1 == "retry"
        assert facade._retry_counters.get("developer:FrequentRetry", 0) == 1

        r2 = facade.check_pre("developer", state)
        assert r2 == "continue"  # pass -> continue

    def test_multiple_guardrails_independent_counters(self) -> None:
        g1 = MagicMock()
        g1.timing = "pre"
        g1.applies_to_stages = ("developer",)
        g1.name = "GuardA"
        g1.check.return_value = GuardrailResult(action="retry", guardrail_name="GuardA")
        g2 = MagicMock()
        g2.timing = "post"
        g2.applies_to_stages = ("developer",)
        g2.name = "GuardB"
        g2.check.return_value = GuardrailResult(action="retry", guardrail_name="GuardB")
        chain = GuardrailChain([g1, g2])
        facade = GuardrailFacade(chain=chain)
        state = MagicMock(major_count=0, block_count=0, consecutive_block_count=0)

        facade.check_pre("developer", state)
        facade.check_post("developer", state)
        assert facade._retry_counters["developer:GuardA"] == 1
        assert facade._retry_counters["developer:GuardB"] == 1
