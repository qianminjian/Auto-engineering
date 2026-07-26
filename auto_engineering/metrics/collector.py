"""MetricsCollector — 跨需求度量聚合器 (T65, T117 拆分).

借鉴 LangGraph runtime.py Runtime 的 scoped context 模式：
Runtime 为每个 run 提供独立上下文（run_id, attempt 计数器），
MetricsCollector 为每个需求提供独立采集作用域（thread_id → 事件流）。

T117: 拆分为门面 + _MetricsAggregator + _MetricsPersistence.
      MetricsCollector 保留事件记录 + 生命周期, 委托聚合/持久化给 delegate.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from auto_engineering.metrics._aggregator import _count_by, _MetricsAggregator
from auto_engineering.metrics._persistence import _MetricsPersistence

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


# Module-level collector singleton — set by CLI/loop entry point, read by agents/base.py.
# Pattern: AE_METRICS=1 env var activates → set_collector(MetricsCollector(project_root)).
# When AE_METRICS is unset, _collector stays None → all hook points are no-ops.
#
# Lifecycle:
#   1. CLI entry (dev_loop.py) calls set_collector(...) at init
#   2. Agent code (agents/base.py) calls get_collector() → None-safe no-op if disabled
#   3. Process exit → singleton dies with process (no explicit teardown needed)
#
# Thread safety: _collector_lock protects set/get. Each tick is a fresh process
# (Tick-Based Discrete Invocation), so no cross-tick state leakage.
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
    """跨需求度量聚合器.

    每个需求的生命周期：begin_requirement → 事件采集 → end_requirement → summary.

    T117: 门面模式 — 持有 _MetricsAggregator + _MetricsPersistence 两个 delegate (组合非继承).
    事件记录 (record_*) 和需求生命周期留在本类.
    聚合计算委托给 _aggregator, 文件持久化委托给 _persistence.
    """

    BASELINE_MIN_SAMPLES: int = _MetricsAggregator.BASELINE_MIN_SAMPLES
    BASELINE_FULL_STATS: int = _MetricsAggregator.BASELINE_FULL_STATS

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        from auto_engineering.metrics._paths import get_metrics_dir
        self._metrics_dir = get_metrics_dir(project_root)
        self._current_thread_id: str = ""
        self._current_category: str = ""
        self._events: list[dict] = []
        self._latest_summary: dict | None = None
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
        if self._events and self._current_thread_id:
            self._persistence.flush_events(self._events, self._metrics_dir,
                                           self._current_thread_id)
        self._current_thread_id = thread_id
        self._current_category = requirement_category
        self._events = []
        self._latest_summary = None
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "requirement_start",
            "thread_id": thread_id,
            "requirement_hash": requirement_hash,
        })

    def resume_events(self, thread_id: str) -> list[dict]:
        """Load existing events from disk for cross-process tick continuation.

        Reads events.jsonl for the given thread_id and populates in-memory
        event buffer. Does NOT add a new requirement_start event.
        Restores _current_category from metadata.json (T85).
        Returns the loaded events list (empty if no prior events).
        """
        self._current_thread_id = thread_id
        self._events = []
        self._latest_summary = None
        # T85: Restore category from metadata.json for cross-process continuity
        self._current_category = self._persistence.read_category_from_disk(
            self._metrics_dir, thread_id)
        self._events = self._persistence.read_events_from_disk(
            self._metrics_dir, thread_id)
        return self._events

    def end_requirement(self, verdict: str, total_ticks: int,
                        loc_added: int = 0) -> dict:
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "requirement_end",
            "thread_id": self._current_thread_id,
            "verdict": verdict,
            "total_ticks": total_ticks,
        })
        summary = self._aggregator.compute_summary(
            self._events, loc_added, self._driver_mode)

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
        self._persistence.flush(self._events, summary, self._metrics_dir,
                                self._current_thread_id, self._current_category)
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

    # ── 事件采集 ──

    def record_tick_complete(self, tick_number: int, stage: str,
                             duration_ms: int,
                             ai_origin: AIOrigin,
                             gate_results: dict | None = None,
                             guardrail_results: dict | None = None,
                             verdict: str = "") -> None:
        payload: dict = {
            "tick_number": tick_number,
            "stage": stage,
            "duration_ms": duration_ms,
            "gate_results": gate_results or {},
            "guardrail_results": guardrail_results or {},
        }
        if verdict:
            payload["verdict"] = verdict
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "tick_complete",
            "thread_id": self._current_thread_id,
            "ai_origin": ai_origin.to_dict(),
            "payload": payload,
        })

    def record_token_usage(self, input_tokens: int, output_tokens: int,
                           model: str, provider: str, stage: str,
                           ai_origin: AIOrigin) -> None:
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "token_usage",
            "thread_id": self._current_thread_id,
            "ai_origin": ai_origin.to_dict(),
            "payload": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "model": model,
                "provider": provider,
                "stage": stage,
            },
        })

    def record_stage_transition(self, from_stage: str, to_stage: str,
                                reason: str,
                                ai_origin: AIOrigin) -> None:
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "stage_transition",
            "thread_id": self._current_thread_id,
            "ai_origin": ai_origin.to_dict(),
            "payload": {
                "from_stage": from_stage,
                "to_stage": to_stage,
                "transition_reason": reason,
            },
        })

    def record_convergence(self, verdict: str, total_ticks: int,
                           criteria_met: str = "",
                           ai_origin: AIOrigin | None = None) -> None:
        event: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "convergence",
            "thread_id": self._current_thread_id,
            "payload": {
                "verdict": verdict,
                "total_ticks": total_ticks,
                "criteria_met": criteria_met,
            },
        }
        if ai_origin is not None:
            event["ai_origin"] = ai_origin.to_dict()
        self._events.append(event)

    def record_gate_result(self, gate_name: str, passed: bool,
                           duration_ms: int, findings_count: int,
                           ai_origin: AIOrigin | None = None) -> None:
        event: dict = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": "gate_result",
            "thread_id": self._current_thread_id,
            "payload": {
                "gate_name": gate_name,
                "passed": passed,
                "duration_ms": duration_ms,
                "findings_count": findings_count,
            },
        }
        if ai_origin is not None:
            event["ai_origin"] = ai_origin.to_dict()
        self._events.append(event)

    # T109f: PII 事件
    def record_pii_event(self, event_type: str, findings: list[dict],
                         tick: int = 0) -> None:
        """Record a PII detection event (T109f).

        Args:
            event_type: One of PII_DETECTED_REQUIREMENT, PII_DETECTED_RESULT,
                        PII_REDACTED, PII_DETECTED_FILE.
            findings: List of PII findings from scan_dict/scan_text.
            tick: Current tick number for by_tick aggregation.
        """
        self._events.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event_type": event_type,
            "thread_id": self._current_thread_id,
            "payload": {
                "tick": tick,
                "count": len(findings),
                "by_severity": _count_by(findings, "severity"),
                "by_category": _count_by(findings, "category"),
                "by_rule": _count_by(findings, "rule"),
            },
        })

    def record_tick_snapshot(self, tick_number: int, stage_in: str,
                              action: dict, state_snapshot: dict,
                              guardrail_results: dict, gate_results: dict,
                              timing_ms: dict) -> None:
        """Write per-tick snapshot to requirements/<thread_id>/ticks/tick-{N:04d}.json.

        Bridges DebugTracer's per-tick snapshots into the metrics storage directory.
        Design: F.2.3 storage structure — ticks/ directory alongside events.jsonl.
        """
        ticks_dir = self._metrics_dir / "requirements" / self._current_thread_id / "ticks"
        ticks_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "tick": tick_number,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage_in": stage_in,
            "action": action,
            "state_snapshot": state_snapshot,
            "guardrail_results": guardrail_results,
            "gate_results": gate_results,
            "timing_ms": timing_ms,
        }
        tick_file = ticks_dir / f"tick-{tick_number:04d}.json"
        tick_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))

    # ── 私有方法委托 (保持外部测试/CLI 兼容性) ──

    def _compute_summary(self, loc_added: int = 0) -> dict:
        return self._aggregator.compute_summary(
            self._events, loc_added, self._driver_mode)

    def _flush_events(self) -> None:
        """Write events buffer to events.jsonl (atomic overwrite via temp file, P2-41)."""
        self._persistence.flush_events(self._events, self._metrics_dir,
                                       self._current_thread_id)

    def _write_summary(self, summary: dict | None = None) -> None:
        """Write M1-M5 summary.json and category metadata.json."""
        if summary is None:
            summary = self._aggregator.compute_summary(
                self._events, 0, self._driver_mode)
        self._persistence.write_summary(summary, self._metrics_dir,
                                        self._current_thread_id,
                                        self._current_category)

    def _flush(self, summary: dict | None = None) -> None:
        """Flush events and write summary (convenience, calls _flush_events + _write_summary)."""
        self._flush_events()
        self._write_summary(summary)

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
