"""收敛阶段的 RatchetController 编排。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def run_ratchet(project_root: Path, collector, enrichment: dict) -> dict | None:
    """执行 keep/revert/stop 判定和配置版本化闭环。"""

    try:
        from auto_engineering.metrics.ratchet import RatchetController

        baseline = collector.load_baseline() or {}
        before = {
            key: value
            for key, value in baseline.items()
            if key.startswith("M") and isinstance(value, (int, float))
        }
        after = {
            key: value
            for key, value in enrichment.get("metrics_signals", {}).items()
            if key.startswith("M") and isinstance(value, (int, float))
        }
        if not before or not after:
            return None
        ratchet = RatchetController(project_root)
        decision = ratchet.evaluate(before, after)

        try:
            from auto_engineering.metrics.threshold_learner import ThresholdLearner

            learner = ThresholdLearner(project_root / ".ae-state" / "metrics")
            proposals = learner.propose_adjustments()
            if proposals:
                _logger.info(
                    "ThresholdLearner proposals: %s",
                    [(item["param"], item["proposed"]) for item in proposals],
                )
        except (ImportError, FileNotFoundError, ValueError, OSError):
            _logger.debug(
                "ThresholdLearner.propose_adjustments skipped",
                exc_info=True,
            )

        result: dict = {
            "action": decision.action,
            "reason": decision.reason,
            "config_version": decision.config_version,
        }
        if decision.action == "keep":
            snapshot_tag = ratchet.save_config_snapshot(after)
            if snapshot_tag:
                result["snapshot_tag"] = snapshot_tag
        elif decision.action in {"revert", "stop"}:
            if ratchet.rollback() is not None:
                result["rollback"] = "applied"
        return result
    except (KeyboardInterrupt, SystemExit):
        raise
    except (
        ImportError,
        ValueError,
        TypeError,
        OSError,
        KeyError,
        json.JSONDecodeError,
    ):
        _logger.debug("RatchetController evaluate failed", exc_info=True)
        return None
