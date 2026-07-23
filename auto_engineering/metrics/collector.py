"""MetricsCollector — 跨需求度量聚合器 (T65).

借鉴 LangGraph runtime.py Runtime 的 scoped context 模式：
Runtime 为每个 run 提供独立上下文（run_id, attempt 计数器），
MetricsCollector 为每个需求提供独立采集作用域（thread_id → 事件流）。
"""
import json
import logging
import subprocess
import threading
import time
from auto_engineering.utils.file_utils import safe_json_load
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
#   1. CLI entry (dev_loop.py / standalone_driver.py) calls set_collector(...) at init
#   2. Agent code (agents/base.py) calls get_collector() → None-safe no-op if disabled
#   3. Process exit → singleton dies with process (no explicit teardown needed)
#
# Thread safety: _collector_lock protects set/get. Each tick is a fresh process
# (Tick-Based Discrete Invocation), so no cross-tick state leakage.
_collector: "MetricsCollector | None" = None
_collector_lock = threading.Lock()


def set_collector(collector: "MetricsCollector | None") -> None:
    """激活或停用全局 MetricsCollector 单例.

    由 CLI/dev_loop/standalone_driver 在初始化时调用。
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
    """

    BASELINE_MIN_SAMPLES: int = 10
    BASELINE_FULL_STATS: int = 30

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        from auto_engineering.metrics._paths import get_metrics_dir
        self._metrics_dir = get_metrics_dir(project_root)
        self._current_thread_id: str = ""
        self._current_category: str = ""
        self._events: list[dict] = []
        self._latest_summary: dict | None = None
        self._driver_mode: str = "agent"  # T115: "agent" | "standalone"

    def set_driver_mode(self, mode: str) -> None:
        """Set the driver mode for metrics labeling (T115 5.4).

        Args:
            mode: "agent" or "standalone".

        Raises:
            ValueError: if mode is not one of the valid values.
        """
        if mode not in ("agent", "standalone"):
            raise ValueError(
                f"Invalid driver_mode '{mode}'. Must be 'agent' or 'standalone'.")
        self._driver_mode = mode

    # ── 需求级生命周期 ──

    def begin_requirement(self, thread_id: str, requirement_hash: str,
                          requirement_category: str = "") -> None:
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        if self._events and self._current_thread_id:
            self._flush_events()
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
        meta_path = self._metrics_dir / "requirements" / thread_id / "metadata.json"
        if meta_path.exists():
            try:
                meta = safe_json_load(meta_path)
                self._current_category = meta.get("category", "")
            except (json.JSONDecodeError, OSError):
                _logger.debug("metrics metadata read failed: %s", meta_path, exc_info=True)
                self._current_category = ""
        else:
            self._current_category = ""
        events_path = self._metrics_dir / "requirements" / thread_id / "events.jsonl"
        if events_path.exists():
            try:
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        self._events.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                _logger.debug("metrics events read failed: %s", events_path, exc_info=True)
                self._events = []
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
        summary = self._compute_summary(loc_added)

        # T111: RuleDiscoverer — 历史数据 ≥ 10 时运行 Spearman 相关扫描
        history = self.load_history(limit=100)
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
        self._flush_events()
        self._write_summary(summary)
        return summary

    def get_latest_summary(self) -> dict | None:
        """Return the most recently computed M1-M5 summary, or None."""
        return self._latest_summary

    def load_history(self, limit: int = 10) -> list[dict]:
        """Load recent summary.json files from past requirements for trend analysis.

        Scans requirements/*/summary.json in the metrics directory, sorts by
        modification time, and returns the most recent *limit* summaries.
        """
        req_dir = self._metrics_dir / "requirements"
        if not req_dir.exists():
            return []
        summaries = []
        for summary_path in sorted(
            req_dir.glob("*/summary.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                data = safe_json_load(summary_path)
                summaries.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.debug("metrics summary read failed: %s", summary_path, exc_info=True)
                pass
        return summaries

    def load_baseline(self) -> dict | None:
        """Load the global baseline from baselines/summary.json.

        Returns aggregated baseline statistics or None if not enough data.
        """
        baseline_path = self._metrics_dir / "baselines" / "summary.json"
        if not baseline_path.exists():
            return None
        try:
            return safe_json_load(baseline_path)
        except (json.JSONDecodeError, OSError):
            _logger.debug("metrics baseline read failed: %s", baseline_path, exc_info=True)
            return None

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

    # ── 聚合计算 ──

    def _compute_summary(self, loc_added: int = 0) -> dict:
        ticks = [e for e in self._events if e["event_type"] == "tick_complete"]
        token_events = [e for e in self._events if e["event_type"] == "token_usage"]
        convergence_events = [e for e in self._events if e["event_type"] == "convergence"]

        # M1: Loop 收敛效率 — 总 tick 数
        m1 = len(ticks)

        # M2: Critic 打回率 — MAJOR verdict 占比
        # 从 tick_complete 事件中统计 stage="critic" 的 MAJOR 占比 (T80 fix)
        # v5.6 tick 模式下单个 loop 只有最终 convergence 事件,
        # 中间 critic MAJOR 必须从 tick_complete 获取
        critic_ticks = [e for e in ticks if e["payload"].get("stage") == "critic"]
        major_count = sum(1 for e in critic_ticks
                         if e["payload"].get("verdict") == "MAJOR")
        m2 = major_count / max(len(critic_ticks), 1)

        # M3: 验证层级触发率
        verifier_stages = ["component_verifier", "plate_deep_audit",
                          "system_verifier", "system_deep_audit"]
        m3 = {
            stage: sum(1 for t in ticks if t["payload"].get("stage") == stage)
            for stage in verifier_stages
        }

        # M4: Plan Refine 频率
        m4 = sum(1 for e in convergence_events
                if e["payload"].get("criteria_met") == "plan_refine")

        # M5: Token 消耗效率
        total_input = sum(e["payload"].get("input_tokens", 0) for e in token_events)
        total_output = sum(e["payload"].get("output_tokens", 0) for e in token_events)
        total_tokens = total_input + total_output
        efficiency = (loc_added / (total_tokens / 1000)) if loc_added > 0 and total_tokens > 0 else 0.0
        from auto_engineering.config.runtime_config import get_default_config
        token_source = get_default_config().token_source
        m5 = {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "loc_added": loc_added,
            "efficiency_ratio": round(efficiency, 2),
            "token_source": token_source,  # T110c: provider (Standalone) or transcript (Agent JSONL)
        }

        # T109f: PII 事件统计
        pii_events = [e for e in self._events
                      if isinstance(e.get("event_type", ""), str)
                      and e["event_type"].startswith("PII_")]
        pii_stats = {
            "total_detections": len(pii_events),
            "by_type": _count_by(pii_events, "event_type"),
            "by_tick": {},
        }
        for pe in pii_events:
            tick = pe.get("payload", {}).get("tick", 0)
            pii_stats["by_tick"][str(tick)] = pii_stats["by_tick"].get(str(tick), 0) + 1

        return {"driver_mode": self._driver_mode,
                "M1_loop_efficiency": m1, "M2_critic_major_rate": m2,
                "M3_verification_trigger_rate": m3, "M4_plan_refine_count": m4,
                "M5_token_efficiency": m5, "pii_events": pii_stats}

    def _flush_events(self) -> None:
        """Write events buffer to events.jsonl (atomic overwrite via temp file, P2-41)."""
        req_dir = self._metrics_dir / "requirements" / self._current_thread_id
        req_dir.mkdir(parents=True, exist_ok=True)
        events_path = req_dir / "events.jsonl"
        tmp_path = events_path.with_suffix(".jsonl.tmp")
        with open(tmp_path, "w") as f:
            for event in self._events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        import os
        os.replace(tmp_path, events_path)  # atomic on POSIX

    def _write_summary(self, summary: dict | None = None) -> None:
        """Write M1-M5 summary.json and category metadata.json."""
        req_dir = self._metrics_dir / "requirements" / self._current_thread_id
        req_dir.mkdir(parents=True, exist_ok=True)
        if summary is None:
            summary = self._compute_summary()
        summary_path = req_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        if self._current_category:
            meta_path = req_dir / "metadata.json"
            meta_path.write_text(json.dumps(
                {"category": self._current_category}, indent=2, ensure_ascii=False))

    def _flush(self, summary: dict | None = None) -> None:
        """Flush events and write summary (convenience, calls _flush_events + _write_summary)."""
        self._flush_events()
        self._write_summary(summary)

    # ── 基线管理 ──

    # Design F.2.3: known requirement complexity categories for by_category baselines.
    _KNOWN_CATEGORIES = ("simple_function", "medium_crud", "complex_multi_module", "unknown")

    def update_baseline(self) -> dict | None:
        """Recalculate global + by_category baselines from all completed requirements.

        Returns global_baseline dict, or None when sample size < BASELINE_MIN_SAMPLES.
        Also writes baselines/by_category/<category>.json for categorized baselines.
        """
        reqs_dir = self._metrics_dir / "requirements"
        if not reqs_dir.exists():
            return None

        all_summaries: list[dict] = []
        categorized: dict[str, list[dict]] = {c: [] for c in self._KNOWN_CATEGORIES}

        for req_path in reqs_dir.iterdir():
            summary_file = req_path / "summary.json"
            if not summary_file.exists():
                continue
            try:
                summary = safe_json_load(summary_file)
            except (json.JSONDecodeError, OSError):
                _logger.debug("metrics summary file read failed: %s", summary_file, exc_info=True)
                continue
            all_summaries.append(summary)
            # Read category from metadata.json
            meta_file = req_path / "metadata.json"
            if meta_file.exists():
                try:
                    meta = safe_json_load(meta_file)
                    cat = meta.get("category", "")
                    if cat in self._KNOWN_CATEGORIES:
                        categorized[cat].append(summary)
                except (json.JSONDecodeError, OSError):
                    continue

        if len(all_summaries) < self.BASELINE_MIN_SAMPLES:
            return None

        def _build_baseline(summaries: list[dict]) -> dict:
            m1_values = [s.get("M1_loop_efficiency", 0) for s in summaries]
            m2_values = [s.get("M2_critic_major_rate", 0) for s in summaries]
            return {
                "sample_size": len(summaries),
                "full_stats_ready": len(summaries) >= self.BASELINE_FULL_STATS,
                "M1": {
                    "median": self._median(m1_values),
                    "p95": self._percentile(m1_values, 95),
                },
                "M2": {
                    "median": self._median(m2_values),
                    "p95": self._percentile(m2_values, 95),
                },
            }

        baseline = _build_baseline(all_summaries)

        # Write global baseline
        baselines_dir = self._metrics_dir / "baselines"
        baselines_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baselines_dir / "global_baseline.json"
        baseline_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))

        # Write categorized baselines
        by_cat_dir = baselines_dir / "by_category"
        by_cat_dir.mkdir(parents=True, exist_ok=True)
        for cat, summaries in categorized.items():
            if summaries:
                cat_baseline = _build_baseline(summaries)
                cat_path = by_cat_dir / f"{cat}.json"
                cat_path.write_text(json.dumps(cat_baseline, indent=2, ensure_ascii=False))

        return baseline

    def compare_periods(self, before_tag: str, after_tag: str) -> dict | None:
        """按配置版本 tag 分割时段，对比调整前后的聚合指标.

        返回 {"before": {...}, "after": {...}} 或 None（tag 无效时）。
        """
        baselines_dir = self._metrics_dir / "baselines"
        before_path = baselines_dir / f"{before_tag}.json"
        after_path = baselines_dir / f"{after_tag}.json"
        if not before_path.exists() or not after_path.exists():
            return None
        before_data = safe_json_load(before_path)
        after_data = safe_json_load(after_path)
        return {"before": before_data, "after": after_data}

    @staticmethod
    def _get_tag_timestamp(tag: str) -> float | None:
        """Get the commit timestamp for a git tag as Unix epoch float.

        Returns None if the tag doesn't exist or git is unavailable.
        Used by compare_periods to dynamically split before/after by tag recency.
        """
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", tag],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
            return None
        except (subprocess.TimeoutExpired, ValueError, OSError):
            _logger.debug("git tag timestamp failed", exc_info=True)
            return None

    @staticmethod
    def _median(values: list[float]) -> float:
        import statistics
        if not values:
            return 0.0
        return statistics.median(values)

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (percentile / 100.0) * (len(sorted_vals) - 1)
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_vals):
            return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
        return sorted_vals[f]

def _count_by(items: list[dict], key: str) -> dict[str, int]:
    """Count items by a key, supporting nested payload access."""
    result: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        if isinstance(val, str):
            result[val] = result.get(val, 0) + 1
    return result
