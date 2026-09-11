"""MetricsCollector 门面：只从 EventStore 投影并物化派生摘要。"""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from auto_engineering.metrics._aggregator import _MetricsAggregator
from auto_engineering.metrics._persistence import _MetricsPersistence
from auto_engineering.metrics.event_projection import project_metrics_events

if TYPE_CHECKING:
    from auto_engineering.loop.event_store import SQLiteEventStore

_logger = logging.getLogger(__name__)


@dataclass
class AIOrigin:
    """AI 溯源标记 — 每个度量事件的标准元信息.

    规范: v5.6-Design-Loop.md 附录 F.2.1.
    """
    level: Literal["none", "assisted", "led", "autonomous"] = "led"
    agent_role: str = ""        # architect / developer / critic / verifier
    model_name: str = ""        # claude-sonnet-4-6 / deepseek-v3 / glm-4
    model_version: str = ""     # 模型版本号
    driver_type: str = ""       # agent / standalone

    def to_dict(self) -> dict:
        """Serialize to dict for event payloads."""
        return {
            "level": self.level,
            "agent_role": self.agent_role,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "driver_type": self.driver_type,
        }


# CLI 设置单例，Agent hook 读取；锁保护进程内访问，跨 Tick 不保留状态。
_collector: "MetricsCollector | None" = None
_collector_lock = threading.Lock()


def set_collector(collector: "MetricsCollector | None") -> None:
    """激活或停用全局 MetricsCollector 单例.

    由 CLI/dev_loop 在初始化时调用（standalone_driver 已删除 Phase 40）。
    传入 None 停用度量采集 (默认状态)。
    """
    with _collector_lock:
        global _collector
        _collector = collector


def get_collector() -> "MetricsCollector | None":
    with _collector_lock:
        return _collector


class MetricsCollector:
    """跨需求度量门面，委托聚合与派生摘要持久化。"""

    BASELINE_MIN_SAMPLES: int = _MetricsAggregator.BASELINE_MIN_SAMPLES
    BASELINE_FULL_STATS: int = _MetricsAggregator.BASELINE_FULL_STATS

    def __init__(
        self,
        project_root: Path,
        *,
        event_store: "SQLiteEventStore",
    ) -> None:
        self.project_root = project_root
        from auto_engineering.metrics._paths import get_metrics_dir
        self._metrics_dir = get_metrics_dir(project_root)
        self._current_thread_id: str = ""
        self._current_category: str = ""
        self._latest_summary: dict | None = None
        self._event_store = event_store
        self._driver_mode: str = "agent"  # 2026-07-26 删除 Standalone 路径: 仅余 "agent"
        self._aggregator = _MetricsAggregator()
        self._persistence = _MetricsPersistence()

    def set_driver_mode(self, mode: str) -> None:
        """Set the driver mode for metrics labeling (T115 5.4).

        Args:
            mode: "agent"（Standalone 已于 Phase 40 移除，仅余 agent 驱动）。

        Raises:
            ValueError: if mode is not "agent".
        """
        if mode != "agent":
            raise ValueError(
                f"Invalid driver_mode '{mode}'. Standalone 已于 Phase 40 移除，仅支持 'agent'。")
        self._driver_mode = mode

    # ── 需求级生命周期 ──

    def begin_requirement(self, thread_id: str, requirement_hash: str,
                          requirement_category: str = "") -> None:
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        self._current_thread_id = thread_id
        self._current_category = requirement_category
        self._latest_summary = None

    def resume_from_event_store(self, thread_id: str) -> list[dict]:
        """Load a temporary metric view by replaying the current EventStore stream."""
        if self._event_store is None:
            raise AssertionError("MetricsCollector 必须绑定 EventStore")
        self._current_thread_id = thread_id
        self._latest_summary = None
        return project_metrics_events(self._event_store.load_stream(thread_id))

    def end_requirement(self, verdict: str, total_ticks: int,
                        loc_added: int = 0) -> dict:
        summary = self._aggregator.compute_summary(
            self._summary_events(), loc_added, self._driver_mode)

        # T111: RuleDiscoverer — 历史数据 ≥ 10 时运行 Spearman 相关扫描
        history = self._persistence.load_history(self._metrics_dir, limit=100)
        if len(history) >= 10:
            from auto_engineering.metrics.rule_discoverer import DiagnosticRuleDiscoverer
            discoverer = DiagnosticRuleDiscoverer(self._metrics_dir)
            candidate_rules = discoverer.discover(min_requirements=10)
            if candidate_rules:
                summary["suggested_rules"] = [
                    {
                        "signal_name": r.signal_name,
                        "metric": r.metric,
                        "correlation_score": r.correlation_score,
                        "confidence": r.confidence,
                    }
                    for r in candidate_rules
                ]

        self._latest_summary = summary
        self._persistence.write_summary(
            summary, self._metrics_dir, self._current_thread_id,
            self._current_category,
        )
        return summary

    def get_latest_summary(self) -> dict | None:
        """Return the most recently computed M1-M5 summary, or None."""
        return self._latest_summary

    def load_history(self, limit: int = 10) -> list[dict]:
        """Load recent summary.json files from past requirements for trend analysis.

        Scans requirements/*/summary.json in the metrics directory, sorts by
        modification time, and returns the most recent *limit* summaries.
        """
        return self._persistence.load_history(self._metrics_dir, limit)

    def load_baseline(self) -> dict | None:
        """Load the global baseline from baselines/summary.json.

        Returns aggregated baseline statistics or None if not enough data.
        """
        return self._aggregator.load_baseline(self._metrics_dir)

    def _summary_events(self) -> list[dict]:
        """Return the current thread's temporary EventStore projection."""
        if not self._current_thread_id:
            raise ValueError("METRICS_THREAD_REQUIRED")
        return project_metrics_events(
            self._event_store.load_stream(self._current_thread_id)
        )

    # ── 私有方法委托 ──

    def _compute_summary(self, loc_added: int = 0) -> dict:
        return self._aggregator.compute_summary(
            self._summary_events(), loc_added, self._driver_mode)

    def _write_summary(self, summary: dict | None = None) -> None:
        """Write M1-M5 summary.json and category metadata.json."""
        if summary is None:
            summary = self._aggregator.compute_summary(
                self._summary_events(), 0, self._driver_mode)
        self._persistence.write_summary(summary, self._metrics_dir,
                                        self._current_thread_id,
                                        self._current_category)

    # ── 基线管理 (委托给 _aggregator) ──

    def update_baseline(self) -> dict | None:
        """Recalculate global + by_category baselines from all completed requirements.

        Returns global_baseline dict, or None when sample size < BASELINE_MIN_SAMPLES.
        Also writes baselines/by_category/<category>.json for categorized baselines.
        """
        return self._aggregator.update_baseline(self._metrics_dir)

    def compare_periods(self, before_tag: str, after_tag: str) -> dict | None:
        """按配置版本 tag 分割时段，对比调整前后的聚合指标.

        返回 {"before": {...}, "after": {...}} 或 None（tag 无效时）。
        """
        return self._aggregator.compare_periods(self._metrics_dir,
                                                before_tag, after_tag)

    @staticmethod
    def _get_tag_timestamp(tag: str) -> float | None:
        """Get the commit timestamp for a git tag as Unix epoch float.

        Returns None if the tag doesn't exist or git is unavailable.
        Used by compare_periods to dynamically split before/after by tag recency.
        """
        return _MetricsAggregator._get_tag_timestamp(tag)

    @staticmethod
    def _median(values: list[float]) -> float:
        """Compute median using statistics module (delegates to _MetricsAggregator)."""
        import statistics  # noqa: F401 — kept for inspect.getsource compatibility
        return _MetricsAggregator._median(values)

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        return _MetricsAggregator._percentile(values, percentile)
