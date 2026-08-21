"""Stage 上下文摘要与持久化服务。"""

from __future__ import annotations

import logging
from typing import Protocol

from auto_engineering.context.summarization import SessionSummary
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.state import EngineState

_logger = logging.getLogger(__name__)


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class Offloader(Protocol):
    def offload(
        self,
        stage: str,
        messages: list[dict],
        summary: str,
        key_decisions: list[str],
        files_changed: list[str],
        gate_results: dict,
    ) -> object: ...


class Summarizer(Protocol):
    def should_summarize(self, current_tick: int, threshold: int = 5) -> bool: ...

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
    ) -> SessionSummary: ...

    def inject_into_prompt(self, summary: SessionSummary) -> str: ...


class StageOffloadService:
    """生成有界 Stage 摘要并委托 Offloader 持久化。"""

    def __init__(
        self,
        *,
        offloader: Offloader,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._offloader = offloader
        self._summarizer = summarizer

    def offload(
        self,
        stage: str,
        *,
        state: EngineState,
        batch_state: BatchState | None,
        cached_summary: SessionSummary | None,
    ) -> SessionSummary | None:
        summary = f"{stage} stage completed at tick {state.tick}/{state.round}"
        key_decisions: list[str] = []
        files_changed = list(state.files_changed or [])
        if stage == "architect":
            summary, key_decisions = self._architect_summary(state)
        elif stage == "developer":
            summary, key_decisions, cached_summary = self._developer_summary(
                state,
                batch_state,
                cached_summary,
            )
        elif stage == "critic":
            summary, key_decisions = self._critic_summary(state)

        messages: list[dict] = []
        if cached_summary is not None and self._summarizer is not None:
            context = self._summarizer.inject_into_prompt(cached_summary)
            if context:
                messages = [{"role": "system", "content": context}]
        self._offloader.offload(
            stage=stage,
            messages=messages,
            summary=summary,
            key_decisions=key_decisions,
            files_changed=files_changed,
            gate_results=dict(state.gate_results or {}),
        )
        return cached_summary

    @staticmethod
    def _architect_summary(state: EngineState) -> tuple[str, list[str]]:
        plan = state.plan or ""
        preview = (plan[:120] + "...") if len(plan) > 120 else plan
        batch_info = (
            f"{len(state.batch_plan)} batches, {len(state.file_list or [])} files"
            if state.batch_plan
            else "no batches"
        )
        summary = f"Architect: {batch_info}"
        if preview:
            summary += f" — {preview}"
        decisions = []
        if state.batch_plan:
            decisions = [
                f"batch_count={len(state.batch_plan)}",
                f"file_count={len(state.file_list or [])}",
                f"plan_first_line={preview[:80] if preview else 'N/A'}",
            ]
        return summary, decisions

    def _developer_summary(
        self,
        state: EngineState,
        batch_state: BatchState | None,
        cached_summary: SessionSummary | None,
    ) -> tuple[str, list[str], SessionSummary | None]:
        results = state.test_results or {}
        passed = results.get("passed", 0)
        total = results.get("total")
        if total is None:
            total = sum(
                _as_int(results.get(key, 0))
                for key in ("passed", "failed", "errors", "skipped")
            )
        summary = f"Developer: {passed}/{total} tests passed"
        if batch_state is not None:
            try:
                if batch_state.is_all_complete():
                    summary = (
                        "Developer: all batches completed — "
                        f"{passed}/{total} tests passed"
                    )
                elif batch_state.is_plate_complete():
                    summary = (
                        "Developer: plate completed — "
                        f"{passed}/{total} tests passed"
                    )
                elif batch_state.is_component_complete():
                    name = batch_state.current_component().name
                    summary = (
                        f"Developer: {name} completed — "
                        f"{passed}/{total} tests passed"
                    )
                else:
                    component = batch_state.current_component()
                    batch_id = batch_state.current_batch_id()
                    name = component.name if component else "?"
                    summary = (
                        f"Developer: {name} batch={batch_id} — "
                        f"{passed}/{total} tests passed"
                    )
            except (AssertionError, AttributeError, TypeError, ValueError) as exc:
                _logger.warning(
                    "batch_state component/batch access failed, using degraded summary: %s",
                    exc,
                )
        decisions: list[str] = []
        if state.commit_hash:
            decisions.append(f"commit={state.commit_hash[:8]}")
        if state.critic_feedback:
            decisions.append(f"critic_feedback={state.critic_feedback[:120]}")
        if state.files_changed:
            decisions.append(f"files_changed_count={len(state.files_changed)}")
        if self._summarizer is not None and self._summarizer.should_summarize(state.tick):
            try:
                progress = self._batch_progress(batch_state)
                generated = self._summarizer.summarize_structured(
                    tick=state.tick,
                    test_results=dict(results),
                    files_changed=list(state.files_changed or []),
                    commit_hash=state.commit_hash or "",
                    gate_results=dict(state.gate_results or {}),
                    critic_verdict=state.critic_verdict or "",
                    total_majors=state.total_majors,
                    batch_progress=progress,
                    previous_summary=cached_summary,
                )
                injected = self._summarizer.inject_into_prompt(generated)
                if injected:
                    summary = injected[:200]
                    decisions.append("summarized=true")
                    cached_summary = generated
            except Exception:
                _logger.warning("SessionSummarizer failed for offload", exc_info=True)
        return summary, decisions, cached_summary

    @staticmethod
    def _batch_progress(batch_state: BatchState | None) -> str:
        if batch_state is None:
            return ""
        try:
            return (
                f"{batch_state.current_batch_idx}/"
                f"{batch_state.total_batches} batches done"
            )
        except Exception:
            _logger.warning("batch_state done/total count failed", exc_info=True)
            return ""

    @staticmethod
    def _critic_summary(state: EngineState) -> tuple[str, list[str]]:
        findings = state.findings or []
        counts = {
            severity: sum(
                1 for finding in findings if finding.get("severity") == severity
            )
            for severity in ("P0", "P1", "P2")
        }
        summary = (
            f"Critic: {state.critic_verdict or 'N/A'} | "
            f"P0={counts['P0']} P1={counts['P1']} P2={counts['P2']}"
        )
        decisions = (
            [f"feedback={state.critic_feedback[:200]}"]
            if state.critic_feedback
            else []
        )
        return summary, decisions


__all__ = ["StageOffloadService"]
