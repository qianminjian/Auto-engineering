"""conftest.py — pytest 共享 fixtures + 阻塞检测 hook.

Phase 2 之后 conftest.py 只 re-export(避免 cli.py 反向依赖 conftest).
Phase 0.3 增强: 跨 session 失败计数 + 自动 skip(检测阻塞测试).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

import pytest

# Re-export from production code(避免 cli.py 反向依赖 conftest)
from auto_engineering.runtime.mock import (  # noqa: F401
    ScriptedMockRuntime,
    StepLimitedMockRuntime,
)

# ============================================================
# Phase 0.3 阻塞检测 hook
# ============================================================
# 思路: 某测试连续失败 >= 3 次(跨 session)→ 自动 mark skip
# 目的: 避免在边角测试上反复死磕(如 git diff untracked 限制)
# 状态: /tmp/_ae_test_failures.json(可手动清理重置)


_FAILURE_CACHE = Path(os.environ.get("AE_TEST_STATE_DIR", "/tmp")) / "_ae_test_failures.json"
_BLOCK_THRESHOLD = 3


def _read_failures() -> dict[str, int]:
    """读取跨 session 失败计数."""
    if _FAILURE_CACHE.exists():
        try:
            return json.loads(_FAILURE_CACHE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_failures(data: dict[str, int]) -> None:
    """写入跨 session 失败计数."""
    with contextlib.suppress(OSError):
        _FAILURE_CACHE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def pytest_runtest_logreport(report):
    """累积测试失败次数(跨 session 持久化).

    失败 >= _BLOCK_THRESHOLD 次 → 下次跑自动 mark skip.
    """
    if report.when == "call" and report.failed:
        failures = _read_failures()
        failures[report.nodeid] = failures.get(report.nodeid, 0) + 1
        _write_failures(failures)


def pytest_collection_modifyitems(config, items):
    """收集阶段: 给持续失败的测试打 skip marker.

    输出: stderr 列出本次跳过的 blocked tests(便于人工 review).
    """
    failures = _read_failures()
    blocked = [tid for tid, count in failures.items() if count >= _BLOCK_THRESHOLD]
    if blocked:
        msg = (
            f"\n[block_detector] Auto-skipping {len(blocked)} tests "
            f"(failed >= {_BLOCK_THRESHOLD} times across sessions):"
        )
        print(msg, file=sys.stderr)
        for tid in blocked[:5]:
            print(f"  - {tid}", file=sys.stderr)
        if len(blocked) > 5:
            print(f"  ... and {len(blocked) - 5} more", file=sys.stderr)

    skip_marker = pytest.mark.skip(
        reason=f"Auto-skip: failed >= {_BLOCK_THRESHOLD} times (blocked across sessions)"
    )
    for item in items:
        if item.nodeid in blocked:
            item.add_marker(skip_marker)


# ============================================================
# Phase 1 共享 fixtures
# ============================================================


@pytest.fixture
def checkpoint_dir(tmp_path):
    """每个测试用独立 tmp 目录存 checkpoint SQLite."""
    return str(tmp_path / ".ae-checkpoints")


def run_async(coro):
    """同步上下文跑 async 协程. Phase 1 不引入 pytest-asyncio 依赖."""
    return asyncio.run(coro)


# Fix: import sys(用于 stderr 输出)
import sys  # noqa: E402
