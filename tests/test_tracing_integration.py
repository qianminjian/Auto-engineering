"""T76 Integration tests — setup_tracing() wired into CLI entry point.

Test layers:
  Layer 1 (Unit) — existing tests in test_tracing.py
  Layer 2 (Integration) — CLI main() calls setup_tracing() via AE_OTLP_ENDPOINT env
  Layer 3 (E2E) — full CLI invocation triggers tracing setup

RED phase: These tests FAIL because:
  - CLI main() does not call setup_tracing()
  - No TracerProvider is configured at CLI startup

Design ref: v5.6-Design-Loop.md appendix E §E.6.1 (T60).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from auto_engineering.observability.tracing import setup_tracing


class TestSetupTracingWiring:
    """T76: Verify setup_tracing() is wired into CLI entry point."""

    def test_setup_tracing_exists_and_callable(self) -> None:
        """setup_tracing() must be importable and callable."""
        tracer = setup_tracing("test-service")
        assert tracer is not None

    def test_cli_main_calls_setup_tracing(self) -> None:
        """CLI main() MUST call setup_tracing() at startup.

        Verifies that the Click group callback (main function) invokes
        setup_tracing with service_name='auto-engineering' and the
        AE_OTLP_ENDPOINT env var.
        """
        import auto_engineering.cli as cli_module

        cli_file = Path(cli_module.__file__) if cli_module.__file__ else Path(".")
        source = cli_file.read_text()
        assert "setup_tracing" in source, (
            "T76 NOT WIRED: CLI __init__.py does not import or call setup_tracing(). "
            "OTLP tracing will never activate in production."
        )

    def test_setup_tracing_returns_noop_when_endpoint_not_set(self) -> None:
        """When AE_OTLP_ENDPOINT is not set, setup_tracing returns a NoOp tracer."""
        with patch.dict(os.environ, {}, clear=True):
            tracer = setup_tracing("ae-test")
            with tracer.start_as_current_span("test") as span:
                span.set_attribute("key", "val")
        # No exception = pass

    @patch.dict(os.environ, {"AE_OTLP_ENDPOINT": "http://localhost:4317"})
    def test_setup_tracing_activates_with_endpoint(self) -> None:
        """When AE_OTLP_ENDPOINT is set, setup_tracing configures OTLP exporter."""
        tracer = setup_tracing("ae-test-otlp")
        assert tracer is not None

    def test_cli_main_function_references_tracing(self) -> None:
        """CLI main() function body MUST reference setup_tracing.

        RED: Currently main() only configures logging, not tracing.
        """
        import auto_engineering.cli as cli_module

        cli_file = Path(cli_module.__file__) if cli_module.__file__ else Path(".")
        source = cli_file.read_text()

        # Check that the main() function body contains setup_tracing call
        main_section = source[source.find("def main()"):source.find("def dev_loop")]
        assert "setup_tracing" in main_section, (
            "T76 NOT WIRED: CLI main() function does not call setup_tracing(). "
            "The main() function only configures logging — tracing setup is missing."
        )


class TestTracingE2E:
    """E2E: tracing activates through CLI env var path."""

    def test_noop_tracer_does_not_throw(self) -> None:
        """NoOp tracer span context manager does not throw."""
        tracer = setup_tracing("ae-e2e")
        with tracer.start_as_current_span("e2e-test") as span:
            span.set_attribute("test", "value")
        # No exception = pass

    def test_otel_sdk_not_imported_without_endpoint(self) -> None:
        """Without AE_OTLP_ENDPOINT, OTLP SDK modules should not be loaded."""
        import sys

        with patch.dict(os.environ, {}, clear=True):
            # Remove otel SDK if previously loaded by other tests
            for mod in list(sys.modules.keys()):
                if 'opentelemetry.sdk' in mod or 'opentelemetry.exporter' in mod:
                    del sys.modules[mod]
            tracer = setup_tracing("ae-noop")
            assert tracer is not None
            sdk_loaded = any(
                'opentelemetry.sdk' in m for m in sys.modules)
            assert not sdk_loaded, (
                "OTLP SDK should not be loaded when AE_OTLP_ENDPOINT is not set"
            )
