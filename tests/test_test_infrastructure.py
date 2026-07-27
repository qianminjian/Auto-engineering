"""测试基础设施不得掩盖真实失败。"""

from __future__ import annotations

from tests import conftest


class _FakeItem:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.markers: list[object] = []

    def add_marker(self, marker: object) -> None:
        self.markers.append(marker)


def test_failure_history_never_adds_skip_marker(tmp_path, monkeypatch) -> None:
    """累计失败只用于诊断，不能改变下一次测试的执行语义。"""
    failure_cache = tmp_path / "failures.json"
    monkeypatch.setattr(conftest, "_FAILURE_CACHE", failure_cache)
    conftest._write_failures({"tests/test_demo.py::test_demo": 3})
    item = _FakeItem("tests/test_demo.py::test_demo")

    conftest.pytest_collection_modifyitems(None, [item])

    assert item.markers == []
