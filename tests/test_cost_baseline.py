from __future__ import annotations

import pytest

from auto_engineering.metrics.cost_baseline import (
    CostBaselineError,
    CostSnapshot,
    compare_costs,
)


def _snapshot(**overrides: object) -> CostSnapshot:
    values = {
        "fixture": "long-run-v1",
        "host": "claude-code",
        "model": "sonnet",
        "completed_work_units": 10,
        "input_units": 1000,
        "cache_read_units": 2000,
        "cache_write_units": 100,
        "output_units": 100,
        "core_payload_bytes": 5000,
        "duplicate_block_bytes": 0,
        "measurement_complete": True,
    }
    values.update(overrides)
    return CostSnapshot(**values)  # type: ignore[arg-type]


def test_cost_comparison_is_normalized_by_completed_work() -> None:
    result = compare_costs(
        _snapshot(),
        _snapshot(
            completed_work_units=20,
            input_units=1800,
            cache_read_units=3600,
            cache_write_units=180,
            core_payload_bytes=9000,
        ),
    )
    assert result["passed"] is True


def test_duplicate_blocks_fail_cost_gate() -> None:
    result = compare_costs(_snapshot(), _snapshot(duplicate_block_bytes=1))
    assert result["passed"] is False
    assert "duplicate_block_bytes" in result["regressions"]


def test_incomplete_or_incompatible_measurements_fail_closed() -> None:
    with pytest.raises(CostBaselineError, match="measurement_incomplete"):
        compare_costs(_snapshot(), _snapshot(measurement_complete=False))
    with pytest.raises(CostBaselineError, match="禁止伪比较"):
        compare_costs(_snapshot(), _snapshot(model="other"))
