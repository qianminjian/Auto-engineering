"""OpenTelemetry OTLP tracing setup (T60).

Design ref: v5.6-Design-Loop.md appendix E §E.6.1.

When AE_OTLP_ENDPOINT is not set, setup_tracing() returns a NoOp tracer —
zero overhead, no SDK imports triggered.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    pass

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
    import os as _os

    from opentelemetry import trace as otel_trace

    if not otlp_endpoint:
        return otel_trace.get_tracer(service_name)

    # DS-14 (T162, 2026-07-23): 检查是否已有有效 TracerProvider（Claude Code 已初始化）
    # Skip in test mode (AE_OTLP_SKIP_PROBE=1) — tests need clean provider state.
    if _os.environ.get("AE_OTLP_SKIP_PROBE") != "1":
        current_provider = otel_trace.get_tracer_provider()
        from opentelemetry.trace import ProxyTracerProvider
        if not isinstance(current_provider, ProxyTracerProvider):
            _logger.debug("TracerProvider 已由外部初始化，复用现有 provider")
            return otel_trace.get_tracer(service_name)

    # DS-14 (T158, 2026-07-23): 先做 connectivity probe，不可达 → 静默降级
    # Skip probe in CI/unit-test environments (AE_OTLP_SKIP_PROBE=1)
    if _os.environ.get("AE_OTLP_SKIP_PROBE") != "1":
        from urllib.parse import urlparse
        parsed = urlparse(otlp_endpoint)
        import socket
        try:
            host = parsed.hostname or "localhost"
            port = parsed.port or 4317
            with socket.create_connection((host, port), timeout=2):
                pass
        except (TimeoutError, OSError):
            _logger.warning(
                "OTLP collector %s 不可达 — 降级为 NoOp tracer（本会话仅告警一次）",
                otlp_endpoint,
            )
            # 设置环境变量为空，避免后续 tick 重复探测
            _os.environ.pop("AE_OTLP_ENDPOINT", None)
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
