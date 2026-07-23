"""Guardrail base layer isolated tests — GuardrailResult + Guardrail ABC.

P2-24: guardrail_base.py 无独立测试，只在 test_guardrail.py 间接覆盖。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.engine.guardrail_types import Guardrail, GuardrailResult


class TestGuardrailResult:
    """GuardrailResult dataclass isolated tests."""

    def test_defaults_to_pass(self):
        result = GuardrailResult()
        assert result.action == "pass"
        assert result.message == ""
        assert result.guardrail_name == ""

    def test_passed_property_true_when_pass(self):
        result = GuardrailResult(action="pass")
        assert result.passed is True

    def test_passed_property_false_when_block(self):
        result = GuardrailResult(action="block", message="blocked")
        assert result.passed is False

    def test_passed_property_false_when_retry(self):
        result = GuardrailResult(action="retry", message="retry needed")
        assert result.passed is False

    def test_message_and_name_settable(self):
        result = GuardrailResult(
            action="block",
            message="security violation",
            guardrail_name="REDGuardrail",
        )
        assert result.message == "security violation"
        assert result.guardrail_name == "REDGuardrail"

    def test_equality_semantics(self):
        a = GuardrailResult(action="block", message="same")
        b = GuardrailResult(action="block", message="same")
        assert a == b
        assert a != GuardrailResult(action="pass")


class _ConcreteGuardrail(Guardrail):
    """Minimal concrete Guardrail for ABC testing."""

    name = "TestGuardrail"
    timing = "pre"
    applies_to_stages = ("architect", "developer")

    def check(self, stage, state, project_root=None):
        return GuardrailResult(action="pass")


class TestGuardrailABC:
    """Guardrail ABC isolated tests."""

    def test_concrete_subclass_instantiable(self):
        g = _ConcreteGuardrail()
        assert g.name == "TestGuardrail"
        assert g.timing == "pre"
        assert g.applies_to_stages == ("architect", "developer")

    def test_concrete_check_returns_guardrail_result(self):
        g = _ConcreteGuardrail()
        state = EngineState()
        result = g.check("architect", state)
        assert isinstance(result, GuardrailResult)
        assert result.passed

    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Guardrail()  # type: ignore[abstract]

    def test_subclass_without_check_cannot_instantiate(self):
        class _Incomplete(Guardrail):
            name = "Incomplete"

        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]

    def test_project_root_default_none(self):
        g = _ConcreteGuardrail()
        state = EngineState()
        result = g.check("developer", state)
        assert result.passed

    def test_project_root_passed_through(self):
        """Verify project_root kwarg is accepted (default None)."""
        g = _ConcreteGuardrail()
        state = EngineState()
        result = g.check("critic", state, project_root=Path("/tmp"))
        assert result.passed
