"""Phase 23 Integration tests — P0 data flow fixes (T79+T80+T81).

T79: Signal pipeline history + baseline passing
T80: M2 criteria_met recording for critic_major_rate
T81: M5 git diff fix (--cached → HEAD~1)

RED phase: These tests FAIL because:
  - compute_metrics_signals receives no history/baseline from build_action
  - record_convergence criteria_met is always "" → M2 always 0
  - _compute_loc_added uses --cached HEAD → always 0 after commits

Design ref: v5.6-Design-Loop.md appendix F.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto_engineering.metrics.collector import MetricsCollector, AIOrigin, get_collector, set_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a clean temp git repo with one initial commit and a second commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@x"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True, env=env)
    (repo / "file1.py").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "-C", str(repo), "add", "file1.py"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, capture_output=True, env=env)
    # Second commit with more lines
    (repo / "file2.py").write_text("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n")
    subprocess.run(["git", "-C", str(repo), "add", "file2.py"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "add file2"], check=True, capture_output=True, env=env)
    return repo


# =============================================================================
# T79 — Signal pipeline history + baseline
# =============================================================================


class TestSignalPipelineHistory:
    """T79: Verify compute_metrics_signals receives history + baseline."""

    def test_compute_metrics_signals_accepts_history(self, tmp_path: Path) -> None:
        """compute_metrics_signals MUST accept and use history parameter."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t1", "h1")

        # Without history, returns empty since no summary yet
        result = compute_metrics_signals(collector, history=[], baseline={})
        assert isinstance(result, dict)

    def test_collector_has_load_history_method(self) -> None:
        """MetricsCollector MUST have a method to load historical summaries."""
        assert hasattr(MetricsCollector, "load_history"), (
            "T79 NOT FIXED: MetricsCollector has no load_history() method. "
            "Signal pipeline cannot access historical data for trend detection."
        )

    def test_collector_has_load_baseline_method(self) -> None:
        """MetricsCollector MUST have a method to load baseline data."""
        assert hasattr(MetricsCollector, "load_baseline"), (
            "T79 NOT FIXED: MetricsCollector has no load_baseline() method. "
            "Signal pipeline cannot compare against baselines."
        )

    def test_convergence_check_passes_history_to_signals(self) -> None:
        """_convergence_check() MUST pass history to compute_metrics_signals.

        T83 moved signal computation from build_action (every tick) to
        _convergence_check (done-verdict only). The history parameter must
        still be passed for trend detection.
        """
        import auto_engineering.loop.tick_orchestrator as tmod
        import inspect

        source = inspect.getsource(tmod.TickOrchestrator._convergence_check)
        # Check that compute_metrics_signals is called with history= parameter
        assert "compute_metrics_signals" in source, (
            "T79 + T83: compute_metrics_signals not found in _convergence_check."
        )
        assert "history=" in source or "recent_history" in source or (
            "history" in source.split("compute_metrics_signals")[1].split(")")[0]
            if "compute_metrics_signals" in source else False
        ), (
            "T79 NOT FIXED: _convergence_check() does not pass history to "
            "compute_metrics_signals(). Signal trend detection will never fire."
        )


# =============================================================================
# T80 — M2 criteria_met
# =============================================================================


class TestM2CriteriaMet:
    """T80: Verify M2 critic_major_rate is computed from criteria_met."""

    def test_record_convergence_stores_criteria_met(self, tmp_path: Path) -> None:
        """record_convergence() MUST store criteria_met in event payload."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t2", "h2")
        collector.record_convergence("APPROVE", 5, criteria_met="critic_approved")
        collector._flush_events()

        # Read back the events
        events_path = tmp_path / ".ae-state" / "metrics" / "requirements" / "t2" / "events.jsonl"
        events = [json.loads(l) for l in events_path.read_text().strip().split("\n")]
        conv_events = [e for e in events if e["event_type"] == "convergence"]
        assert len(conv_events) == 1
        assert conv_events[0]["payload"]["criteria_met"] == "critic_approved", (
            "T80 NOT FIXED: record_convergence criteria_met field is not stored. "
            "M2 calculation will always be zero because criteria_met filtering fails."
        )

    def test_m2_nonzero_with_critic_major(self, tmp_path: Path) -> None:
        """M2 MUST be > 0 when critic issued MAJOR verdicts."""
        collector = MetricsCollector(tmp_path)
        collector.begin_requirement("t2b", "h2b")
        # Simulate 5 ticks + 1 critic-approved + 1 critic-MAJOR
        for i in range(5):
            collector._events.append({
                "timestamp": "",
                "event_type": "tick_complete",
                "thread_id": "t2b",
                "payload": {"tick_number": i, "stage": "critic", "verdict": "APPROVE"},
            })
        collector.record_convergence("APPROVE", 5, criteria_met="critic_approved")
        collector.record_convergence("MAJOR", 6, criteria_met="critic_major_found")
        # Also add a token event to make M5 non-NaN
        collector._events.append({
            "timestamp": "",
            "event_type": "token_usage",
            "thread_id": "t2b",
            "payload": {"input_tokens": 100, "output_tokens": 50},
        })

        summary = collector._compute_summary(loc_added=10)
        assert summary["M2_critic_major_rate"] > 0, (
            "T80 NOT FIXED: M2_critic_major_rate is zero despite MAJOR verdict. "
            "criteria_met field is not being populated in convergence events."
        )

    def test_convergence_event_in_tick_orchestrator_passes_criteria_met(self) -> None:
        """TickOrchestrator MUST pass criteria_met when recording convergence.

        RED: Currently record_convergence is called but criteria_met may not be set.
        """
        import auto_engineering.loop.tick_orchestrator as tmod
        import inspect

        source = inspect.getsource(tmod.TickOrchestrator)
        # record_convergence should be called with criteria_met=... somewhere
        has_criteria_met = "criteria_met=" in source
        assert has_criteria_met, (
            "T80 NOT FIXED: TickOrchestrator does not pass criteria_met "
            "to record_convergence(). M2 will always be zero."
        )


# =============================================================================
# T81 — M5 git diff fix
# =============================================================================


class TestM5GitDiffFix:
    """T81: Verify _compute_loc_added uses correct git diff command."""

    def test_loc_added_nonzero_with_committed_changes(self, tmp_path: Path) -> None:
        """_compute_loc_added MUST return > 0 when there are committed changes.

        RED: Currently uses --cached HEAD which returns 0 for committed changes.
        """
        repo = _make_git_repo(tmp_path)
        loc = MetricsCollector._compute_loc_added(repo)
        assert loc > 0, (
            "T81 NOT FIXED: _compute_loc_added returns 0 despite committed changes. "
            "The --cached flag only counts staged (not committed) changes."
        )

    def test_git_diff_does_not_use_cached(self) -> None:
        """_compute_loc_added MUST NOT use --cached flag in git command."""
        import inspect
        source = inspect.getsource(MetricsCollector._compute_loc_added)
        # Only check git diff command lines (not comments)
        git_cmd_lines = [
            l for l in source.split("\n")
            if "git" in l and "diff" in l and not l.strip().startswith("#")
        ]
        has_cached = any("--cached" in l for l in git_cmd_lines)
        assert not has_cached, (
            "T81 NOT FIXED: _compute_loc_added still uses --cached flag "
            "in the git command. This causes M5 to always be zero."
        )

    def test_loc_added_zero_in_fresh_repo(self, tmp_path: Path) -> None:
        """_compute_loc_added returns 0 in a fresh repo with no extra changes."""
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        env = {
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
        }
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@x"], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True, env=env)
        (repo / "seed.txt").write_text("hello\n")
        subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True, capture_output=True, env=env)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, capture_output=True, env=env)
        # Only one commit, no additional changes
        loc = MetricsCollector._compute_loc_added(repo)
        assert loc == 0
