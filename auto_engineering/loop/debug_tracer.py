"""DebugTracer — 调度轨迹与故障信息写入目标项目的 debug 目录.

激活方式: ae dev-loop --init --debug 或 AE_DEBUG=1 环境变量.
输出: <debug_dir>/tick-{N:04d}.json, errors.jsonl, trace.json

零开销保证: disabled() 工厂返回的实例所有方法均为 no-op (仅 if None: return 检查).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

_ISO_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_iso() -> str:
    return datetime.now(UTC).strftime(_ISO_FMT)


class DebugTracer:
    """将 tick 快照、故障事件和最终摘要写入 debug 目录."""

    def __init__(self, debug_dir: Path) -> None:
        self._dir = debug_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._errors_path = self._dir / "errors.jsonl"
        self._stage_sequence: list[str] = []
        self._error_counts: dict[str, int] = {}
        self._t_start = time.perf_counter()

    @staticmethod
    def disabled() -> "DebugTracer":
        """返回一个所有方法均为 no-op 的实例 (零开销, 无文件写入)."""
        tracer = object.__new__(DebugTracer)
        tracer._dir = None  # type: ignore[attr-defined]
        return tracer

    # ── 记录方法 ──

    def record_tick(
        self,
        tick_num: int,
        stage_in: str,
        action: dict,
        state_snapshot: dict,
        guardrail_results: dict,
        gate_results: dict,
        timing_ms: dict,
    ) -> None:
        """写入 per-tick 快照到 tick-{N:04d}.json."""
        if self._dir is None:
            return
        stage_out = action.get("stage", "?")
        self._stage_sequence.append(stage_out)
        snapshot = {
            "tick": tick_num,
            "timestamp": _now_iso(),
            "stage_in": stage_in,
            "stage_out": stage_out,
            "action": action,
            "state_snapshot": state_snapshot,
            "guardrail_results": guardrail_results,
            "gate_results": gate_results,
            "timing_ms": timing_ms,
        }
        tick_file = self._dir / f"tick-{tick_num:04d}.json"
        tick_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_error(self, tick: int, category: str, detail: dict) -> None:
        """追加故障事件到 errors.jsonl."""
        if self._dir is None:
            return
        entry = {
            "tick": tick,
            "timestamp": _now_iso(),
            "category": category,
            "detail": detail,
        }
        self._error_counts[category] = self._error_counts.get(category, 0) + 1
        with open(self._errors_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def finalize(self, verdict: str, total_ticks: int) -> None:
        """写入最终摘要 trace.json."""
        if self._dir is None:
            return
        t_total_ms = (time.perf_counter() - self._t_start) * 1000
        trace = {
            "verdict": verdict,
            "total_ticks": total_ticks,
            "stage_sequence": self._stage_sequence,
            "error_counts": self._error_counts,
            "total_duration_ms": round(t_total_ms, 2),
            "finished_at": _now_iso(),
        }
        trace_file = self._dir / "trace.json"
        trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
