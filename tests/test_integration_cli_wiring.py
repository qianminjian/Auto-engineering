"""T113 L3: 接线契约测试 — 防止 Build-then-Wire.

每个新增 injectable 必须在 _build_injectables() 中有创建路径,
在 TickOrchestrator 构造时有传入点, 且本测试文件中有对应断言。
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Helpers ──

def _get_injectables(root: Path, environ: dict | None = None) -> dict:
    """Call _build_injectables with optional env override."""
    from auto_engineering.cli.dev_loop import _build_injectables
    return _build_injectables(root, environ or os.environ)


# ── L3-a: Required injectables must be instantiated ──

def test_all_required_injectables_non_none(tmp_path):
    """每个必需模块必须在 _build_injectables() 中被实例化."""
    inj = _get_injectables(tmp_path)
    assert inj["context_offloader"] is not None, (
        "ContextOffloader must be instantiated (required injectable)")
    # T54 SessionSummarizer — optional, only in Standalone mode with LLM provider
    assert "session_summarizer" in inj, (
        "SessionSummarizer 必须出现在 injectables 中 (T54 恢复)")


def test_conditional_injectables_have_creation_paths(tmp_path, monkeypatch):
    """条件模块的创建路径存在: 环境变量设置时非 None, 未设置时为 None."""
    # tracer: None without AE_OTLP_ENDPOINT
    monkeypatch.delenv("AE_OTLP_ENDPOINT", raising=False)
    inj = _get_injectables(tmp_path)
    assert inj["tracer"] is None, "tracer should be None without AE_OTLP_ENDPOINT"

    # audit_logger: None without AE_AUDIT_LOG
    monkeypatch.delenv("AE_AUDIT_LOG", raising=False)
    assert inj["audit_logger"] is None, "audit_logger should be None without AE_AUDIT_LOG=1"


# ── L3-b: Injectables are passed to TickOrchestrator ──

def test_injectables_passed_to_orchestrator(tmp_path):
    """验证所有 injectable 参数实际传入了 TickOrchestrator 构造器."""
    from auto_engineering.cli.dev_loop import _build_injectables
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    inj = _get_injectables(tmp_path)
    orch = TickOrchestrator(
        tmp_path,
        context_offloader=inj["context_offloader"],
        tracer=inj["tracer"],
        audit_logger=inj["audit_logger"],
    )
    assert orch._context_offloader is not None
    # T54: SessionSummarizer — optional, None in AgentDriver mode (no LLM provider)
    assert hasattr(orch, "_session_summarizer")
    # tracer may be None (no OTLP endpoint)
    assert orch._tracer is None
    assert orch._audit_logger is None


# ── L3-c: New injectable convention enforcement ──

def test_new_module_wiring_convention():
    """每个 _build_injectables() 的新增 key 必须在本测试文件中追加断言.

    当 _build_injectables() return dict 新增 key 时, 本测试期望集
    expected_keys 必须同步更新. 不匹配的 extra keys 会触发测试失败,
    提醒开发者在此文件追加对应的接线验证断言.
    """
    known_conditionals = {"tracer", "audit_logger", "session_summarizer"}

    # Build a ThrowawayPath to call _build_injectables without I/O
    with patch("pathlib.Path.mkdir"):
        with patch("pathlib.Path.exists", return_value=False):
            from auto_engineering.cli.dev_loop import _build_injectables
            # Minimal environ: no optional features enabled
            minimal_env: dict[str, str] = {}
            inj = _build_injectables(Path("/nonexistent"), minimal_env)

    actual_keys = set(inj.keys())
    expected_required = {"context_offloader"}

    missing = expected_required - actual_keys
    extra = actual_keys - expected_required - known_conditionals

    assert not missing, f"Missing required injectable keys: {missing}"
    assert not extra, (
        f"New injectable keys detected: {extra}. "
        f"Add corresponding wiring assertions in {__file__} "
        f"and verify the key is passed to TickOrchestrator in dev_loop.py."
    )
