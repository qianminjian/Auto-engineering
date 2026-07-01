"""Extended coverage tests for gates/coverage.py (74% → ≥85%).

Covers missed paths:
- _emit_freeze_warning at counter milestones (1, 6, 11)
- run() with non-existent project_root
- _resolve_pytest_cmd with custom pytest_bin / no pytest
- subprocess.TimeoutExpired / FileNotFoundError
- coverage data found: above/below threshold, strict/non-strict
- no coverage data (no TOTAL match)
"""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from auto_engineering.gates.base import Verdict
from auto_engineering.gates.coverage import (
    CoverageGate,
    _emit_freeze_warning,
    _TOTAL_COV_RE,
    _run_counter,
)


# ============================================================
# Group 1: _emit_freeze_warning
# ============================================================


def test_emit_freeze_warning_triggers_every_5_runs() -> None:
    """_emit_freeze_warning triggers DeprecationWarning every 5th run."""
    # Reset global counter by calling enough times to reach a known state
    import auto_engineering.gates.coverage as cov_mod
    cov_mod._run_counter = 0

    with pytest.warns(DeprecationWarning, match="CoverageGate 已冻结"):
        _emit_freeze_warning()

    # runs 2-5 should NOT warn
    for _ in range(4):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _emit_freeze_warning()  # should not raise

    # run 6 (6 % 5 == 1) should warn again
    with pytest.warns(DeprecationWarning, match="CoverageGate 已冻结"):
        _emit_freeze_warning()


# ============================================================
# Group 2: _resolve_pytest_cmd
# ============================================================


def test_resolve_pytest_cmd_custom_bin() -> None:
    """_resolve_pytest_cmd returns custom bin when pytest_bin is set."""
    gate = CoverageGate(pytest_bin="/custom/pytest")
    cmd = gate._resolve_pytest_cmd()
    assert cmd == ["/custom/pytest"]


def test_resolve_pytest_cmd_none_not_found() -> None:
    """_resolve_pytest_cmd returns None when pytest not in PATH and no bin set."""
    with patch("auto_engineering.gates.coverage.shutil.which", return_value=None):
        gate = CoverageGate()
        cmd = gate._resolve_pytest_cmd()
        assert cmd is None


# ============================================================
# Group 3: run() — project_root边界
# ============================================================


def test_run_project_root_not_exists(tmp_path: Path) -> None:
    """run() returns Verdict.failed when project_root does not exist."""
    nonexistent = tmp_path / "nonexistent"
    gate = CoverageGate()
    verdict = gate.run(nonexistent)
    assert verdict.passed is False
    assert "不存在" in verdict.message


def test_run_project_root_exists_no_cov_data(tmp_path: Path) -> None:
    """run() with project_root existing but no pytest-cov → skip verdict."""
    gate = CoverageGate(pytest_bin="pytest")
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "collected 0 items"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        verdict = gate.run(tmp_path)
        assert "skip" in verdict.message.lower()


# ============================================================
# Group 4: run() — subprocess exceptions
# ============================================================


def test_run_subprocess_timeout(tmp_path: Path) -> None:
    """run() handles subprocess.TimeoutExpired → skip Verdict."""
    gate = CoverageGate(pytest_bin="pytest", timeout=0.1)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=0.1)):
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "超时" in verdict.message


def test_run_subprocess_file_not_found(tmp_path: Path) -> None:
    """run() handles FileNotFoundError → skip Verdict."""
    gate = CoverageGate(pytest_bin="pytest")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "pytest 命令未找到" in verdict.message


# ============================================================
# Group 5: run() — coverage threshold (TOTAL line matching)
# ============================================================


def test_run_coverage_above_threshold(tmp_path: Path) -> None:
    """run() with coverage ≥ threshold → Verdict.passed."""
    gate = CoverageGate(pytest_bin="pytest", threshold=80.0)
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        # Simulate pytest-cov output with 92% coverage
        mock_result.stdout = (
            "Name                     Stmts   Miss  Cover\n"
            "----------------------------------------------\n"
            "my_module.py               100     8     92%\n"
            "TOTAL                      500    40     92%\n"
        )
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "92.0%" in verdict.message
        assert "≥" in verdict.message


def test_run_coverage_below_threshold_non_strict(tmp_path: Path) -> None:
    """run() with coverage < threshold and strict=False → passed with warn."""
    gate = CoverageGate(pytest_bin="pytest", threshold=90.0, strict=False)
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = (
            "TOTAL                      500   250     50%\n"
        )
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "warn" in verdict.message.lower()
        assert "50.0%" in verdict.message


def test_run_coverage_below_threshold_strict(tmp_path: Path) -> None:
    """run() with coverage < threshold and strict=True → Verdict.failed."""
    gate = CoverageGate(pytest_bin="pytest", threshold=90.0, strict=True)
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = (
            "TOTAL                      500   250     50%\n"
        )
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "50.0%" in verdict.message
        assert "<" in verdict.message


def test_run_no_pytest_bin_skip(tmp_path: Path) -> None:
    """run() with no pytest at all → skip verdict."""
    gate = CoverageGate()
    with patch.object(gate, "_resolve_pytest_cmd", return_value=None):
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "skip" in verdict.message.lower()


# ============================================================
# Group 6: constructor defaults
# ============================================================


def test_default_constructor_values() -> None:
    """CoverageGate default constructor values."""
    from auto_engineering.gates.coverage import (
        DEFAULT_THRESHOLD,
        DEFAULT_COV_TARGET,
        DEFAULT_TIMEOUT,
    )
    gate = CoverageGate()
    assert gate.threshold == DEFAULT_THRESHOLD
    assert gate.cov_target == DEFAULT_COV_TARGET
    assert gate.timeout == DEFAULT_TIMEOUT
    assert gate.strict is False
    assert gate.pytest_bin is None
    assert gate.name == "coverage"
    assert gate.applies_to_stages == ("developer",)


def test_custom_constructor_values() -> None:
    """CoverageGate with custom values."""
    gate = CoverageGate(
        threshold=90.0,
        cov_target="my_package",
        pytest_bin="/usr/bin/pytest",
        timeout=60.0,
        strict=True,
    )
    assert gate.threshold == 90.0
    assert gate.cov_target == "my_package"
    assert gate.pytest_bin == "/usr/bin/pytest"
    assert gate.timeout == 60.0
    assert gate.strict is True


# ============================================================
# Group 7: TOTAL_COV_RE regex
# ============================================================


def test_total_cov_re_matches() -> None:
    """_TOTAL_COV_RE matches pytest-cov TOTAL line."""
    line = "TOTAL                      4021    484    88%"
    match = _TOTAL_COV_RE.search(line)
    assert match is not None
    assert match.group(1) == "88"


def test_total_cov_re_100_percent() -> None:
    """_TOTAL_COV_RE matches 100%."""
    line = "TOTAL                      100      0   100%"
    match = _TOTAL_COV_RE.search(line)
    assert match is not None
    assert match.group(1) == "100"


def test_total_cov_re_no_match() -> None:
    """_TOTAL_COV_RE does not match non-TOTAL lines."""
    line = "my_module.py               100      8    92%"
    match = _TOTAL_COV_RE.search(line)
    assert match is None
