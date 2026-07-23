"""OpenTelemetry OTLP tracing setup (T60).

Design ref: v5.6-Design-Loop.md appendix E §E.6.1.

When AE_OTLP_ENDPOINT is not set, setup_tracing() returns a NoOp tracer —
zero overhead, no SDK imports triggered.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

_logger = logging.getLogger("ae.observability.tracing")


class _TracerLike(Protocol):
    """Minimal tracer interface — duck-typed by opentelemetry Tracer + NoOpTracer.

    T135g: start_span is the canonical method (matches tick_orchestrator usage).
    start_as_current_span removed — never called in codebase.
    """

    def start_span(
        self, name: str, attributes: dict | None = None
    ) -> object: ...


def setup_tracing(
    service_name: str = "auto-engineering",
    otlp_endpoint: str | None = None,
) -> _TracerLike:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: service.name attribute in OTLP resource.
        otlp_endpoint: OTLP collector gRPC address (e.g. "http://localhost:4317").
            When None, returns a NoOp tracer (zero overhead).

    Returns:
        A tracer object with start_span() interface.
    """
    import logging
    _logger = logging.getLogger("ae.observability.tracing")

    from opentelemetry import trace as otel_trace

    if not otlp_endpoint:
        return otel_trace.get_tracer(service_name)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(attributes={"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        return otel_trace.get_tracer(service_name)
    except Exception:
        _logger.warning(
            "OTLP tracing setup failed for endpoint=%s — falling back to NoOp tracer. "
            "Check that the collector is reachable and grpc dependencies are installed.",
            otlp_endpoint, exc_info=True,
        )
        return otel_trace.get_tracer(service_name)
