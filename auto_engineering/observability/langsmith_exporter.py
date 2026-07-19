"""LangSmith exporter — optional trace export to LangSmith (T93).

Activated by AE_LANGSMITH=1 + LANGCHAIN_API_KEY env vars.
Integrates with AnthropicProvider to export LLM call traces.

Design ref: BEACON decisions #67/68.
"""

from __future__ import annotations

import logging
import os

_logger = logging.getLogger("ae.observability.langsmith")


def is_available() -> bool:
    """Check whether LangSmith SDK is installed and configured."""
    try:
        import langsmith  # noqa: F401
        return True
    except ImportError:
        return False


def is_enabled() -> bool:
    """Check whether LangSmith export is enabled via env vars."""
    return (
        os.environ.get("AE_LANGSMITH", "").strip() == "1"
        and bool(os.environ.get("LANGCHAIN_API_KEY"))
        and is_available()
    )


class LangSmithExporter:
    """Exports LLM call traces to LangSmith.

    Creates a RunTree per LLM call and posts it to LangSmith.
    Usage::

        exporter = LangSmithExporter()
        exporter.export_call(
            stage="architect",
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_messages=[...],
            output={"content": "...", "stop_reason": "end_turn"},
            tokens_prompt=1000,
            tokens_completion=200,
            duration_ms=1500,
        )
    """

    def __init__(self) -> None:
        self._available = is_enabled()

    def export_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        input_messages: list[dict],
        output: dict,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Export a single LLM call as a LangSmith run."""
        if not self._available:
            return
        try:
            from langsmith import Client  # type: ignore[import-untyped]
            client = Client()
            client.create_run(
                name=f"{stage}.{provider}",
                run_type="llm",
                inputs={"messages": input_messages},
                outputs=output,
                extra={
                    "metadata": {
                        "stage": stage,
                        "provider": provider,
                        "model": model,
                        "tokens_prompt": tokens_prompt,
                        "tokens_completion": tokens_completion,
                        "duration_ms": duration_ms,
                    },
                },
            )
        except Exception:
            _logger.warning("LangSmith export failed", exc_info=True)


# Module-level singleton
_exporter: LangSmithExporter | None = None


def get_exporter() -> LangSmithExporter:
    """Get or create the module-level LangSmithExporter singleton."""
    global _exporter
    if _exporter is None:
        _exporter = LangSmithExporter()
    return _exporter
