"""Cross-tick developer session summarization.

Design ref: v5.6-Design-Loop.md appendix E §E.2.3 (T54).

When the developer's main session exceeds a configurable tick threshold (default 5),
the previous N-1 ticks' conversation history is compressed into a structured summary
and injected as a prefix into the next tick's developer system prompt.

Only the developer role needs this — the other 6 roles spawn fresh subagents each tick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Inlined from providers/base.py (Phase 40 consolidation) ──

@dataclass
class ToolUseBlock:
    """Unified tool-use representation across LLM providers."""
    id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Unified LLM response across providers."""
    content: str = ""
    model: str = ""
    stop_reason: str = "end_turn"
    tool_use_blocks: list[ToolUseBlock] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM provider backends."""
    async def create_message(
        self, system: str, messages: list[dict],
        tools: list[dict] | None = None, model: str = "", max_tokens: int = 4096,
    ) -> LLMResponse: ...
    def close(self) -> None: ...

_SUMMARIZE_SYSTEM_PROMPT = """\
You are a session summarizer for a TDD development loop. Given the conversation
history below, produce a structured summary with:
1. Key implementation decisions made
2. Files created/modified and what changed
3. Any MAJOR review findings and how they were resolved
4. Unresolved issues still open

Output format: one line per item, prefixed with its category.
Example:
DECISION: Used Decimal for monetary calculations
FILE: src/payment.py — Payment module with retry logic
MAJOR(tick 3): Missing null check in calculate() — FIXED by adding guard
ISSUE: Batch insert performance needs profiling
"""


@dataclass
class SessionSummary:
    """Cross-tick developer session summary."""

    ticks_covered: range
    key_implementation_decisions: list[str] = field(default_factory=list)
    files_created_modified: dict[str, str] = field(default_factory=dict)
    major_history: list[dict] = field(default_factory=list)
    unresolved_issues: list[str] = field(default_factory=list)
    generated_at_tick: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为 checkpoint 可序列化结构。"""
        return {
            "ticks_covered": {
                "start": self.ticks_covered.start,
                "stop": self.ticks_covered.stop,
                "step": self.ticks_covered.step,
            },
            "key_implementation_decisions": list(
                self.key_implementation_decisions
            ),
            "files_created_modified": dict(self.files_created_modified),
            "major_history": list(self.major_history),
            "unresolved_issues": list(self.unresolved_issues),
            "generated_at_tick": self.generated_at_tick,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionSummary:
        """从 checkpoint 结构恢复滚动摘要。"""
        ticks = data.get("ticks_covered", {})
        return cls(
            ticks_covered=range(
                int(ticks.get("start", 1)),
                int(ticks.get("stop", 1)),
                int(ticks.get("step", 1)),
            ),
            key_implementation_decisions=list(
                data.get("key_implementation_decisions", [])
            ),
            files_created_modified=dict(
                data.get("files_created_modified", {})
            ),
            major_history=list(data.get("major_history", [])),
            unresolved_issues=list(data.get("unresolved_issues", [])),
            generated_at_tick=int(data.get("generated_at_tick", 0)),
        )


class SessionSummarizer:
    """Rolling summarizer for cross-tick developer context.

    Two implementation modes:
    - **LLM mode** (llm_provider is set): calls Haiku to compress conversation
      history into a structured summary. This optional injection point currently
      has no production consumer.
    - **Structured mode** (llm_provider is None): generates summary from
      state metadata (test results, files changed, gate results) without
      any LLM call. This is the host-neutral Core path.

    Usage::

        # Optional injected LLM summarization
        summarizer = SessionSummarizer(anthropic_provider)
        if summarizer.should_summarize(tick):
            summary = await summarizer.summarize(messages, prev_summary, tick)
            prompt_prefix = summarizer.inject_into_prompt(summary)

        # Host-neutral structured summary (no LLM in Core)
        summarizer = SessionSummarizer()
        if summarizer.should_summarize(tick):
            summary = summarizer.summarize_structured(
                tick=tick, test_results={...}, files_changed=[...],
                commit_hash="abc123", gate_results={...},
                previous_summary=prev_summary)
            prompt_prefix = summarizer.inject_into_prompt(summary)
    """

    def __init__(self, llm_provider: LLMProvider | None = None, max_summary_words: int = 500) -> None:
        self._llm = llm_provider
        self._max_words = max_summary_words

    # ---- public API ----------------------------------------------------

    def should_summarize(self, current_tick: int, threshold: int = 5) -> bool:
        """Return True when *current_tick* exceeds *threshold*."""
        return current_tick > threshold

    async def summarize(
        self,
        messages: list[dict],
        previous_summary: SessionSummary | None,
        tick: int,
    ) -> SessionSummary:
        """Generate a rolling summary by asking the LLM to compress *messages*.

        If *previous_summary* is given its key decisions are included in the
        prompt so the LLM can merge old + new into one coherent summary.
        """
        system = _SUMMARIZE_SYSTEM_PROMPT
        if previous_summary is not None:
            system += _render_previous_summary(previous_summary)

        user_content = _render_messages_for_summary(messages)
        if self._llm is None:
            raise RuntimeError("LLM provider required for summarize(); use summarize_structured() instead")
        try:
            response: LLMResponse = await self._llm.create_message(
                system=system,
                messages=[{"role": "user", "content": user_content}],
                model="",  # let provider pick default (Haiku for cost)
                max_tokens=1024,
            )
            decisions, files, majors, issues = _parse_summary_response(response.content)
        except Exception:
            # LLM call can fail for any SDK error type. Summarization is best-effort
            # degradation — failure must never crash the loop. (P0-5: LLM tool handler exemption)
            logger.warning("Session summarization failed, using degraded summary", exc_info=True)
            decisions, files, majors, issues = (
                ["(summarization failed — see offload files for details)"],
                {},
                [],
                [],
            )

        return SessionSummary(
            ticks_covered=(
                range(1, tick + 1)
                if previous_summary is None
                else range(previous_summary.generated_at_tick + 1, tick + 1)
            ),
            key_implementation_decisions=decisions,
            files_created_modified=files,
            major_history=majors,
            unresolved_issues=issues,
            generated_at_tick=tick,
        )

    def summarize_structured(
        self,
        *,
        tick: int,
        test_results: dict | None = None,
        files_changed: list[str] | None = None,
        commit_hash: str = "",
        gate_results: dict | None = None,
        critic_verdict: str = "",
        total_majors: int = 0,
        batch_progress: str = "",
        previous_summary: SessionSummary | None = None,
    ) -> SessionSummary:
        """Generate summary from state metadata — no LLM call.

        This is the host-neutral Core path: the engine does not have an LLM
        provider, but it has structured data from the result JSON.
        Produces a SessionSummary with the same shape as the LLM path
        so downstream consumers (inject_into_prompt, offload) are
        identical regardless of mode.

        DS-14 (T166, 2026-07-23): 新增 batch_progress 参数，从 engine state
        聚合 batch 级别进度信息（已完成 batch 数、plan_refine 次数等）。
        """
        tr = test_results or {}
        decisions: list[str] = []
        files: dict[str, str] = {}
        majors: list[dict] = []
        issues: list[str] = []

        # Batch progress (DS-14 T166: aggregated from engine state)
        if batch_progress:
            decisions.append(f"batch_progress: {batch_progress}")

        # Key decisions from this tick
        if commit_hash:
            decisions.append(f"commit={commit_hash[:8]}")
        passed = tr.get("passed", 0)
        total = tr.get("total", 0)
        if total > 0:
            decisions.append(f"tests: {passed}/{total} passed")
        if gate_results:
            failed_gates = [k for k, v in gate_results.items()
                            if isinstance(v, dict) and not v.get("passed", True)]
            if failed_gates:
                issues.append(f"failed gates: {', '.join(failed_gates)}")
            else:
                decisions.append("all gates passed")

        # Critic verdict history
        if critic_verdict:
            if critic_verdict == "APPROVE":
                decisions.append(f"critic: APPROVE (total MAJORs={total_majors})")
            elif critic_verdict == "MAJOR":
                issues.append(f"critic: MAJOR (total MAJORs={total_majors})")

        # Files changed — group by directory for readability
        for f in (files_changed or []):
            files[f] = ""

        # Carry forward previous state
        if previous_summary is not None:
            if previous_summary.unresolved_issues:
                issues.extend(previous_summary.unresolved_issues)
            if previous_summary.major_history:
                majors.extend(previous_summary.major_history)
            # Accumulate file list across ticks
            if previous_summary.files_created_modified:
                for fpath in previous_summary.files_created_modified:
                    if fpath not in files:
                        files[fpath] = ""

        return SessionSummary(
            ticks_covered=(
                range(1, tick + 1)
                if previous_summary is None
                else range(previous_summary.generated_at_tick + 1, tick + 1)
            ),
            key_implementation_decisions=decisions,
            files_created_modified=files,
            major_history=majors,
            unresolved_issues=issues,
            generated_at_tick=tick,
        )

    def close(self) -> None:
        """Release underlying LLM provider resources if any."""
        if self._llm is not None and hasattr(self._llm, "close"):
            self._llm.close()

    def inject_into_prompt(self, summary: SessionSummary) -> str:
        """Format *summary* as a developer system-prompt prefix."""
        lines = [
            "## Previous Session Summary",
            "",
            f"Covering ticks {summary.ticks_covered.start}–{summary.ticks_covered.stop - 1}:",
            "",
        ]
        if summary.key_implementation_decisions:
            lines.append("### Key Decisions")
            for d in summary.key_implementation_decisions:
                lines.append(f"- {d}")
            lines.append("")
        if summary.files_created_modified:
            lines.append("### Files Changed")
            for path, desc in summary.files_created_modified.items():
                lines.append(f"- `{path}` — {desc}")
            lines.append("")
        if summary.major_history:
            lines.append("### MAJOR Findings History")
            for m in summary.major_history:
                tick = m.get("tick", "?")
                findings = m.get("findings", [])
                lines.append(f"- Tick {tick}: {'; '.join(findings)}")
            lines.append("")
        if summary.unresolved_issues:
            lines.append("### Unresolved Issues")
            for issue in summary.unresolved_issues:
                lines.append(f"- {issue}")
            lines.append("")
        lines.append("Continue from where you left off.")
        return "\n".join(lines)


# ---- internal helpers --------------------------------------------------------

def _render_previous_summary(prev: SessionSummary) -> str:
    lines = [
        "",
        "## Previous Session Summary (merge into new summary)",
        "",
        f"Previous ticks: {prev.ticks_covered.start}–{prev.ticks_covered.stop - 1}",
    ]
    if prev.key_implementation_decisions:
        lines.append("Previous decisions:")
        lines.extend(f"  - {d}" for d in prev.key_implementation_decisions)
    if prev.major_history:
        lines.append("Previous MAJOR findings:")
        for m in prev.major_history:
            lines.append(f"  - Tick {m.get('tick', '?')}: {'; '.join(m.get('findings', []))}")
    if prev.unresolved_issues:
        lines.append("Previous unresolved:")
        lines.extend(f"  - {i}" for i in prev.unresolved_issues)
    return "\n".join(lines)


def _render_messages_for_summary(messages: list[dict]) -> str:
    """Render messages as a compact text block for the summarizer."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            text = str(content)
        # Truncate very long messages so the summary prompt stays bounded.
        if len(text) > 2000:
            text = text[:2000] + "..."
        parts.append(f"[{role}]: {text}")
    return "\n\n".join(parts)


def _parse_summary_response(text: str) -> tuple[list[str], dict[str, str], list[dict], list[str]]:
    """Parse the LLM's free-form summary into structured fields."""
    decisions: list[str] = []
    files: dict[str, str] = {}
    majors: list[dict] = []
    issues: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("DECISION:"):
            decisions.append(line.removeprefix("DECISION:").strip())
        elif line.startswith("FILE:"):
            parts = line.removeprefix("FILE:").strip().split(" — ", 1)
            path = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            files[path] = desc
        elif line.startswith("MAJOR"):
            majors.append({"raw": line.removeprefix("MAJOR").strip("(): ")})
        elif line.startswith("ISSUE:"):
            issues.append(line.removeprefix("ISSUE:").strip())
        else:
            # Non-prefixed line — append as continuation to last decision
            if decisions:
                decisions[-1] += " " + line.strip()
            elif issues:
                issues[-1] = issues[-1] + " " + line.strip()

    return decisions, files, majors, issues
