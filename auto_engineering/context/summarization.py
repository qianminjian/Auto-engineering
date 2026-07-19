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

from auto_engineering.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

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


class SessionSummarizer:
    """Rolling summarizer for cross-tick developer context.

    Usage::

        summarizer = SessionSummarizer(anthropic_provider)
        if summarizer.should_summarize(tick):
            summary = await summarizer.summarize(messages, prev_summary, tick)
            prompt_prefix = summarizer.inject_into_prompt(summary)
            # prepend prompt_prefix to developer system prompt
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

        if self._llm is None:
            logger.warning("SessionSummarizer has no LLM provider — returning empty summary")
            return SessionSummary(
                ticks_covered=range(1, tick + 1),
                generated_at_tick=tick,
            )

        user_content = _render_messages_for_summary(messages)
        try:
            response: LLMResponse = await self._llm.create_message(
                system=system,
                messages=[{"role": "user", "content": user_content}],
                model="",  # let provider pick default (Haiku for cost)
                max_tokens=1024,
            )
            decisions, files, majors, issues = _parse_summary_response(response.content)
        except Exception as exc:
            logger.warning("Session summarization failed, using degraded summary", exc_info=True)
            decisions, files, majors, issues = (
                [f"(summarization failed: {exc} — see offload files for details)"],
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
            # Non-prefixed lines are appended to the last decision or issue
            pass

    return decisions, files, majors, issues
