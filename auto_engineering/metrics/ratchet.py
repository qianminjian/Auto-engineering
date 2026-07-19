"""RatchetController — 棘轮 keep/revert/stop 三元判定 + 配置版本化 (T68).

设计规范: v5.6-Design-Loop.md 附录 F.6.
"""
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RatchetMetricDelta:
    """单个指标的 before/after 对比."""
    name: str
    before: float
    after: float
    delta: float
    direction: str  # "improved" / "regressed" / "stable"


@dataclass
class RatchetDecision:
    """棘轮三元判定 (F.6-aligned)."""
    action: str                  # keep / revert / stop
    reason: str
    config_version: str = ""     # 当前配置版本 tag
    previous_version: str = ""   # 回滚目标版本 tag
    metrics: list[dict] = field(default_factory=list)


class RatchetController:
    """配置棘轮控制器.

    核心逻辑:
    - keep: 所有指标持平或改善 → 保留新配置
    - revert: 有显著退化（>50% 恶化） → 回滚到上一版本
    - stop: 极端退化（>200% 恶化）或安全红线 → 停止并告警

    Git tag 配置版本化:
    - 配置快照写入 .ae-state/metrics/configs/ae-config-v{N}.json
    - 尝试 git tag ae-config-v{N}（失败降至 JSON 备选，返回 None）
    """

    REGRESSION_THRESHOLD: float = 0.5   # >50% 恶化 → revert
    CRITICAL_THRESHOLD: float = 2.0     # >200% 恶化 → stop
    IMPROVEMENT_THRESHOLD: float = 0.05  # <5% 变化 → stable (noise)

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        from auto_engineering.metrics._paths import get_metrics_dir
        self._metrics_dir = get_metrics_dir(project_root)
        self._configs_dir = self._metrics_dir / "configs"
        self._configs_dir.mkdir(parents=True, exist_ok=True)

    # ── 核心判定 ──

    def evaluate(self, before: dict, after: dict,
                 before_metrics: dict | None = None,
                 after_metrics: dict | None = None,
                 min_improvement: float = 0.05) -> RatchetDecision:
        """对比 before/after 配置，返回 keep/revert/stop 判定 (F.6-aligned).

        与设计 F.6 对齐: before_params/after_params 合并为 before/after
        (含 M1-M5 度量值)。before_metrics/after_metrics 为可选聚合基线，
        支持 _relative_change 计算。
        """
        # 优先用 before/after 的 M1/M2 直接值做判定
        deltas: list[RatchetMetricDelta] = []
        regression_count = 0
        severe_count = 0

        metrics_keys = set(before) | set(after)
        if before_metrics:
            metrics_keys |= set(before_metrics)
        if after_metrics:
            metrics_keys |= set(after_metrics)

        for key in metrics_keys:
            b_val = self._extract_numeric(before.get(key, before_metrics.get(key) if before_metrics else None))
            a_val = self._extract_numeric(after.get(key, after_metrics.get(key) if after_metrics else None))
            if b_val is None or a_val is None:
                continue
            if b_val == 0 and a_val == 0:
                continue
            if b_val == 0:
                delta_pct = 1.0 if a_val > 0 else -1.0
            else:
                delta_pct = (a_val - b_val) / b_val

            # For metrics where lower is better (M1, M2, M4), flip sign
            direction = "stable"
            effective_delta = delta_pct
            if key in ("M1_loop_efficiency", "M2_critic_major_rate",
                       "M4_plan_refine_count"):
                effective_delta = -delta_pct

            if effective_delta > min_improvement:
                direction = "improved"
            elif effective_delta < -min_improvement:
                direction = "regressed"
                regression_count += 1
                if abs(effective_delta) > self.CRITICAL_THRESHOLD:
                    severe_count += 1

            deltas.append(RatchetMetricDelta(
                name=key,
                before=b_val,
                after=a_val,
                delta=round(delta_pct, 4),
                direction=direction,
            ))

        current_ver = f"ae-config-v{self._detect_current_version()}"
        prev_ver = f"ae-config-v{self._detect_current_version() - 1}" if self._detect_current_version() > 1 else ""

        # Decision logic
        if severe_count > 0:
            return RatchetDecision(
                action="stop",
                reason=f"{severe_count} metric(s) have severe regression (>200%)",
                config_version=current_ver,
                metrics=[{
                    "name": d.name, "before": d.before, "after": d.after,
                    "delta": d.delta, "direction": d.direction,
                } for d in deltas],
            )
        elif regression_count > 0:
            return RatchetDecision(
                action="revert",
                reason=f"{regression_count} metric(s) regressed significantly (>{min_improvement:.0%})",
                config_version=current_ver,
                previous_version=prev_ver,
                metrics=[{
                    "name": d.name, "before": d.before, "after": d.after,
                    "delta": d.delta, "direction": d.direction,
                } for d in deltas],
            )
        else:
            return RatchetDecision(
                action="keep",
                reason="All metrics stable or improved",
                config_version=current_ver,
                metrics=[{
                    "name": d.name, "before": d.before, "after": d.after,
                    "delta": d.delta, "direction": d.direction,
                } for d in deltas],
            )

    # ── 配置版本化 ──

    def save_config_snapshot(self, config: dict) -> str | None:
        """保存配置快照，返回版本标签.

        写入 .ae-state/metrics/configs/ae-config-v{N}.json.
        尝试 git tag ae-config-v{N}。失败时返回 JSON 文件路径作为降级。
        """
        existing = sorted(self._configs_dir.glob("ae-config-v*.json"))
        next_version = len(existing) + 1
        tag = f"ae-config-v{next_version}"

        config_path = self._configs_dir / f"{tag}.json"
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))

        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "tag", tag],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.warning("git tag failed for %s: %s", tag, result.stderr.strip())
                return str(config_path)
        except Exception as exc:
            logger.warning("git tag failed for %s: %s", tag, exc)
            return str(config_path)

        return tag

    def rollback(self) -> dict | None:
        """回滚到上一个配置版本."""
        existing = sorted(self._configs_dir.glob("ae-config-v*.json"))
        if len(existing) < 2:
            return None
        previous = existing[-2]
        return json.loads(previous.read_text())

    def get_current_config(self) -> dict | None:
        """读取当前最新配置."""
        existing = sorted(self._configs_dir.glob("ae-config-v*.json"))
        if not existing:
            return None
        return json.loads(existing[-1].read_text())

    # ── 版本管理 (F.6) ──

    def _detect_current_version(self) -> int:
        """从 git tag / 文件检测当前配置版本号 (F.6)."""
        try:
            result = subprocess.run(
                ["git", "tag", "-l", "ae-config-v*"],
                cwd=str(self.project_root), capture_output=True, text=True,
            )
            tags = result.stdout.strip().split("\n")
            versions = []
            for tag in tags:
                if tag.startswith("ae-config-v"):
                    try:
                        versions.append(int(tag.split("v")[-1]))
                    except ValueError:
                        pass
            return max(versions) if versions else 0
        except Exception:
            _logger.debug("git tag version detection failed", exc_info=True)
        # Fallback: count JSON config files
        existing = sorted(self._configs_dir.glob("ae-config-v*.json"))
        return len(existing)

    def revert_config(self, target_version: str) -> bool:
        """回滚到指定配置版本 (F.6)."""
        config_path = self._configs_dir / f"{target_version}.json"
        if not config_path.exists():
            return False
        target_config = json.loads(config_path.read_text())
        active_path = self._configs_dir / "active.json"
        active_path.write_text(json.dumps(target_config, indent=2, ensure_ascii=False))
        return True

    # ── sandbox evaluation (T72, F.12) ──

    def sandbox_evaluate(
        self,
        proposals: list[dict],
        candidate_rules: list | None = None,
        dry_run: bool = True,
    ) -> dict:
        """Evaluate threshold proposals and candidate rules in sandbox (T72).

        Receives ThresholdLearner proposals and/or DiagnosticRuleDiscoverer
        candidate rules, evaluates against historical data, returns per-item
        keep/revert/stop decisions.

        Args:
            proposals: From ThresholdLearner.propose_adjustments().
            candidate_rules: From DiagnosticRuleDiscoverer.discover().
            dry_run: If True, don't modify configs (default safe mode).

        Returns:
            {"decisions": [...], "summary": str}
        """
        if candidate_rules is None:
            candidate_rules = []

        decisions: list[dict] = []

        if not proposals and not candidate_rules:
            return {"decisions": [], "summary": "no proposals to evaluate"}

        current_config = self.get_current_config() or {}

        for p in proposals:
            param = p["param"]
            current_val = p["current"]
            proposed_val = p["proposed"]
            confidence = p.get("confidence", 0.5)

            # Decision logic: keep if confidence is high and change is moderate
            deviation = abs(proposed_val - current_val) / max(current_val, 1)
            if confidence > 0.9 and deviation < 0.3:
                action = "keep"
                reason = (
                    f"{param}: {current_val} → {proposed_val:.1f} "
                    f"({deviation:.1%} change, {confidence:.0%} confidence)"
                )
            elif deviation > 1.0:
                action = "stop"
                reason = (
                    f"{param}: {current_val} → {proposed_val:.1f} "
                    f"({deviation:.1%} change — extreme, needs manual review)"
                )
            else:
                action = "revert"
                reason = (
                    f"{param}: {current_val} → {proposed_val:.1f} "
                    f"({deviation:.1%} change, confidence {confidence:.0%})"
                )

            if not dry_run and action == "keep":
                # Persist the accepted threshold change
                current_config.setdefault("params", {})[param] = proposed_val
                self.save_config_snapshot(current_config)

            decisions.append({
                "item_type": "threshold",
                "param": param,
                "action": action,
                "reason": reason,
                "current": current_val,
                "proposed": proposed_val,
            })

        for rule in candidate_rules:
            score = getattr(rule, "correlation_score", 0)
            confidence = getattr(rule, "confidence", 0)
            if confidence > 0.9 and score > 0.6:
                action = "keep"
                reason = f"Rule '{rule.signal_name}' has strong evidence (ρ={score:.2f})"
            else:
                action = "revert"
                reason = f"Rule '{rule.signal_name}' needs more evidence (ρ={score:.2f})"

            if not dry_run and action == "keep":
                self._merge_rule(rule)

            decisions.append({
                "item_type": "candidate_rule",
                "param": rule.signal_name,
                "action": action,
                "reason": reason,
            })

        summary = (
            f"Evaluated {len(proposals)} threshold proposals + "
            f"{len(candidate_rules)} candidate rules: "
            f"{sum(1 for d in decisions if d['action'] == 'keep')} keep, "
            f"{sum(1 for d in decisions if d['action'] == 'revert')} revert, "
            f"{sum(1 for d in decisions if d['action'] == 'stop')} stop"
        )
        return {"decisions": decisions, "summary": summary}

    def _merge_rule(self, rule) -> None:
        """Merge an approved candidate rule into active diagnosis rules."""
        rules_path = self._metrics_dir / "baselines" / "merged_rules.json"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if rules_path.exists():
            existing = json.loads(rules_path.read_text())
        existing.append({
            "signal_name": rule.signal_name,
            "metric": rule.metric,
            "auto_params": getattr(rule, "auto_params", []),
            "possible_causes": getattr(rule, "causes", []),
            "actions": getattr(rule, "actions", []),
            "human_actions": getattr(rule, "human_actions", []),
        })
        rules_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    # ── helpers ──

    @staticmethod
    def _extract_numeric(value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            # For nested metrics like M5_token_efficiency, use total_tokens or efficiency_ratio
            return float(value.get("efficiency_ratio",
                                   value.get("total_tokens", 0)))
        return None


# ── F.7 可调参数空间 ──

TUNABLE_PARAMS: dict = {
    # ── 低风险：自动调整 ──
    "max_refine_per_source": {
        "default": 2, "range": (1, 4), "auto": True,
        "trigger": "同组件 2 次 refine 仍不满意",
        "adjustment": "±1",
    },
    "max_refine_global": {
        "default": 4, "range": (2, 8), "auto": True,
        "trigger": "全局 refine 频率高但收敛效果好",
        "adjustment": "±2",
    },
    "AE_MAX_TOOL_CALLS": {
        "default": 10, "range": (5, 20), "auto": True,
        "trigger": "developer 频繁触达上限",
        "adjustment": "+5",
    },
    "max_iter": {
        "default": 20, "range": (10, 40), "auto": True,
        "trigger": "复杂需求提前截断",
        "adjustment": "+10",
    },
    "token_budget_warning": {
        "default": None, "range": "按需求复杂度分档", "auto": True,
        "trigger": "连续 3 次超支",
        "adjustment": "设置警告线",
    },

    # ── 中风险：建议确认 ──
    "verification_trim_threshold": {
        "default": "基于设计文档层次", "range": "LEAF/PLATE/FULL 手动覆盖", "auto": False,
        "trigger": "plate_deep_audit 发现大量跨组件问题时",
    },
    "context_offloading_strategy": {
        "default": "每 stage 全量卸载", "range": "选择性卸载（仅大文件）", "auto": False,
        "trigger": "context 压力指标超标",
    },
    "prompt_template_selection": {
        "default": "B12 PromptRegistry", "range": "按需求类型匹配", "auto": False,
        "trigger": "特定需求类型反复失败",
    },
}

# 安全红线（不可自动调整）
SAFETY_RED_LINES: list[str] = [
    "Guardrail 禁止跳过",
    "Gate 最低通过标准",
    "Agent 权限范围（AUTHZ_MATRIX）",
    "PII 防护规则（PIIDetectionRule）",
]
