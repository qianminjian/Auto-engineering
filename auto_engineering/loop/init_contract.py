"""v5.0 Phase 08 — Init-Loop 接口契约 (Loop 侧实现).

设计来源: design/v5.0-Design-Loop.md §IL.1-IL.6.

核心组件:
    INIT_MANIFEST_SCHEMA_VERSION  — 当前支持的 init-manifest schema 版本
    SUPPORTED_PROJECT_TYPES        — 8 个 project_type enum 合法值
    SUPPORTED_LANGUAGES            — 5 个 language enum 合法值
    LANGUAGE_TOOLS                 — 5 语言默认 Gate 工具映射
    ValidationResult               — validate 结果数据类 (ok / errors / warnings)
    load_init_manifest             — 读 .ae-state/init-manifest.json
    validate_init_manifest         — 校验 manifest 内容 (IL-AC-01~05)
    get_gate_tools_from_manifest   — 从 conventions 提取 linter/type_checker/test_runner

约束:
    - Loop 是 Init 的消费者, 不主动调用 Init (v5.0 §IL.4)
    - init-manifest.json 不被 Loop 修改 (IL-AC-05: read-only)
    - 未知字段静默忽略 (IL-AC-03, forward-compat)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# ============================================================
# 常量 (v5.0 §IL.2 enum 合法值)
# ============================================================

# 当前 Loop 侧最低 + 最高支持的 schema_version.
# 最低: < 1.0 拒绝 (IL-AC-04). 最高: > 9.9 WARN forward-compat.
INIT_MANIFEST_SCHEMA_VERSION: str = "1.0"
INIT_MANIFEST_MIN_VERSION: tuple[int, ...] = (1, 0)
INIT_MANIFEST_MAX_VERSION: tuple[int, ...] = (9, 9)  # 软上限: 超过则 WARN

# 8 个 project_type (v5.0 §IL.2)
SUPPORTED_PROJECT_TYPES: frozenset[str] = frozenset(
    {
        "app-service",
        "library",
        "cli-tool",
        "skill",
        "hook",
        "mcp-server",
        "spec-doc",
        "monorepo",
    }
)

# 5 个 language (v5.0 §IL.2)
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "typescript", "go", "rust", "bash"}
)

# 5 语言默认 Gate 工具映射 (v5.0 §IL.2)
# value: (linter, type_checker, test_runner)
LANGUAGE_TOOLS: dict[str, tuple[str, str, str]] = {
    "python": ("ruff", "pyright", "pytest"),
    "typescript": ("eslint", "tsc", "vitest"),
    "go": ("golangci-lint", "go vet", "go test"),
    "rust": ("clippy", "cargo check", "cargo test"),
    "bash": ("shellcheck", "bash -n", "bats"),
}

# 必需字段 (v5.0 §IL.2 字段表)
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "project_type",
        "language",
        "structure",
        "conventions",
    }
)

# 已知字段 (init_metadata 等扩展字段也是"已知" — 静默忽略只针对真未知)
_KNOWN_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "project_type",
        "language",
        "framework",
        "created_at",
        "init_version",
        "structure",
        "conventions",
        "templates_applied",
        "answers",
    }
)


# ============================================================
# ValidationResult (validate_init_manifest 返回值)
# ============================================================


@dataclass
class ValidationResult:
    """validate_init_manifest 校验结果.

    Attributes:
        ok: True = 通过, False = 失败 (含 errors 时)
        errors: 阻断性错误列表 (存在时 ok=False)
        warnings: 非阻断警告 (例如未知字段、schema_version 过高)
    """

    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ============================================================
# 工具函数
# ============================================================


def _parse_version(version_str: str) -> tuple[int, ...]:
    """解析 'X.Y.Z' 形式版本号 → tuple[int, ...]. 解析失败返回 (0,)."""
    parts: list[int] = []
    for chunk in str(version_str).strip().split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def _manifest_path(project_root: Path) -> Path:
    """init-manifest.json 标准路径 = project_root/.ae-state/init-manifest.json."""
    return project_root / ".ae-state" / "init-manifest.json"


# ============================================================
# 1. load_init_manifest
# ============================================================


def load_init_manifest(project_root: Path) -> dict[str, Any] | None:
    """加载 init-manifest.json (v5.0 §IL.2).

    Args:
        project_root: 项目根目录.

    Returns:
        - manifest dict: 文件存在 + JSON 合法.
        - None: 文件不存在 / JSON 解析失败 (调用方需处理).

    约束: 此函数是**只读**的, 不修改文件 mtime (IL-AC-05).
    """
    path = _manifest_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("init-manifest.json 解析失败: %s", e)
        return None
    if not isinstance(data, dict):
        _logger.warning(
            "init-manifest.json 顶层不是 dict, 而是 %s", type(data).__name__
        )
        return None
    return data


# ============================================================
# 2. validate_init_manifest
# ============================================================


def validate_init_manifest(manifest: dict[str, Any]) -> ValidationResult:
    """校验 init-manifest 内容 (v5.0 §IL.2 + §IL.4 + IL-AC-01~05).

    校验项:
        1. schema_version 存在 + 解析成功
        2. schema_version >= INIT_MANIFEST_MIN_VERSION (IL-AC-04)
        3. schema_version <= INIT_MANIFEST_MAX_VERSION → WARN forward-compat
        4. 必需字段缺失 → ✗ (列字段名)
        5. project_type 不在 enum → ✗ (列支持值)
        6. language 不在 enum → ✗ (列支持值)
        7. 未知 top-level 字段 → WARN (IL-AC-03, 不阻断)
        8. conventions.linter/type_checker/test_runner 缺失 → ✗

    Args:
        manifest: load_init_manifest 返回的 dict.

    Returns:
        ValidationResult(ok, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1-3. schema_version 校验
    schema_version = manifest.get("schema_version")
    if not schema_version:
        errors.append("缺少必需字段: schema_version")
    else:
        current = _parse_version(str(schema_version))
        if current < INIT_MANIFEST_MIN_VERSION:
            errors.append(
                f"init-manifest schema_version {schema_version} 不支持 "
                f"(最低 {INIT_MANIFEST_MIN_VERSION[0]}.{INIT_MANIFEST_MIN_VERSION[1]}, "
                f"最高 {INIT_MANIFEST_MAX_VERSION[0]}.{INIT_MANIFEST_MAX_VERSION[1]}), "
                f"请重新 Init"
            )
        elif current > INIT_MANIFEST_MAX_VERSION:
            warnings.append(
                f"init-manifest schema_version {schema_version} 超过 Loop 当前最高支持 "
                f"{INIT_MANIFEST_MAX_VERSION[0]}.{INIT_MANIFEST_MAX_VERSION[1]}, "
                f"forward-compat 模式, 建议升级 Loop"
            )

    # 4. 必需字段
    for field_name in sorted(_REQUIRED_FIELDS):
        if field_name not in manifest:
            errors.append(f"缺少必需字段: {field_name}")

    # 5. project_type enum
    project_type = manifest.get("project_type")
    if project_type and project_type not in SUPPORTED_PROJECT_TYPES:
        errors.append(
            f"project_type '{project_type}' 不支持, 合法值: {sorted(SUPPORTED_PROJECT_TYPES)}"
        )

    # 6. language enum
    language = manifest.get("language")
    if language and language not in SUPPORTED_LANGUAGES:
        errors.append(
            f"language '{language}' 不支持, 合法值: {sorted(SUPPORTED_LANGUAGES)}"
        )

    # 7. 未知 top-level 字段 (IL-AC-03 静默忽略 + WARN)
    unknown_fields = sorted(
        set(manifest.keys()) - _KNOWN_TOP_LEVEL_FIELDS
    )
    if unknown_fields:
        warnings.append(
            f"init-manifest 包含未知字段 (forward-compat 忽略): {unknown_fields}"
        )

    # 8. conventions 必需子字段
    conventions = manifest.get("conventions")
    if isinstance(conventions, dict):
        for sub in ("linter", "type_checker", "test_runner"):
            if sub not in conventions:
                errors.append(f"conventions 缺少必需子字段: {sub}")
    elif "conventions" in manifest:
        # conventions 存在但不是 dict
        errors.append(f"conventions 字段类型错误: 应为 dict, 实际 {type(conventions).__name__}")

    return ValidationResult(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ============================================================
# 3. get_gate_tools_from_manifest
# ============================================================


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
    # 缺 conventions → 用 language 默认
    if not isinstance(conventions, dict):
        return _default_tools_for(language)
    linter = conventions.get("linter")
    type_checker = conventions.get("type_checker")
    test_runner = conventions.get("test_runner")
    # 任一缺 → 用 language 默认填充
    default = _default_tools_for(language)
    return {
        "linter": linter or default[0],
        "type_checker": type_checker or default[1],
        "test_runner": test_runner or default[2],
    }


def _default_tools_for(language: str) -> tuple[str, str, str]:
    """查 LANGUAGE_TOOLS, 不支持则回退 python."""
    return LANGUAGE_TOOLS.get(language, LANGUAGE_TOOLS["python"])


__all__ = [
    "INIT_MANIFEST_SCHEMA_VERSION",
    "LANGUAGE_TOOLS",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_PROJECT_TYPES",
    "ValidationResult",
    "get_gate_tools_from_manifest",
    "load_init_manifest",
    "validate_init_manifest",
]
