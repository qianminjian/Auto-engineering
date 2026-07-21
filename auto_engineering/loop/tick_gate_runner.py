"""TickGateRunner — gate execution delegate extracted from TickOrchestrator (P0-1).

Handles gate selection, parallel execution, result parsing, snapshot_sha
computation, metrics recording, tracing spans, and audit logging.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class TickGateRunner:
    """Gate execution subsystem — runs all gates and returns structured results.

    Separated from TickOrchestrator so the orchestrator only handles
    coordination (when to run gates), not execution mechanics (how to
    run, parse, measure, trace, and audit gates).
    """

    def __init__(
        self,
        project_root: Path,
        *,
        init_manifest: dict[str, Any] | None = None,
        gate_runner: Any = None,
        tracer: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self._project_root = project_root
        self._injected_runner = gate_runner
        self._tracer = tracer
        self._audit_logger = audit_logger
        self._gates = self._load_gates(init_manifest)

    # ── Gate selection ──

    @staticmethod
    def _load_gates(init_manifest: dict[str, Any] | None) -> list:
        from auto_engineering.gates.registry import DEFAULT_GATES, build_gates_from_manifest
        if init_manifest:
            return build_gates_from_manifest(init_manifest)
        return DEFAULT_GATES

    def reload(self, init_manifest: dict[str, Any] | None = None) -> None:
        """Reload gate list after manifest change (system escalation, resume)."""
        self._gates = self._load_gates(init_manifest)

    # ── Execution ──

    def run(
        self,
        files_changed: list[str],
        *,
        stage: str = "",
        tick: int = 0,
    ) -> tuple[dict[str, Any], float]:
        """Run all gates. Returns (gate_results_dict, duration_ms)."""
        gate_names = tuple(g.name for g in self._gates)

        gate_span = None
        if self._tracer is not None:
            gate_span = self._tracer.start_span(
                "gates.run", attributes={"gate_names": list(gate_names)})

        t_g = time.perf_counter()
        if self._injected_runner:
            raw = self._injected_runner(gate_names, self._project_root)
        else:
            from auto_engineering.gates.runner import run_gates
            raw = run_gates(gate_names, self._project_root,
                            files_changed=files_changed)
        per_gate = raw.get("gate_summary", raw)
        duration_ms = (time.perf_counter() - t_g) * 1000

        from auto_engineering.loop.guardrails.stateful import _aggregate_sha
        snapshot_sha = _aggregate_sha(files_changed, self._project_root)
        ran_at = datetime.now(UTC).isoformat()

        gate_results: dict[str, Any] = {
            name: {
                "passed": (
                    v.get("passed") if isinstance(v, dict)
                    else getattr(v, "passed", None)
                ),
                "message": (
                    v.get("message", "") if isinstance(v, dict)
                    else getattr(v, "message", "") or ""
                ),
                "files_snapshot_sha": snapshot_sha,
                "ran_at": ran_at,
            }
            for name, v in per_gate.items()
        }

        # T69a: Record gate results for metrics collector
        from auto_engineering.metrics.collector import AIOrigin, get_collector
        mc = get_collector()
        if mc is not None:
            for name, info in gate_results.items():
                findings = 0
                msg = info.get("message", "")
                if isinstance(msg, str) and msg:
                    findings = msg.count("\n") + 1 if msg.strip() else 0
                mc.record_gate_result(
                    gate_name=name,
                    passed=bool(info.get("passed")),
                    duration_ms=int(duration_ms),
                    findings_count=findings,
                    ai_origin=AIOrigin(
                        level="led", agent_role="developer", driver_type="agent",
                    ),
                )

        # T75: close gate tracing span + T76: audit log gate results
        if gate_span is not None:
            passed = all(v.get("passed") for v in gate_results.values())
            gate_span.set_attribute("all_passed", passed)
            gate_span.set_attribute("gate_count", len(gate_results))
            gate_span.end()

        if self._audit_logger is not None:
            self._audit_logger.log_event(
                event="gate_run",
                stage=stage,
                tick=tick,
                gate_results={
                    name: {"passed": v["passed"], "message": v["message"][:200]}
                    for name, v in gate_results.items()
                },
            )

        return gate_results, duration_ms
