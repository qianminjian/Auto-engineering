"""Tests for auto_engineering.context.summarization — SessionSummary + SessionSummarizer."""

from __future__ import annotations

import pytest

from auto_engineering.context.summarization import LLMProvider, LLMResponse, SessionSummarizer, SessionSummary

_DEFAULT_RESPONSE = (
    "DECISION: Used Decimal for monetary calculations\n"
    "FILE: src/payment.py — Payment module with retry logic\n"
    "ISSUE: Batch insert needs profiling\n"
)


class _FakeLLM(LLMProvider):
    """Stub LLMProvider that returns a canned summary response."""

    def __init__(self, response_text: str = _DEFAULT_RESPONSE) -> None:
        self._response = response_text
        self.calls: list[dict] = []

    async def create_message(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "",
        max_tokens: int = 4096,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "model": model})
        return LLMResponse(content=self._response, model=model, stop_reason="end_turn")

    def close(self) -> None:
        pass


class TestSessionSummary:
    """SessionSummary dataclass tests."""

    def test_default_construction(self) -> None:
        s = SessionSummary(
            ticks_covered=range(1, 6),
            key_implementation_decisions=["Used Decimal for money"],
            files_created_modified={"src/payment.py": "Payment module implementation"},
            major_history=[],
            unresolved_issues=[],
            generated_at_tick=5,
        )
        assert s.ticks_covered == range(1, 6)
        assert s.generated_at_tick == 5

    def test_full_construction(self) -> None:
        s = SessionSummary(
            ticks_covered=range(3, 8),
            key_implementation_decisions=["Used Decimal", "Added retry"],
            files_created_modified={
                "src/payment.py": "Core payment logic",
                "tests/test_payment.py": "11 tests added",
            },
            major_history=[
                {"tick": 4, "findings": ["Missing null check in calculate()"]},
            ],
            unresolved_issues=["Performance of batch insert needs profiling"],
            generated_at_tick=7,
        )
        assert len(s.key_implementation_decisions) == 2
        assert len(s.major_history) == 1
        assert s.unresolved_issues[0].startswith("Performance")

    def test_event_store_round_trip_preserves_summary_fields(self) -> None:
        summary = SessionSummary(
            ticks_covered=range(2, 5),
            key_implementation_decisions=["decision"],
            files_created_modified={"src/a.py": "changed"},
            major_history=[{"tick": 3, "findings": ["finding"]}],
            unresolved_issues=["issue"],
            generated_at_tick=4,
        )

        restored = SessionSummary.from_dict(summary.to_dict())

        assert restored == summary


class TestSessionSummarizer:
    """SessionSummarizer tests (LLM calls mocked)."""

    @pytest.fixture
    def fake_llm(self) -> _FakeLLM:
        return _FakeLLM("DECISION: Aggregated summary of ticks 1-5.")

    @pytest.fixture
    def summarizer(self, fake_llm: _FakeLLM) -> SessionSummarizer:
        return SessionSummarizer(fake_llm)

    def test_should_summarize_below_threshold(self, summarizer: SessionSummarizer) -> None:
        """Tick ≤ 5 → should NOT trigger summarization."""
        assert not summarizer.should_summarize(current_tick=3)
        assert not summarizer.should_summarize(current_tick=5)

    def test_should_summarize_above_threshold(self, summarizer: SessionSummarizer) -> None:
        """Tick > 5 → SHOULD trigger summarization."""
        assert summarizer.should_summarize(current_tick=6)
        assert summarizer.should_summarize(current_tick=10)

    def test_should_summarize_custom_threshold(self, summarizer: SessionSummarizer) -> None:
        """Custom threshold is respected."""
        assert not summarizer.should_summarize(current_tick=3, threshold=3)
        assert summarizer.should_summarize(current_tick=4, threshold=3)

    @pytest.mark.asyncio
    async def test_summarize_calls_llm(self, summarizer: SessionSummarizer, fake_llm: _FakeLLM) -> None:
        """summarize() sends a summarization prompt to the LLM."""
        messages = [
            {"role": "user", "content": "Implement login."},
            {"role": "assistant", "content": "Done."},
        ]
        summary = await summarizer.summarize(messages=messages, previous_summary=None, tick=6)
        assert len(fake_llm.calls) == 1
        assert summary.generated_at_tick == 6
        assert "Aggregated summary" in summary.key_implementation_decisions[0]

    @pytest.mark.asyncio
    async def test_summarize_with_previous_summary_merges(
        self, summarizer: SessionSummarizer, fake_llm: _FakeLLM
    ) -> None:
        """summarize() merges previous summary decisions into the prompt."""
        prev = SessionSummary(
            ticks_covered=range(1, 6),
            key_implementation_decisions=["Used Decimal"],
            files_created_modified={"src/a.py": "Module A"},
            major_history=[{"tick": 3, "findings": ["NPE in handler"]}],
            unresolved_issues=["Slow DB query"],
            generated_at_tick=5,
        )
        messages = [{"role": "user", "content": "Add retry logic."}]
        summary = await summarizer.summarize(messages=messages, previous_summary=prev, tick=7)
        # LLM was called with previous summary context
        call = fake_llm.calls[0]
        assert "Used Decimal" in call["system"]
        assert summary.generated_at_tick == 7

    @pytest.mark.asyncio
    async def test_summarize_error_fallback(
        self, summarizer: SessionSummarizer, fake_llm: _FakeLLM
    ) -> None:
        """When LLM call fails, summarize() returns a minimal degraded summary."""
        async def _fail(*args, **kwargs):
            raise RuntimeError("LLM down")
        fake_llm.create_message = _fail  # type: ignore[assignment]
        messages = [{"role": "user", "content": "Fix bug."}]
        summary = await summarizer.summarize(messages=messages, previous_summary=None, tick=6)
        assert summary.generated_at_tick == 6
        assert isinstance(summary.key_implementation_decisions, list)

    def test_inject_into_prompt_formats_summary(self, summarizer: SessionSummarizer) -> None:
        """inject_into_prompt() formats the summary as a structured prompt prefix."""
        s = SessionSummary(
            ticks_covered=range(1, 6),
            key_implementation_decisions=["Used Decimal for money"],
            files_created_modified={"src/payment.py": "Payment module", "tests/test_payment.py": "11 tests"},
            major_history=[],
            unresolved_issues=["Batch insert slow"],
            generated_at_tick=5,
        )
        injected = summarizer.inject_into_prompt(s)
        assert "Previous Session Summary" in injected
        assert "Used Decimal for money" in injected
        assert "src/payment.py" in injected
        assert "Batch insert slow" in injected

    def test_inject_into_prompt_empty_summary(self, summarizer: SessionSummarizer) -> None:
        """Empty summary produces a minimal prompt prefix."""
        s = SessionSummary(
            ticks_covered=range(1, 1),
            key_implementation_decisions=[],
            files_created_modified={},
            major_history=[],
            unresolved_issues=[],
            generated_at_tick=0,
        )
        injected = summarizer.inject_into_prompt(s)
        assert "Previous Session Summary" in injected

    def test_structured_summary_collects_current_and_previous_state(self) -> None:
        previous = SessionSummary(
            ticks_covered=range(1, 3),
            files_created_modified={"src/old.py": ""},
            major_history=[{"tick": 2, "findings": ["old finding"]}],
            unresolved_issues=["old issue"],
            generated_at_tick=2,
        )
        summary = SessionSummarizer().summarize_structured(
            tick=4,
            test_results={"passed": 3, "total": 3},
            files_changed=["src/new.py"],
            commit_hash="abcdef123456",
            gate_results={"lint": {"passed": True}},
            critic_verdict="APPROVE",
            total_majors=1,
            batch_progress="1/2",
            previous_summary=previous,
        )

        assert summary.ticks_covered == range(3, 5)
        assert "batch_progress: 1/2" in summary.key_implementation_decisions
        assert "commit=abcdef12" in summary.key_implementation_decisions
        assert "tests: 3/3 passed" in summary.key_implementation_decisions
        assert "all gates passed" in summary.key_implementation_decisions
        assert "critic: APPROVE (total MAJORs=1)" in summary.key_implementation_decisions
        assert set(summary.files_created_modified) == {"src/new.py", "src/old.py"}
        assert summary.major_history == previous.major_history
        assert summary.unresolved_issues == previous.unresolved_issues

    def test_structured_summary_records_failed_gate_and_major(self) -> None:
        summary = SessionSummarizer().summarize_structured(
            tick=2,
            test_results={"passed": 1, "total": 2},
            gate_results={"test": {"passed": False}},
            critic_verdict="MAJOR",
            total_majors=2,
        )

        assert "tests: 1/2 passed" in summary.key_implementation_decisions
        assert "failed gates: test" in summary.unresolved_issues
        assert "critic: MAJOR (total MAJORs=2)" in summary.unresolved_issues

    @pytest.mark.asyncio
    async def test_summarize_without_provider_fails_explicitly(self) -> None:
        with pytest.raises(RuntimeError, match="LLM provider required"):
            await SessionSummarizer().summarize([], None, 1)

    def test_close_releases_provider(self) -> None:
        llm = _FakeLLM()
        closed = []
        llm.close = lambda: closed.append(True)

        SessionSummarizer(llm).close()

        assert closed == [True]
