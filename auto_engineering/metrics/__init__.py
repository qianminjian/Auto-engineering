"""Auto-Engineering Metrics — AI Coding 度量与自进化体系 (Phase 20-21)."""

from auto_engineering.metrics.collector import AIOrigin, MetricsCollector, get_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.metrics.signals import SignalDetector
from auto_engineering.metrics.usage import UsageRecord

__all__ = [
    "AIOrigin",
    "MetricsCollector",
    "SignalDetector",
    "UsageRecord",
    "compute_metrics_signals",
    "get_collector",
]
