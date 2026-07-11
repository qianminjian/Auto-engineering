"""v5.5 P1-1 — 语言默认工具映射 (从 registry.py 提取, 消除循环依赖).

单向依赖: _tools ← 无 gates/ 内部 import → 被 lint/test_gate/type_check/registry 引用.
"""

from __future__ import annotations

from typing import Any

__all__ = ["LANGUAGE_TOOLS", "get_gate_tools_from_manifest"]

LANGUAGE_TOOLS: dict[str, tuple[str, str, str]] = {
    "python": ("ruff", "pyright", "pytest"),
    "typescript": ("eslint", "tsc", "vitest"),
    "go": ("golangci-lint", "go vet", "go test"),
    "rust": ("clippy", "cargo check", "cargo test"),
    "bash": ("shellcheck", "bash -n", "bats"),
}


def _default_tools_for(language: str) -> tuple[str, str, str]:
    """查 LANGUAGE_TOOLS, 不支持则回退 python."""
    return LANGUAGE_TOOLS.get(language, LANGUAGE_TOOLS["python"])


def get_gate_tools_from_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    """从 init-manifest conventions 提取 Gate 工具配置 (v5.0 §IL-AC-02).

    Args:
        manifest: load_init_manifest 返回的 dict.

    Returns:
        {"linter": str, "type_checker": str, "test_runner": str}
        - 若 conventions 缺失, 回退到 language 默认工具 (LANGUAGE_TOOLS)
        - 若 language 也不支持, 用 python 默认 (向后兼容)
    """
    conventions = manifest.get("conventions")
    language = manifest.get("language", "python")
    if not isinstance(conventions, dict):
        return dict(zip(("linter", "type_checker", "test_runner"), _default_tools_for(language), strict=True))
    linter = conventions.get("linter")
    type_checker = conventions.get("type_checker")
    test_runner = conventions.get("test_runner")
    default = _default_tools_for(language)
    return {
        "linter": linter or default[0],
        "type_checker": type_checker or default[1],
        "test_runner": test_runner or default[2],
    }
