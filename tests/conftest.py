"""conftest.py — pytest 共享 fixtures + 持续失败诊断 hook.

Phase 2 之后 conftest.py 只 re-export(避免 cli.py 反向依赖 conftest).
Phase 50: 跨 session 失败计数只用于诊断，不得自动跳过测试。

WARNING: 本文件含跨 session 持久化 hook (pytest_runtest_logreport), 写入
/tmp/_ae_test_failures.json 做失败计数；该状态不得改变测试执行语义。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

import pytest

# v2.0-only: MockRuntime 已删除 (v1.0 移除).
# 测试需要 mock agent 时直接用 unittest.mock.MagicMock.

# ============================================================
# Phase 0.3 持续失败诊断 hook
# ============================================================
# 某测试连续失败 >= 3 次时前台报告，仍必须真实执行，禁止掩盖回归。


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
    """累积测试失败次数，供跨 session 诊断。"""
    if report.when == "call" and report.failed:
        failures = _read_failures()
        failures[report.nodeid] = failures.get(report.nodeid, 0) + 1
        _write_failures(failures)


def pytest_collection_modifyitems(config, items):
    """收集阶段报告持续失败测试，但不改变其执行语义。"""
    failures = _read_failures()
    blocked = [tid for tid, count in failures.items() if count >= _BLOCK_THRESHOLD]
    if blocked:
        msg = (
            f"\n[block_detector] Reporting {len(blocked)} persistently failing tests "
            f"(failed >= {_BLOCK_THRESHOLD} times across sessions; tests will run):"
        )
        print(msg, file=sys.stderr)
        for tid in blocked[:5]:
            print(f"  - {tid}", file=sys.stderr)
        if len(blocked) > 5:
            print(f"  ... and {len(blocked) - 5} more", file=sys.stderr)

# ============================================================
# Phase 0.3 缓存清理 fixture
# ============================================================
# 场景: 某测试已修好但 cache 中失败计数未清,会被错误地 skip
# 解法: 提供 _reset_block_cache fixture,显式重置 cache


@pytest.fixture
def _reset_block_cache():
    """重置 block detector 失败计数 cache.

    使用场景: 修复了某个被 block 的测试,需要让它从 cache 重新跑(不 skip).
    本 fixture 清理后**只对当前测试生效**,其他测试的 cache 状态保持不变.
    """
    failures = _read_failures()
    saved = dict(failures)  # backup
    _write_failures({})
    yield
    # 恢复原 cache(避免影响其他测试 session)
    _write_failures(saved)


# ============================================================
# Phase 1 共享 fixtures
# ============================================================


@pytest.fixture
def checkpoint_dir(tmp_path):
    """每个测试用独立 tmp 目录存 checkpoint SQLite."""
    return str(tmp_path / ".ae-state")


def run_async(coro):
    """同步上下文跑 async 协程. Phase 1 不引入 pytest-asyncio 依赖."""
    return asyncio.run(coro)


# 2026-07-04 (v5.0 深度审计 P1-S-01): fail-CLOSED 是新默认行为.
# 测试场景默认不期望走严格沙箱 (除非明确测沙箱, 如 test_tool_sandbox.py).
# autouse fixture 自动设 ALLOW_NO_SANDBOX=true 旁路, 避免每个测试显式声明.
# Phase 45: AE_SKIP_CONFIG_CHECK=1 跳过 ae.toml 配置闸门（测试环境无 ae.toml）
@pytest.fixture(autouse=True)
def _allow_no_sandbox_default(monkeypatch):
    """所有测试默认 ALLOW_NO_SANDBOX=true (fail-CLOSED 旁路).

    test_tool_sandbox.py 内的 fail-CLOSED 测试显式 monkeypatch.delenv
    撤销此 fixture 的设值, 验证默认行为.
    """
    monkeypatch.setenv("ALLOW_NO_SANDBOX", "true")
    monkeypatch.setenv("AE_SKIP_CONFIG_CHECK", "1")
    yield


# P0-6: Reset RuntimeConfig sentinel between tests so monkeypatch.setenv() works.
# Without this, a test that calls set_default_config() would leak its config to
# subsequent tests, making their monkeypatch.env changes invisible.
@pytest.fixture(autouse=True)
def _reset_runtime_config_sentinel():
    from auto_engineering.config.runtime_config import _SENTINEL as _sentinel_ref
    # Save and clear
    saved = _sentinel_ref
    import auto_engineering.config.runtime_config as _rc_mod
    _rc_mod._SENTINEL = None
    yield
    # Restore (in case the test itself set it)
    _rc_mod._SENTINEL = saved


# P1-19: Reset module-level singletons between tests to prevent cross-test pollution.
@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """Reset _collector, _DEFAULT_REGISTRY, _STRICT_RED between tests."""
    import auto_engineering.loop.guardrails.stateful as _gs
    import auto_engineering.metrics.collector as _mc
    import auto_engineering.pii.redactor as _pii
    import auto_engineering.prompts.registry as _pr

    saved_collector = _mc._collector
    saved_registry = _pr._DEFAULT_REGISTRY
    saved_strict_red = _gs._STRICT_RED
    saved_pii = _pii._pii_redactor_singleton

    _mc._collector = None
    _pr._DEFAULT_REGISTRY = None
    _gs._STRICT_RED = None
    _pii._pii_redactor_singleton = None

    yield

    _mc._collector = saved_collector
    _pr._DEFAULT_REGISTRY = saved_registry
    _gs._STRICT_RED = saved_strict_red
    _pii._pii_redactor_singleton = saved_pii


# Fix: import sys(用于 stderr 输出)
import sys  # noqa: E402
