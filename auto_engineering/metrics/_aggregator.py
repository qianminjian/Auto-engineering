"""_MetricsAggregator — 度量聚合计算 (T117 拆分自 collector.py).

职责: M1-M5 指标聚合 + 基线统计计算 + 基线文件读写.
不含事件记录、生命周期管理、事件/摘要文件持久化.
"""
import json
import logging
import subprocess
from pathlib import Path

from auto_engineering.utils.file_utils import safe_json_load

_logger = logging.getLogger(__name__)


def _count_by(items: list[dict], key: str) -> dict[str, int]:
    """Count items by a key, supporting nested payload access."""
    result: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        if isinstance(val, str):
            result[val] = result.get(val, 0) + 1
    return result


class _MetricsAggregator:
    """度量聚合计算 — M1-M5 指标 + 基线统计.

    无状态: 所有方法接收数据作为参数, 不持有 events/metrics_dir 引用.
    """

    BASELINE_MIN_SAMPLES: int = 10
    BASELINE_FULL_STATS: int = 30

    # Design F.2.3: known requirement complexity categories for by_category baselines.
    _KNOWN_CATEGORIES = ("simple_function", "medium_crud", "complex_multi_module", "unknown")

    def compute_summary(self, events: list[dict], loc_added: int = 0,
                        driver_mode: str = "agent") -> dict:
        """Compute M1-M5 summary from events list.

        Mirrors original _compute_summary logic byte-for-byte.
        """
        ticks = [e for e in events if e["event_type"] == "tick_complete"]
        token_events = [e for e in events if e["event_type"] == "token_usage"]
        convergence_events = [e for e in events if e["event_type"] == "convergence"]

        # M1: Loop 收敛效率 — 总 tick 数
        m1 = len(ticks)

        # M2: Critic 打回率 — MAJOR verdict 占比
        # 从 tick_complete 事件中统计 stage="critic" 的 MAJOR 占比 (T80 fix)
        # v5.6 tick 模式下单个 loop 只有最终 convergence 事件,
        # 中间 critic MAJOR 必须从 tick_complete 获取
        # 排除 verdict 为空的 tick (critic 未运行或 verdict 未设置 — 不计入分母)
        critic_ticks = [e for e in ticks
                        if e["payload"].get("stage") == "critic"
                        and e["payload"].get("verdict")]
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
        m5 = {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_tokens,
            "loc_added": loc_added,
            "efficiency_ratio": round(efficiency, 2),
        }

        # T109f: PII 事件统计
        pii_events = [e for e in events
                      if isinstance(e.get("event_type", ""), str)
                      and e["event_type"].startswith("PII_")]
        by_tick: dict[str, int] = {}
        for pe in pii_events:
            tick = pe.get("payload", {}).get("tick", 0)
            by_tick[str(tick)] = by_tick.get(str(tick), 0) + 1
        pii_stats = {
            "total_detections": len(pii_events),
            "by_type": _count_by(pii_events, "event_type"),
            "by_tick": by_tick,
        }

        return {"driver_mode": driver_mode,
                "M1_loop_efficiency": m1, "M2_critic_major_rate": m2,
                "M3_verification_trigger_rate": m3, "M4_plan_refine_count": m4,
                "M5_token_efficiency": m5, "pii_events": pii_stats}

    def load_baseline(self, metrics_dir: Path) -> dict | None:
        """Load the global baseline from baselines/summary.json.

        Returns aggregated baseline statistics or None if not enough data.
        """
        baseline_path = metrics_dir / "baselines" / "summary.json"
        if not baseline_path.exists():
            return None
        data = safe_json_load(baseline_path)
        if isinstance(data, dict):
            return data
        _logger.debug("metrics baseline read failed: %s", baseline_path)
        return None

    def update_baseline(self, metrics_dir: Path) -> dict | None:
        """Recalculate global + by_category baselines from all completed requirements.

        Returns global_baseline dict, or None when sample size < BASELINE_MIN_SAMPLES.
        Also writes baselines/by_category/<category>.json for categorized baselines.
        """
        reqs_dir = metrics_dir / "requirements"
        if not reqs_dir.exists():
            return None

        all_summaries: list[dict] = []
        categorized: dict[str, list[dict]] = {c: [] for c in self._KNOWN_CATEGORIES}

        for req_path in reqs_dir.iterdir():
            summary_file = req_path / "summary.json"
            if not summary_file.exists():
                continue
            summary_data = safe_json_load(summary_file)
            if not isinstance(summary_data, dict):
                _logger.debug("metrics summary file read failed: %s", summary_file)
                continue
            all_summaries.append(summary_data)
            # Read category from metadata.json
            meta_file = req_path / "metadata.json"
            if meta_file.exists():
                meta_data = safe_json_load(meta_file)
                if isinstance(meta_data, dict):
                    cat = meta_data.get("category", "")
                    if cat in self._KNOWN_CATEGORIES:
                        categorized[cat].append(summary_data)

        if len(all_summaries) < self.BASELINE_MIN_SAMPLES:
            return None

        baseline = self._build_baseline(all_summaries)

        # Write global baseline
        baselines_dir = metrics_dir / "baselines"
        baselines_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baselines_dir / "global_baseline.json"
        baseline_path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))

        # Write categorized baselines
        by_cat_dir = baselines_dir / "by_category"
        by_cat_dir.mkdir(parents=True, exist_ok=True)
        for cat, summaries in categorized.items():
            if summaries:
                cat_baseline = self._build_baseline(summaries)
                cat_path = by_cat_dir / f"{cat}.json"
                cat_path.write_text(json.dumps(cat_baseline, indent=2, ensure_ascii=False))

        return baseline

    def compare_periods(self, metrics_dir: Path, before_tag: str,
                        after_tag: str) -> dict | None:
        """按配置版本 tag 分割时段，对比调整前后的聚合指标.

        返回 {"before": {...}, "after": {...}} 或 None（tag 无效时）。
        """
        baselines_dir = metrics_dir / "baselines"
        before_path = baselines_dir / f"{before_tag}.json"
        after_path = baselines_dir / f"{after_tag}.json"
        if not before_path.exists() or not after_path.exists():
            return None
        before_data = safe_json_load(before_path)
        after_data = safe_json_load(after_path)
        # safe_json_load returns dict | list | None; non-dict = invalid data
        if not isinstance(before_data, dict) or not isinstance(after_data, dict):
            return None
        return {"before": before_data, "after": after_data}

    def _build_baseline(self, summaries: list[dict]) -> dict:
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
        """Compute median using statistics module."""
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
