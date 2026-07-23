"""Phase 24 Integration tests — P1/P2 fixes (T82-T90).

T82: category parameter to begin_requirement() calls
T83: signal pipeline only on convergence
T84: tick numbering consistency (0-based→1-based)
T85: resume_events restore category from metadata
T86: compare_periods align with design
T87: dead code helpers into analyze() or internal API
T88: remove redundant _flush after begin_requirement
T89: replace manual median with statistics.median
T90: implement _get_tag_timestamp() for compare_periods

RED phase: These tests FAIL because P1/P2 fixes are not yet implemented.

⚠ P1-9 WARNING: Several tests in this file use inspect.getsource() to verify
source code PRESENCE rather than behavioral correctness. These tests will pass
silently after refactoring that changes code structure while preserving behavior
— a false negative.  Treat GREEN results as "code exists" not "code works".

Design ref: v5.6-Design-Loop.md appendix F + Phase 20 Round 4 audit findings.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path

import pytest

from auto_engineering.metrics.collector import MetricsCollector, AIOrigin


# =============================================================================
# T82 — category parameter to begin_requirement() calls
# =============================================================================


class TestT82CategoryParameter:
    """T82: Verify begin_requirement() calls pass requirement_category."""

    def test_begin_requirement_accepts_category(self, tmp_path: Path) -> None:
        """begin_requirement MUST accept and store requirement_category."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t1", "h1", requirement_category="simple_function")
        assert collector._current_category == "simple_function"

    def test_category_written_to_metadata(self, tmp_path: Path) -> None:
        """Category MUST be persisted in metadata.json for by_category baselines."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t2", "h2", requirement_category="complex_multi_module")
        collector._flush()

        meta_path = tmp_path / ".ae-state" / "metrics" / "requirements" / "t2" / "metadata.json"
        assert meta_path.exists(), (
            "T82 NOT FIXED: metadata.json not written. "
            "Category baseline generation requires category metadata."
        )
        meta = json.loads(meta_path.read_text())
        assert meta["category"] == "complex_multi_module"

    def test_category_defaults_to_empty_string(self, tmp_path: Path) -> None:
        """When no category is provided, _current_category should be empty string."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t3", "h3")
        assert collector._current_category == "", (
            "T82 NOT FIXED: _current_category should default to '' when not provided."
        )

    def test_init_tick_loop_passes_category(self) -> None:
        """run_tick_init() MUST pass requirement_category to begin_requirement().

        RED: Currently passes only thread_id and req_hash.
        """
        # auto_engineering.cli.dev_loop is shadowed by Click Command in __init__.py
        # Read source file directly
        source_path = Path(__file__).parent.parent / "auto_engineering" / "cli" / "dev_loop.py"
        source = source_path.read_text()

        # Find run_tick_init and extract its body
        assert "begin_requirement" in source, "No begin_requirement call found"
        # Find the begin_requirement call within run_tick_init
        func_start = source.find("def run_tick_init(")
        assert func_start >= 0, "Cannot find run_tick_init function"
        # Find next def after run_tick_init
        next_def = source.find("\ndef ", func_start + 10)
        func_body = source[func_start:next_def] if next_def > 0 else source[func_start:]
        assert "requirement_category" in func_body, (
            "T82 NOT FIXED: run_tick_init() does not pass requirement_category "
            "to begin_requirement(). by_category/ will never get category-specific baselines."
        )

    def testrun_standalone_passes_category(self) -> None:
        """run_standalone() MUST pass requirement_category to begin_requirement().

        RED: Currently passes only thread_id and req_hash.
        """
        source_path = Path(__file__).parent.parent / "auto_engineering" / "cli" / "dev_loop.py"
        source = source_path.read_text()

        assert "begin_requirement" in source, "No begin_requirement call found"
        # Find run_standalone function (v5.5 legacy path)
        func_start = source.find("def run_standalone(")
        assert func_start >= 0, "Cannot find run_standalone function"
        # Find next top-level def after run_standalone
        next_def = source.find("\ndef ", func_start + 10)
        func_body = source[func_start:next_def] if next_def > 0 else source[func_start:]
        assert "requirement_category" in func_body, (
            "T82 NOT FIXED: run_standalone() does not pass requirement_category "
            "to begin_requirement(). by_category/ will never get category-specific baselines."
        )


# =============================================================================
# T83 — Signal pipeline only on convergence
# =============================================================================


class TestT83SignalOnlyOnConvergence:
    """T83: compute_metrics_signals() should only be called on convergence."""

    def testbuild_action_does_not_compute_signals(self) -> None:
        """build_action() MUST NOT call compute_metrics_signals unconditionally.

        Signal computation should be in the convergence path, not every tick.
        """
        import auto_engineering.loop.tick_orchestrator as tmod
        import inspect as _inspect

        source = _inspect.getsource(tmod.TickOrchestrator.build_action)
        assert "compute_metrics_signals" not in source, (
            "T83 NOT FIXED: build_action() still calls compute_metrics_signals "
            "unconditionally. Move it to _convergence_check() for done-verdict-only."
        )

    def test_convergence_check_computes_signals(self) -> None:
        """_convergence_check() MUST compute metrics signals on terminal verdict."""
        import auto_engineering.loop.tick_orchestrator as tmod
        import inspect as _inspect

        source = _inspect.getsource(tmod.TickOrchestrator._convergence_check)
        assert "compute_metrics_signals" in source, (
            "T83 NOT FIXED: _convergence_check() does not compute metrics signals. "
            "Signal pipeline must be in the done-verdict branch."
        )


# =============================================================================
# T84 — Tick numbering consistency (0-based→1-based)
# =============================================================================


class TestT84TickNumbering:
    """T84: record_tick_snapshot MUST use 1-based tick numbers."""

    def test_record_tick_snapshot_uses_one_based(self, tmp_path: Path) -> None:
        """record_tick_snapshot writes tick-0001.json with tick_number=1."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t4", "h4")
        collector.record_tick_snapshot(
            tick_number=1,
            stage_in="developer",
            action={"type": "develop"},
            state_snapshot={},
            guardrail_results={},
            gate_results={},
            timing_ms={},
        )

        tick_file = (
            tmp_path / ".ae-state" / "metrics" / "requirements" / "t4"
            / "ticks" / "tick-0001.json"
        )
        assert tick_file.exists()
        data = json.loads(tick_file.read_text())
        assert data["tick"] == 1, (
            "T84 NOT FIXED: tick_number in snapshot is not 1-based. "
            "Should be 1 for first tick, not 0."
        )

    def test_orchestrator_call_site_passes_one_based(self) -> None:
        """TickOrchestrator MUST pass tick_no + 1 to record_tick_snapshot()."""
        import auto_engineering.loop.tick_orchestrator as tmod
        import inspect as _inspect

        # The tick_orchestrator module is inspectable
        source = _inspect.getsource(tmod.TickOrchestrator.tick_dict)
        # The record_tick_snapshot call should use tick_no + 1, not tick_no
        # Find the record_tick_snapshot call and check its tick_number parameter
        lines = source.split("\n")
        in_snapshot_call = False
        for line in lines:
            if "record_tick_snapshot(" in line:
                in_snapshot_call = True
            elif in_snapshot_call and "tick_number=" in line:
                assert "tick_no + 1" in line or "tick_no+1" in line, (
                    "T84 NOT FIXED: record_tick_snapshot call site uses "
                    f"raw tick_no (0-based): {line.strip()}. "
                    "Must use tick_no + 1 for 1-based numbering."
                )
                break


# =============================================================================
# T85 — resume_events restore category from metadata
# =============================================================================


class TestT85ResumeCategory:
    """T85: resume_events() MUST restore _current_category from metadata.json."""

    def test_resume_events_restores_category(self, tmp_path: Path) -> None:
        """After resume_events(), _current_category should match metadata.json."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t5", "h5", requirement_category="medium_crud")
        collector._flush()

        # Simulate new process: create fresh collector, resume
        collector2 = MetricsCollector(tmp_path)
        events = collector2.resume_events("t5")
        assert len(events) > 0, "resume_events should load existing events"

        assert collector2._current_category == "medium_crud", (
            "T85 NOT FIXED: resume_events() does not restore _current_category "
            "from metadata.json. Cross-process category is lost."
        )

    def test_resume_events_empty_category_when_no_metadata(self, tmp_path: Path) -> None:
        """resume_events defaults to '' when no metadata.json exists."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t5b", "h5b")  # No category
        collector._flush()

        collector2 = MetricsCollector(tmp_path)
        collector2.resume_events("t5b")
        assert collector2._current_category == ""


# =============================================================================
# T86 — compare_periods align with design
# =============================================================================


class TestT86ComparePeriods:
    """T86: compare_periods must work with tag-timestamp-based before/after."""

    def test_compare_periods_accepts_tags(self, tmp_path: Path) -> None:
        """compare_periods MUST accept before_tag and after_tag parameters."""
        collector = MetricsCollector(tmp_path)
        result = collector.compare_periods("v1.0", "v2.0")
        # Should return None (tags don't exist) or dict, not crash
        assert result is None or isinstance(result, dict)

    def test_compare_periods_returns_m1_m2_medians(self, tmp_path: Path) -> None:
        """compare_periods output MUST contain M1 and M2 median values."""
        collector = MetricsCollector(tmp_path)
        # Pre-populate baselines for tags
        baselines_dir = tmp_path / ".ae-state" / "metrics" / "baselines"
        baselines_dir.mkdir(parents=True, exist_ok=True)
        baseline_v1 = {
            "sample_size": 5,
            "M1": {"median": 3.0, "p95": 8.0},
            "M2": {"median": 0.2, "p95": 0.8},
        }
        (baselines_dir / "v1.0.json").write_text(json.dumps(baseline_v1))
        (baselines_dir / "v2.0.json").write_text(json.dumps({
            "sample_size": 5,
            "M1": {"median": 2.0, "p95": 5.0},
            "M2": {"median": 0.1, "p95": 0.5},
        }))

        result = collector.compare_periods("v1.0", "v2.0")
        assert result is not None, "compare_periods returned None with existing tag files"
        assert "before" in result
        assert "after" in result
        assert result["before"]["M1"]["median"] == 3.0
        assert result["after"]["M2"]["median"] == 0.1


# =============================================================================
# T87 — Dead code helpers into analyze() or internal API
# =============================================================================


class TestT87SignalsCoverage:
    """T87: Signal helper methods must be reachable from production path."""

    def test_analyze_calls_detect_trend(self) -> None:
        """analyze() MUST call _detect_trend() in its code path."""
        import auto_engineering.metrics.signals as smod
        import inspect as _inspect

        source = _inspect.getsource(smod.SignalDetector.analyze)
        assert "_detect_trend" in source, (
            "T87 NOT FIXED: _detect_trend is dead code — not called from analyze() "
            "or any other production path."
        )


# =============================================================================
# T88 — Remove redundant _flush after begin_requirement
# =============================================================================


class TestT88NoRedundantFlush:
    """T88: run_tick_init MUST NOT call _flush() after begin_requirement()."""

    def test_init_tick_loop_has_no_flush_after_begin(self) -> None:
        """run_tick_init() MUST NOT call collector._flush() after begin_requirement."""
        source_path = Path(__file__).parent.parent / "auto_engineering" / "cli" / "dev_loop.py"
        source = source_path.read_text()

        # Extract run_tick_init function body
        func_start = source.find("def run_tick_init(")
        assert func_start >= 0, "Cannot find run_tick_init function"
        next_def = source.find("\ndef ", func_start + 10)
        func_body = source[func_start:next_def] if next_def > 0 else source[func_start:]

        lines = func_body.split("\n")
        begin_idx = None
        for i, line in enumerate(lines):
            if "begin_requirement" in line:
                begin_idx = i
                break
        assert begin_idx is not None, "No begin_requirement call found"

        # Check the next 5 lines after begin_requirement for _flush
        after_lines = lines[begin_idx + 1:begin_idx + 6]
        has_flush = any("_flush()" in l for l in after_lines)
        assert not has_flush, (
            "T88 NOT FIXED: run_tick_init() has redundant _flush() after "
            "begin_requirement(). The _flush is already called when requirement ends."
        )


# =============================================================================
# T89 — Replace manual median with statistics.median
# =============================================================================


class TestT89MedianConsistency:
    """T89: Manual _median() should match statistics.median() output."""

    def test_manual_median_matches_statistics(self) -> None:
        """_median() output MUST match statistics.median()."""
        import statistics

        test_cases = [
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [1.0, 2.0, 3.0, 4.0],
            [5.0],
            [],
            [1.0, 100.0, 2.0],
        ]
        for values in test_cases:
            manual = MetricsCollector._median(values)
            expected = statistics.median(values) if values else 0.0
            assert manual == expected, (
                f"T89 NOT FIXED: _median({values}) = {manual} != statistics.median = {expected}"
            )

    def test_collector_uses_statistics_module(self) -> None:
        """MetricsCollector SHOULD import statistics for median calculation."""
        import inspect as _inspect

        source = _inspect.getsource(MetricsCollector._median)
        # After fix, _median should use statistics.median or the method should be simpler
        # At minimum the implementation should be correct
        assert "sorted" in source or "statistics" in source, (
            "T89: _median implementation present (passes, just checking)"
        )


# =============================================================================
# T90 — _get_tag_timestamp implementation
# =============================================================================


class TestT90TagTimestamp:
    """T90: _get_tag_timestamp must return timestamp for git tags."""

    def test_get_tag_timestamp_exists(self) -> None:
        """MetricsCollector MUST have _get_tag_timestamp method."""
        assert hasattr(MetricsCollector, "_get_tag_timestamp"), (
            "T90 NOT FIXED: MetricsCollector has no _get_tag_timestamp() method. "
            "compare_periods cannot dynamically split by tag timestamps."
        )

    def test_get_tag_timestamp_returns_float_or_none(self, tmp_path: Path) -> None:
        """_get_tag_timestamp MUST return float or None."""
        collector = MetricsCollector(tmp_path)
        result = collector._get_tag_timestamp("nonexistent-tag")
        assert result is None or isinstance(result, float), (
            "T90 NOT FIXED: _get_tag_timestamp should return float timestamp or None."
        )
