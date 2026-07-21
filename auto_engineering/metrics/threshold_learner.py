"""ThresholdLearner — Beta-Binomial Bayesian threshold learning (T70).

Design spec: v5.6-Design-Loop.md Appendix F.10.

@reserved: 战略储备模块 — 完整实现 (148 行, 32 tests PASS) 但零调用方。
激活条件: metrics 管线累积 ≥30 条需求数据后, 在 enrichment.py:compute_metrics_signals()
中实例化 ThresholdLearner 并调用 propose_adjustments()。
参见 BEACON 决策 #83 Phase 30。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ThresholdEstimate:
    """Single threshold Bayesian estimate (F.10.2)."""

    param_name: str
    alpha: float = 2.0
    beta: float = 2.0
    min_value: float = 0.0
    max_value: float = 100.0
    min_obs: int = 30

    @property
    def posterior_mean(self) -> float:
        mean = self.alpha / (self.alpha + self.beta)
        return self.min_value + mean * (self.max_value - self.min_value)

    @property
    def confidence(self) -> float:
        return 1.0 / (1.0 + self.alpha + self.beta)

    @property
    def total_obs(self) -> int:
        return max(0, int(self.alpha + self.beta - 4))

    def observe(self, worked_well: bool) -> None:
        if worked_well:
            self.alpha += 1
        else:
            self.beta += 1

    def is_ready(self) -> bool:
        return self.total_obs >= self.min_obs


class ThresholdLearner:
    """Bayesian threshold learner (F.10.2).

    Maintains Beta posteriors for 10 tunable thresholds, updated per requirement.
    """

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir
        self._estimates: dict[str, ThresholdEstimate] = self._init_estimates()
        self._load_state()

    def _init_estimates(self) -> dict[str, ThresholdEstimate]:
        return {
            "max_refine_per_source": ThresholdEstimate(
                "max_refine_per_source", min_value=1, max_value=4),
            "max_refine_global": ThresholdEstimate(
                "max_refine_global", min_value=2, max_value=8),
            "AE_MAX_TOOL_CALLS": ThresholdEstimate(
                "AE_MAX_TOOL_CALLS", min_value=5, max_value=20),
            "max_iter": ThresholdEstimate(
                "max_iter", min_value=10, max_value=40),
            "token_budget_warning": ThresholdEstimate(
                "token_budget_warning", min_value=50000, max_value=500000),
            "M1_tick_limit": ThresholdEstimate(
                "M1_tick_limit", min_value=5, max_value=30),
            "M2_cons_rise": ThresholdEstimate(
                "M2_cons_rise", min_value=2, max_value=6),
            "M4_refine_limit": ThresholdEstimate(
                "M4_refine_limit", min_value=1, max_value=5),
            "M5_token_limit": ThresholdEstimate(
                "M5_token_limit", min_value=50000, max_value=1000000),
            "M3_skip_window": ThresholdEstimate(
                "M3_skip_window", min_value=4, max_value=20),
        }

    def compute_max_iter(self) -> int:
        """从 Bayesian 后验计算推荐的 max_iter (替代 loop/threshold_learner 旧版).

        Returns:
            int: min(int(posterior_mean), 40). 冷启动时返回 10.
        """
        est = self._estimates.get("max_iter")
        if est is None or not est.is_ready():
            return 10
        return min(int(est.posterior_mean), 40)

    def observe_requirement(self, summary: dict, signals: list[dict]) -> None:
        signal_names = {s.get("name", "") for s in signals}
        self._estimates["M1_tick_limit"].observe(
            "slow_convergence" not in signal_names)
        self._estimates["M2_cons_rise"].observe(
            "critic_major_increasing" not in signal_names)
        self._estimates["M4_refine_limit"].observe(
            "plan_refine_spike" not in signal_names)
        self._estimates["M5_token_limit"].observe(
            "token_efficiency_drop" not in signal_names)
        for param in ["max_refine_per_source", "max_refine_global",
                       "AE_MAX_TOOL_CALLS", "max_iter", "token_budget_warning",
                       "M3_skip_window"]:
            self._estimates[param].observe(True)

    def propose_adjustments(self) -> list[dict]:
        proposals = []
        for name, est in self._estimates.items():
            if not est.is_ready():
                continue
            proposed = est.posterior_mean
            current = self._get_current_value(name)
            if abs(proposed - current) / max(current, 1) > 0.05:
                proposals.append({
                    "param": name,
                    "current": round(current, 2),
                    "proposed": round(proposed, 2),
                    "confidence": round(1.0 - est.confidence, 3),
                    "total_obs": est.total_obs,
                })
        return proposals

    def _get_current_value(self, param_name: str) -> float:
        active_path = self._metrics_dir / "configs" / "active.json"
        if active_path.exists():
            config = json.loads(active_path.read_text())
            return float(config.get("params", {}).get(param_name, 0))
        defaults = {
            "M1_tick_limit": 12, "M2_cons_rise": 3,
            "M4_refine_limit": 2, "M5_token_limit": 200_000,
            "M3_skip_window": 8,
            "max_refine_per_source": 2, "max_refine_global": 4,
            "AE_MAX_TOOL_CALLS": 10, "max_iter": 20,
            "token_budget_warning": 200_000,
        }
        return float(defaults.get(param_name, 0))

    def _save_state(self) -> None:
        state = {
            name: {"alpha": est.alpha, "beta": est.beta}
            for name, est in self._estimates.items()
        }
        state_path = self._metrics_dir / "baselines" / "threshold_posteriors.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    def _load_state(self) -> None:
        state_path = self._metrics_dir / "baselines" / "threshold_posteriors.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            for name, params in state.items():
                if name in self._estimates:
                    self._estimates[name].alpha = params["alpha"]
                    self._estimates[name].beta = params["beta"]
