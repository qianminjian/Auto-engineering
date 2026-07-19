"""T69c: Automated suggestions generator from signals + diagnoses.

Wired into TickOrchestrator._build_action() to provide actionable
guidance alongside every action JSON.
"""

SEVERITY_TO_LEVEL = {"INFO": "info", "WARN": "warn", "CRITICAL": "error"}


def generate_suggestions(
    signals: list[dict],
    diagnoses: list[dict],
) -> list[dict]:
    """Generate actionable suggestions from detected signals and diagnoses.

    Each suggestion has:
    - level: "info" | "warn" | "error"
    - message: human-readable action description
    - source: which signal or diagnosis rule triggered it
    """
    suggestions: list[dict] = []

    for signal in signals:
        severity = signal.get("severity", "INFO")
        level = SEVERITY_TO_LEVEL.get(severity, "info")
        suggestions.append({
            "level": level,
            "message": f"[{signal.get('name')}] {signal.get('description', '')}",
            "source": signal.get("name", "unknown"),
        })

    for diag in diagnoses:
        severity = diag.get("severity", "INFO")
        level = SEVERITY_TO_LEVEL.get(severity, "info")
        for action in diag.get("suggested_actions", []):
            suggestions.append({
                "level": level,
                "message": action,
                "source": diag.get("signal_name", "unknown"),
            })

    return suggestions
