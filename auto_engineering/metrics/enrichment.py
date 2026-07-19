"""T69b+T69c: Metric enrichment — collector data → signals + diagnoses + suggestions.

Wired into TickOrchestrator._build_action() to inject metrics intelligence
into every action JSON returned to the agent.
"""
from auto_engineering.metrics.collector import MetricsCollector
from auto_engineering.metrics.diagnoser import Diagnoser
from auto_engineering.metrics.ratchet import RatchetController
from auto_engineering.metrics.signals import SignalDetector
from auto_engineering.metrics.suggestions import generate_suggestions


def compute_metrics_signals(
    collector: MetricsCollector,
    history: list[dict] | None = None,
    baseline: dict | None = None,
    project_root: str | None = None,
) -> dict:
    """Compute signals + diagnoses + suggestions from collector data (F.8.2-aligned).

    Pipeline: summary → SignalDetector.analyze → Diagnoser.diagnose
    → generate_suggestions → RatchetController.evaluate (low-risk auto-adjust).

    Returns a dict with 'metrics_signals', 'metrics_diagnoses', and
    'metrics_suggestions' keys, suitable for merging into the action JSON.
    """
    detector = SignalDetector()
    diagnoser = Diagnoser()

    summary = collector.get_latest_summary()
    if not summary:
        return {}

    # Build requirement history including current summary
    all_history = list(history or [])
    all_history.append(summary)

    signals = detector.analyze(all_history, baseline)
    signal_dicts = [
        {"name": s.name, "severity": s.severity, "metric": s.metric,
         "value": s.value, "baseline": s.baseline, "description": s.description}
        for s in signals
    ]

    diagnoses = []
    for s in signals:
        d = diagnoser.diagnose(s)
        if d is not None:
            diagnoses.append({
                "signal_name": d.signal_name,
                "severity": d.severity,
                "possible_causes": d.possible_causes,
                "suggested_actions": d.suggested_actions,
                "auto_adjustable": d.auto_adjustable,
                "needs_human": d.needs_human,
            })

    suggestions = generate_suggestions(signal_dicts, diagnoses)

    # RatchetController auto-adjust for low-risk auto-adjustable params
    ratchet_decisions = []
    if project_root is not None and baseline is not None:
        try:
            from pathlib import Path
            controller = RatchetController(Path(project_root))
            for diag in diagnoses:
                auto_params = diag.get("auto_adjustable", [])
                if auto_params:
                    # Low-risk: evaluate against baseline
                    decision = controller.evaluate(
                        before=baseline,
                        after=summary,
                        min_improvement=0.05,
                    )
                    if decision.action == "keep":
                        ratchet_decisions.append({
                            "action": decision.action,
                            "params": auto_params,
                            "reason": decision.reason,
                        })
        except Exception:
            _logger.warning("RatchetController enrichment failed", exc_info=True)

    result = {
        "metrics_signals": signal_dicts,
        "metrics_diagnoses": diagnoses,
        "metrics_suggestions": suggestions,
    }
    if ratchet_decisions:
        result["metrics_ratchet_decisions"] = ratchet_decisions

    return result
