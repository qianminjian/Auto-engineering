"""Tests for gates/guardrail.py — Phase 2 T6.

TDD Red phase: GuardrailResult + DropOutput + GuardrailHandler Protocol + GuardrailChain.

参考:
    - CrewAI GuardrailResult(success, result, error)
    - AutoGen InterventionHandler Protocol + DropMessage sentinel
    - v1.0-AUDIT-SUPPLEMENT.md P0-18: Gate 升级为 Guardrail(4 态)
"""

from __future__ import annotations

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.state import LoopState
from auto_engineering.gates.guardrail import (
    DropOutput,
    GuardrailChain,
    GuardrailResult,
)


class TestGuardrailResult:
    """GuardrailResult 字段."""

    def test_minimal_creation(self):
        r = GuardrailResult(action="pass")
        assert r.action == "pass"
        assert r.reason == ""
        assert r.payload is None

    def test_with_reason_and_payload(self):
        r = GuardrailResult(action="block", reason="plan 文件不存在", payload={"file": "plan.md"})
        assert r.action == "block"
        assert "plan 文件不存在" in r.reason
        assert r.payload["file"] == "plan.md"

    def test_all_actions_valid(self):
        """4 态都应能构造."""
        for action in ("pass", "block", "drop", "retry"):
            r = GuardrailResult(action=action)
            assert r.action == action


class TestDropOutputSentinel:
    """DropOutput sentinel — AutoGen DropMessage 风格.

    用于 Guardrail 显式表达"静默丢弃"语义,避免和 None / False 混淆.
    """

    def test_drop_output_is_singleton_like(self):
        """DropOutput() 可多次创建,instance check 仍 True."""
        d1 = DropOutput()
        d2 = DropOutput()
        assert isinstance(d1, DropOutput)
        assert isinstance(d2, DropOutput)


class TestGuardrailHandlerProtocol:
    """GuardrailHandler Protocol — 实现 check() 的对象都是 Guardrail.

    v1.0 不要求 isinstance 检查(Protocol 是 structural typing),
    Phase 2 builtin Guardrail 应满足 Protocol.
    """

    def test_simple_handler_satisfies_protocol(self):
        class SimpleHandler:
            def check(self, stage, state):
                return GuardrailResult(action="pass")

        h = SimpleHandler()
        # 不强制 isinstance 检查 — Protocol 是 duck typing
        assert hasattr(h, "check")
        assert callable(h.check)


class TestGuardrailChainEmpty:
    """空 GuardrailChain.run() 应返回 pass."""

    def test_empty_chain_returns_pass(self):
        chain = GuardrailChain()
        stage = Stage(name="x", agent_type="x", description_template="", expected_output="")
        result = chain.run(stage, LoopState())
        assert result.action == "pass"


class TestGuardrailChainSingleHandler:
    """单个 handler 的 4 态."""

    def _stage(self) -> Stage:
        return Stage(name="x", agent_type="x", description_template="", expected_output="")

    def test_pass_handler_returns_pass(self):
        class PassHandler:
            def check(self, stage, state):
                return GuardrailResult(action="pass")

        chain = GuardrailChain([PassHandler()])
        result = chain.run(self._stage(), LoopState())
        assert result.action == "pass"

    def test_block_handler_returns_block(self):
        class BlockHandler:
            def check(self, stage, state):
                return GuardrailResult(action="block", reason="bad input")

        chain = GuardrailChain([BlockHandler()])
        result = chain.run(self._stage(), LoopState())
        assert result.action == "block"
        assert result.reason == "bad input"

    def test_drop_handler_returns_drop(self):
        class DropHandler:
            def check(self, stage, state):
                return GuardrailResult(action="drop")

        chain = GuardrailChain([DropHandler()])
        result = chain.run(self._stage(), LoopState())
        assert result.action == "drop"

    def test_retry_handler_returns_retry(self):
        class RetryHandler:
            def check(self, stage, state):
                return GuardrailResult(action="retry", reason="transient")

        chain = GuardrailChain([RetryHandler()])
        result = chain.run(self._stage(), LoopState())
        assert result.action == "retry"


class TestGuardrailChainMultipleHandlers:
    """多 handler:首个非 pass 决定最终结果."""

    def test_first_non_pass_short_circuits(self):
        """第一个非 pass handler 返回后,后续 handler 不调用."""
        call_log = []

        class TrackingHandler:
            def __init__(self, action, name):
                self.action = action
                self.name = name

            def check(self, stage, state):
                call_log.append(self.name)
                return GuardrailResult(action=self.action)

        chain = GuardrailChain(
            [
                TrackingHandler("pass", "h1"),
                TrackingHandler("block", "h2"),
                TrackingHandler("pass", "h3"),  # 不应被调用
            ]
        )
        result = chain.run(
            Stage(name="x", agent_type="x", description_template="", expected_output=""),
            LoopState(),
        )
        assert result.action == "block"
        assert call_log == ["h1", "h2"]  # h3 未调用

    def test_all_pass_returns_pass(self):
        class PassHandler:
            def check(self, stage, state):
                return GuardrailResult(action="pass")

        chain = GuardrailChain([PassHandler(), PassHandler(), PassHandler()])
        result = chain.run(
            Stage(name="x", agent_type="x", description_template="", expected_output=""),
            LoopState(),
        )
        assert result.action == "pass"


class TestGuardrailChainAddHandler:
    """运行时添加 handler."""

    def test_add_handler_extends_chain(self):
        chain = GuardrailChain()

        class PassHandler:
            def check(self, stage, state):
                return GuardrailResult(action="pass")

        chain.add(PassHandler())
        assert len(chain.handlers) == 1

    def test_add_multiple_in_order(self):
        chain = GuardrailChain()
        h1 = PassHandler()
        h2 = PassHandler()
        chain.add(h1)
        chain.add(h2)
        assert chain.handlers == [h1, h2]


# SimpleHandler / PassHandler helper (defined once, reused)
class PassHandler:
    def check(self, stage, state):
        return GuardrailResult(action="pass")
