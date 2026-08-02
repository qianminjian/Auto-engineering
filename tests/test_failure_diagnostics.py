"""持续失败诊断缓存的确定性行为。"""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace


def _load_conftest() -> dict[str, object]:
    return runpy.run_path(Path(__file__).with_name("conftest.py"))


def test_successful_test_clears_stale_failure_count(tmp_path) -> None:
    conftest = _load_conftest()

    cache = tmp_path / "failures.json"
    conftest["_FAILURE_CACHE"] = cache
    conftest["_write_failures"]({"tests/test_example.py::test_case": 4})

    conftest["pytest_runtest_logreport"](
        SimpleNamespace(
            when="call",
            nodeid="tests/test_example.py::test_case",
            failed=False,
            passed=True,
        )
    )

    assert conftest["_read_failures"]() == {}


def test_failed_test_increments_failure_count(tmp_path) -> None:
    conftest = _load_conftest()

    cache = tmp_path / "failures.json"
    conftest["_FAILURE_CACHE"] = cache
    conftest["_write_failures"]({"tests/test_example.py::test_case": 1})

    conftest["pytest_runtest_logreport"](
        SimpleNamespace(
            when="call",
            nodeid="tests/test_example.py::test_case",
            failed=True,
            passed=False,
        )
    )

    assert conftest["_read_failures"]() == {"tests/test_example.py::test_case": 2}
