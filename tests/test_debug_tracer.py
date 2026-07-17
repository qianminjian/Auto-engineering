"""DebugTracer 单元测试 — 调度轨迹/故障信息写入 debug 目录."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.loop.debug_tracer import DebugTracer


class TestDebugTracerInit:
    def test_creates_debug_dir(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        DebugTracer(debug_dir)
        assert debug_dir.is_dir()

    def test_noop_when_dir_exists(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        debug_dir.mkdir()
        (debug_dir / "existing.txt").write_text("keep")
        DebugTracer(debug_dir)
        assert (debug_dir / "existing.txt").read_text() == "keep"


class TestRecordTick:
    def test_writes_tick_snapshot_json(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        tracer = DebugTracer(debug_dir)
        tracer.record_tick(
            tick_num=3,
            stage_in="architect",
            action={"stage": "developer", "batch_id": "B1"},
            state_snapshot={"current_stage": "developer", "tick": 3},
            guardrail_results={"REDGuard": "pass"},
            gate_results={"safety": {"passed": True}},
            timing_ms={"t_orchestration": 45, "t_gate": 1200},
        )
        tick_file = debug_dir / "tick-0003.json"
        assert tick_file.is_file()
        data = json.loads(tick_file.read_text())
        assert data["tick"] == 3
        assert data["stage_in"] == "architect"
        assert data["action"]["stage"] == "developer"
        assert data["state_snapshot"]["current_stage"] == "developer"
        assert data["guardrail_results"]["REDGuard"] == "pass"
        assert data["gate_results"]["safety"]["passed"] is True
        assert data["timing_ms"]["t_orchestration"] == 45
        assert "timestamp" in data

    def test_tick_files_numbered_sequentially(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        tracer = DebugTracer(debug_dir)
        empty_action = {"stage": "idle"}
        empty_state: dict = {}
        for i in range(5):
            tracer.record_tick(
                tick_num=i,
                stage_in="idle",
                action=empty_action,
                state_snapshot=empty_state,
                guardrail_results={},
                gate_results={},
                timing_ms={},
            )
        for i in range(5):
            assert (debug_dir / f"tick-{i:04d}.json").is_file()


class TestRecordError:
    def test_appends_to_errors_jsonl(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        tracer = DebugTracer(debug_dir)
        tracer.record_error(tick=5, category="GUARDRAIL_BLOCK",
                            detail={"guardrail": "REDGuard", "message": "no red commit"})
        tracer.record_error(tick=7, category="GATE_FAIL",
                            detail={"gate": "type_check", "message": "F821 undefined"})
        errors_path = debug_dir / "errors.jsonl"
        assert errors_path.is_file()
        lines = errors_path.read_text().strip().split("\n")
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        assert e1["tick"] == 5
        assert e1["category"] == "GUARDRAIL_BLOCK"
        assert e1["detail"]["guardrail"] == "REDGuard"
        e2 = json.loads(lines[1])
        assert e2["tick"] == 7
        assert e2["category"] == "GATE_FAIL"


class TestFinalize:
    def test_writes_trace_json(self, tmp_path: Path) -> None:
        debug_dir = tmp_path / "debug"
        tracer = DebugTracer(debug_dir)
        empty_action = {"stage": "idle"}
        empty_state: dict = {}
        for i in range(3):
            tracer.record_tick(
                tick_num=i, stage_in="idle", action=empty_action,
                state_snapshot=empty_state, guardrail_results={},
                gate_results={}, timing_ms={},
            )
        tracer.record_error(tick=1, category="GUARDRAIL_BLOCK",
                            detail={"guardrail": "REDGuard"})
        tracer.finalize(verdict="GOAL_ACHIEVED", total_ticks=3)

        trace_file = debug_dir / "trace.json"
        assert trace_file.is_file()
        data = json.loads(trace_file.read_text())
        assert data["verdict"] == "GOAL_ACHIEVED"
        assert data["total_ticks"] == 3
        assert data["error_counts"]["GUARDRAIL_BLOCK"] == 1
        assert data["stage_sequence"] == ["idle", "idle", "idle"]
        assert "total_duration_ms" in data


class TestDisabled:
    """disabled() 工厂返回的实例所有方法均为 no-op."""

    def test_disabled_record_tick_does_nothing(self, tmp_path: Path) -> None:
        tracer = DebugTracer.disabled()
        tracer.record_tick(0, "idle", {}, {}, {}, {}, {})
        # no crash, no files

    def test_disabled_record_error_does_nothing(self, tmp_path: Path) -> None:
        tracer = DebugTracer.disabled()
        tracer.record_error(0, "X", {})
        # no crash

    def test_disabled_finalize_does_nothing(self, tmp_path: Path) -> None:
        tracer = DebugTracer.disabled()
        tracer.finalize("GOAL_ACHIEVED", 10)
        # no crash
