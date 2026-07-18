"""Tests for auto_engineering.observability.tracing — OTLP tracing setup (T60)."""

from __future__ import annotations

from unittest.mock import patch

# Lazy imports are inside setup_tracing() — patch at source module location.
_OTLP_EXPORTER = "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
_BSP = "opentelemetry.sdk.trace.export.BatchSpanProcessor"
_RESOURCE = "opentelemetry.sdk.resources.Resource"
_TP = "opentelemetry.sdk.trace.TracerProvider"
_SET_TP = "opentelemetry.trace.set_tracer_provider"
_GET_TRACER = "opentelemetry.trace.get_tracer"


class TestSetupTracing:
    """setup_tracing() function tests."""

    def test_no_endpoint_returns_noop_tracer(self) -> None:
        """When otlp_endpoint is None, returns a NoOp tracer (zero overhead)."""
        from auto_engineering.observability.tracing import setup_tracing

        tracer = setup_tracing(otlp_endpoint=None)
        with tracer.start_as_current_span("test") as span:
            assert not span.is_recording()

    def test_no_endpoint_does_not_import_opentelemetry_sdk(self) -> None:
        """NoOp path does not trigger heavy SDK imports (lazy import)."""
        import sys

        sys.modules.pop("auto_engineering.observability.tracing", None)
        for mod in list(sys.modules):
            if mod.startswith("opentelemetry.sdk"):
                del sys.modules[mod]

        with patch("builtins.__import__", wraps=__import__) as mock_import:
            from auto_engineering.observability.tracing import setup_tracing

            tracer = setup_tracing(otlp_endpoint=None)
            with tracer.start_as_current_span("test"):
                pass
            sdk_imports = [
                c.args[0]
                for c in mock_import.call_args_list
                if isinstance(c.args[0], str) and "opentelemetry.sdk" in c.args[0]
            ]
            assert len(sdk_imports) == 0, f"Unexpected SDK imports: {sdk_imports}"

    def test_with_endpoint_creates_real_tracer(self) -> None:
        """OTLP endpoint set → creates TracerProvider with OTLPSpanExporter."""
        with patch(_OTLP_EXPORTER) as mock_exp, \
             patch(_BSP) as mock_bsp, \
             patch(_RESOURCE), \
             patch(_TP) as mock_tp, \
             patch(_SET_TP) as mock_set_tp, \
             patch(_GET_TRACER) as mock_get_tracer:
            from auto_engineering.observability.tracing import setup_tracing

            tracer = setup_tracing(otlp_endpoint="http://localhost:4317")
            mock_exp.assert_called_once_with(endpoint="http://localhost:4317")
            mock_bsp.assert_called_once()
            mock_tp.assert_called_once()
            mock_set_tp.assert_called_once()
            mock_get_tracer.assert_called_once_with("auto-engineering")
            assert tracer is mock_get_tracer.return_value

    def test_default_service_name(self) -> None:
        """Default service_name is 'auto-engineering'."""
        with patch(_OTLP_EXPORTER), \
             patch(_BSP), \
             patch(_RESOURCE) as mock_resource, \
             patch(_TP), \
             patch(_SET_TP), \
             patch(_GET_TRACER):
            from auto_engineering.observability.tracing import setup_tracing

            setup_tracing(otlp_endpoint="http://localhost:4317")
            call_kwargs = mock_resource.create.call_args.kwargs
            assert call_kwargs["attributes"]["service.name"] == "auto-engineering"

    def test_custom_service_name(self) -> None:
        """Custom service_name is passed to Resource."""
        with patch(_OTLP_EXPORTER), \
             patch(_BSP), \
             patch(_RESOURCE) as mock_resource, \
             patch(_TP), \
             patch(_SET_TP), \
             patch(_GET_TRACER):
            from auto_engineering.observability.tracing import setup_tracing

            setup_tracing(service_name="my-service", otlp_endpoint="http://localhost:4317")
            call_kwargs = mock_resource.create.call_args.kwargs
            assert call_kwargs["attributes"]["service.name"] == "my-service"

    def test_tracer_can_set_span_attributes(self) -> None:
        """Tracer creates spans that accept attributes."""
        with patch(_OTLP_EXPORTER), \
             patch(_BSP), \
             patch(_RESOURCE), \
             patch(_TP), \
             patch(_SET_TP), \
             patch(_GET_TRACER):
            from auto_engineering.observability.tracing import setup_tracing

            tracer = setup_tracing(otlp_endpoint="http://localhost:4317")
            with tracer.start_as_current_span("tick") as span:
                span.set_attribute("tick_number", 1)
                span.set_attribute("stage", "architect")
