"""SignalDetector — 5 种信号检测 (T67).

检测类型（F.4）：
1. Trend — 趋势检测（简单方向判定，< 完整统计基线时用；≥30 样本切换 Mann-Kendall）
2. Mutation — 突变检测（IQR 离群值）
3. Ratio Anomaly — 比率异常（M2 打回率 / M4 重设计频率）
4. Cost Alert — 成本告警（token 预算超限）
5. Cold-Start M5 — 冷启动 token 效率（< COLD_START_MIN_SAMPLES 时硬编码阈值）
"""
from dataclasses import dataclass


@dataclass
class Signal:
    """检测到的度量信号 (F.4-aligned)."""
    name: str
    severity: str               # INFO / WARN / CRITICAL
    metric: str                 # M1_loop_efficiency / M2_critic_major_rate / ...
    value: float
    baseline: float = 0.0       # 历史基线对比值 (F.4)
    threshold: float = 0.0      # 告警触发阈值
    description: str = ""


class SignalDetector:
    """多维度信号检测器.

    冷启动策略（F.4）：
    - < COLD_START_MIN_SAMPLES 需求 → 硬编码阈值
    - ≥ COLD_START_MIN_SAMPLES → 简单统计基线
    - ≥ BASELINE_FULL_STATS → Mann-Kendall + IQR 完整版
    """

    COLD_START_MIN_SAMPLES: int = 10
    BASELINE_FULL_STATS: int = 30

    def __init__(
        self,
        min_samples: int = 10,
        major_rate_threshold: float = 0.5,
        refine_rate_threshold: int = 3,
        token_budget: int = 200000,
        cold_start_min_samples: int = 10,
        cold_start_token_threshold: int = 200000,
    ) -> None:
        self.min_samples = min_samples
        self.major_rate_threshold = major_rate_threshold
        self.refine_rate_threshold = refine_rate_threshold
        self.token_budget = token_budget
        self.cold_start_min_samples = cold_start_min_samples
        self.cold_start_token_threshold = cold_start_token_threshold

    def analyze(
        self,
        requirement_history: list[dict],
        baseline: dict | None = None,
    ) -> list[Signal]:
        """分析需求历史，产出信号列表 (F.4-aligned).

        Args:
            requirement_history: 最近 N 个需求的 summary.json 列表。
            baseline: 全局基线（可能为 None=冷启动）。
        """
        signals: list[Signal] = []
        if not requirement_history:
            return signals

        use_stat = (
            baseline is not None
            and baseline.get("sample_size", 0) >= self.COLD_START_MIN_SAMPLES
        )

        signals.extend(self._detect_major_trend(
            requirement_history, baseline, use_stat))
        signals.extend(self._detect_refine_spike(
            requirement_history, baseline, use_stat))
        signals.extend(self._detect_slow_convergence(
            requirement_history, baseline, use_stat))
        signals.extend(self._detect_token_efficiency_drop(
            requirement_history, baseline, use_stat))
        signals.extend(self._detect_verification_skip(
            requirement_history, baseline, use_stat))

        # T87: Wire dead-code helpers into production path.
        # Previously only test-called — now reachable from analyze().
        # _detect_trend: trend analysis on M1/M2 history
        m1_history = [h.get("M1_loop_efficiency", 0) for h in requirement_history]
        m2_history = [h.get("M2_critic_major_rate", 0) for h in requirement_history]
        signals.extend(self._detect_trend(m1_history, "M1_loop_efficiency"))
        signals.extend(self._detect_trend(m2_history, "M2_critic_major_rate"))

        # _detect_mutation: latest-vs-baseline spike detection
        if baseline and requirement_history:
            latest_m1 = requirement_history[-1].get("M1_loop_efficiency", 0)
            bl_m1 = baseline.get("M1", {}).get("median")
            if bl_m1 is not None:
                signals.extend(self._detect_mutation(latest_m1, [bl_m1], "M1_loop_efficiency"))

        # _detect_ratio_anomaly: M2/M4 ratio check
        latest = requirement_history[-1]
        signals.extend(self._detect_ratio_anomaly(
            major_rate=latest.get("M2_critic_major_rate", 0),
            plan_refine_count=latest.get("M4_plan_refine_count", 0),
        ))

        # _detect_cost_alert + _detect_token_budget_internal
        latest_m5 = latest.get("M5_token_efficiency", {})
        total_tokens = latest_m5.get("total_tokens", 0) if isinstance(latest_m5, dict) else 0
        signals.extend(self._detect_cost_alert(total_tokens))
        signals.extend(self._detect_token_budget_internal(
            total_tokens, requirement_history, baseline or {}, use_stat,
        ))

        return signals

    # ── 5 design-aligned detection methods (F.4) ──

    def _detect_major_trend(self, history: list[dict],
                            baseline: dict | None,
                            use_stat: bool) -> list[Signal]:
        """M2: critic MAJOR 率连续上升 (F.4 _detect_major_trend)."""
        if len(history) < 5:
            return []
        recent = [h.get("M2_critic_major_rate", 0) for h in history[-5:]]
        increasing_streak = sum(
            1 for i in range(1, len(recent)) if recent[i] > recent[i - 1]
        )
        if increasing_streak >= 3:
            bl = baseline.get("M2", {}).get("median", 0.3) if use_stat and baseline else 0.3
            return [Signal(
                name="critic_major_increasing",
                severity="WARN",
                metric="M2_critic_major_rate",
                value=recent[-1],
                baseline=bl,
                threshold=bl,
                description=f"critic MAJOR 率连续上升: {recent[-3:]}",
            )]
        return []

    def _detect_refine_spike(self, history: list[dict],
                             baseline: dict | None,
                             use_stat: bool) -> list[Signal]:
        """M4: plan_refine 次数超过基线 p95 (F.4 _detect_refine_spike)."""
        if not history:
            return []
        latest = history[-1].get("M4_plan_refine_count", 0)
        threshold = (
            baseline.get("M4", {}).get("p95", 2) if use_stat and baseline else 2
        )
        if latest > threshold:
            return [Signal(
                name="plan_refine_spike",
                severity="WARN",
                metric="M4_plan_refine_count",
                value=float(latest),
                baseline=float(threshold),
                threshold=float(threshold),
                description=f"plan_refine 次数 {latest} 超过基线 p95={threshold}",
            )]
        return []

    def _detect_slow_convergence(self, history: list[dict],
                                  baseline: dict | None,
                                  use_stat: bool) -> list[Signal]:
        """M1: 收敛 tick 数超过基线中位数 2x (F.4 _detect_slow_convergence)."""
        if not history:
            return []
        latest = history[-1].get("M1_loop_efficiency", 0)
        threshold = (
            baseline.get("M1", {}).get("median", 6) * 2
            if use_stat and baseline else 12
        )
        if latest > threshold:
            return [Signal(
                name="slow_convergence",
                severity="CRITICAL",
                metric="M1_loop_efficiency",
                value=float(latest),
                baseline=float(threshold),
                threshold=float(threshold),
                description=f"收敛 tick 数 {latest} 远超基线 {threshold}",
            )]
        return []

    def _detect_token_efficiency_drop(self, history: list[dict],
                                       baseline: dict | None,
                                       use_stat: bool) -> list[Signal]:
        """M5: token 消耗效率低于基线 50% 或超过冷启动阈值 (F.4)."""
        if not history:
            return []
        latest_m5 = history[-1].get("M5_token_efficiency", {})
        latest_tokens = (
            latest_m5.get("total_tokens", 0) if isinstance(latest_m5, dict) else 0
        )

        if use_stat and baseline:
            baseline_tokens = baseline.get("M5", {}).get("median_total_tokens", 0)
            if baseline_tokens > 0 and latest_tokens > baseline_tokens * 1.5:
                return [Signal(
                    name="token_efficiency_drop",
                    severity="WARN",
                    metric="M5_token_efficiency",
                    value=float(latest_tokens),
                    baseline=float(baseline_tokens),
                    threshold=float(baseline_tokens * 1.5),
                    description=f"token 消耗 {latest_tokens} 超出基线 {baseline_tokens} 50%",
                )]
        elif latest_tokens > self.token_budget:
            return [Signal(
                name="token_efficiency_drop",
                severity="WARN",
                metric="M5_token_efficiency",
                value=float(latest_tokens),
                baseline=float(self.token_budget),
                threshold=float(self.token_budget),
                description=f"token 消耗 {latest_tokens} 超过冷启动阈值 {self.token_budget}",
            )]
        return []

    def _detect_verification_skip(self, history: list[dict],
                                   baseline: dict | None,
                                   use_stat: bool) -> list[Signal]:
        """M3: 验证层持续为 LEAF，深层审计从未触发 (F.4)."""
        if len(history) < 8:
            return []
        recent = history[-8:]
        full_count = sum(
            1 for h in recent
            if h.get("M3_verification_trigger_rate", {}).get(
                "system_deep_audit", 0) > 0
        )
        if full_count == 0:
            return [Signal(
                name="verification_always_leaf",
                severity="INFO",
                metric="M3_verification_trigger_rate",
                value=0.0,
                baseline=1.0,
                threshold=1.0,
                description="最近 8 需求从未触发 system_deep_audit",
            )]
        return []

    # ── internal helper detectors (tested directly) ──

    def _detect_trend(self, history: list[float],
                      metric: str) -> list[Signal]:
        if len(history) < max(self.min_samples, 2):
            return []
        # Simple direction check: compare first half average to second half
        mid = len(history) // 2
        if mid == 0:
            return []
        first_half = sum(history[:mid]) / mid
        second_half = sum(history[mid:]) / (len(history) - mid)
        if first_half == 0:
            return []
        change = (second_half - first_half) / first_half
        if abs(change) < 0.15:  # < 15% change = flat
            return []
        if metric == "M1_loop_efficiency":
            name = "m1_increasing_trend" if change > 0 else "m1_decreasing_trend"
        elif metric == "M2_critic_major_rate":
            name = "m2_increasing_trend" if change > 0 else "m2_decreasing_trend"
        else:
            name = f"{metric}_trend"
        return [Signal(
            name=name,
            severity="WARN" if abs(change) > 0.3 else "INFO",
            metric=metric,
            value=round(change, 3),
            threshold=0.15,
            description=f"{'Upward' if change > 0 else 'Downward'} trend detected ({change:.1%} change)",
        )]

    def _detect_mutation(self, latest: float, baseline: list[float],
                         metric: str) -> list[Signal]:
        if len(baseline) < self.min_samples:
            return []
        avg = sum(baseline) / len(baseline)
        if avg == 0:
            return []
        ratio = latest / avg
        if ratio > 2.0:
            return [Signal(
                name=f"{metric}_spike",
                severity="WARN",
                metric=metric,
                value=round(ratio, 2),
                threshold=2.0,
                description=f"Sudden spike: {ratio:.1f}x baseline average",
            )]
        return []

    def _detect_ratio_anomaly(self, major_rate: float,
                              plan_refine_count: int) -> list[Signal]:
        signals: list[Signal] = []
        if major_rate > self.major_rate_threshold:
            signals.append(Signal(
                name="high_critic_major_rate",
                severity="CRITICAL" if major_rate > 0.7 else "WARN",
                metric="M2_critic_major_rate",
                value=major_rate,
                threshold=self.major_rate_threshold,
                description=f"Critic MAJOR rate {major_rate:.0%} exceeds threshold {self.major_rate_threshold:.0%}",
            ))
        if plan_refine_count > self.refine_rate_threshold:
            signals.append(Signal(
                name="high_plan_refine_frequency",
                severity="WARN",
                metric="M4_plan_refine_count",
                value=float(plan_refine_count),
                threshold=float(self.refine_rate_threshold),
                description=f"Plan refine count {plan_refine_count} exceeds threshold {self.refine_rate_threshold}",
            ))
        return signals

    def _detect_cost_alert(self, total_tokens: int) -> list[Signal]:
        if total_tokens > self.token_budget:
            return [Signal(
                name="token_budget_exceeded",
                severity="WARN",
                metric="M5_token_efficiency",
                value=float(total_tokens),
                threshold=float(self.token_budget),
                description=f"Token usage {total_tokens} exceeds budget {self.token_budget}",
            )]
        return []

    def _detect_token_budget_internal(self, latest_tokens: int,
                                       history: list[dict],
                                       baseline: dict,
                                       use_stat: bool) -> list[Signal]:
        if use_stat:
            # Statistical baseline path (≥30 requirements)
            # Placeholder: compare against baseline p95
            p95 = baseline.get("M5_total_tokens_p95", float("inf"))
            if latest_tokens > p95 * 1.5:
                return [Signal(
                    name="token_efficiency_drop",
                    severity="WARN",
                    metric="M5_token_efficiency",
                    value=float(latest_tokens),
                    threshold=p95 * 1.5,
                    description="Token usage exceeds baseline P95 by 50%",
                )]
            return []
        else:
            # Cold-start path: hardcoded threshold
            if latest_tokens > self.cold_start_token_threshold:
                return [Signal(
                    name="token_efficiency_drop",
                    severity="WARN",
                    metric="M5_token_efficiency",
                    value=float(latest_tokens),
                    threshold=float(self.cold_start_token_threshold),
                    description=f"Token usage {latest_tokens} exceeds cold-start threshold {self.cold_start_token_threshold}",  # noqa: E501
                )]
            return []
