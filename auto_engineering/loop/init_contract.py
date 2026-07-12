"""v5.0 Phase 08 — Init-Loop 接口契约 (Loop 侧实现).

设计来源: design/v5.6-Design-Loop.md §IL.1-IL.6.

核心组件:
    INIT_MANIFEST_SCHEMA_VERSION  — 当前支持的 init-manifest schema 版本
    SUPPORTED_PROJECT_TYPES        — 8 个 project_type enum 合法值
    SUPPORTED_LANGUAGES            — 5 个 language enum 合法值
    LANGUAGE_TOOLS                 — 5 语言默认 Gate 工具映射 (re-exported from gates.registry)
    ValidationResult               — validate 结果数据类 (ok / errors / warnings)
    load_init_manifest             — 读 .ae-state/init-manifest.json
    validate_init_manifest         — 校验 manifest 内容 (IL-AC-01~05)
    get_gate_tools_from_manifest   — 从 manifest 提取 Gate 工具配置 (re-exported from gates.registry)
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

# v5.4 审计 r3 P1-1: LANGUAGE_TOOLS / get_gate_tools_from_manifest 已迁移到 gates.registry,
# 此处 re-export 保持向后兼容. 新代码请直接从 gates.registry import.
from auto_engineering.gates.registry import (  # noqa: E402
    LANGUAGE_TOOLS,
    get_gate_tools_from_manifest,
)

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


from auto_engineering.utils import parse_version as _parse_version

# T32: JSON Schema SSOT (IL-AC-06). 与 init-manifest.schema.json 同目录.
INIT_MANIFEST_SCHEMA_PATH: Path = Path(__file__).resolve().parent / "init-manifest.schema.json"


def _load_schema() -> dict[str, Any] | None:
    """加载 init-manifest JSON Schema. 文件缺失/损坏 → None."""
    try:
        return json.loads(INIT_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("无法加载 init-manifest schema: %s", e)
        return None


def _jsonschema_lib() -> Any | None:
    """返回 jsonschema 库或 None (未安装时)."""
    try:
        import jsonschema  # type: ignore[import-untyped]
        return jsonschema
    except ImportError:
        return None


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


def validate_against_schema(manifest: dict[str, Any]) -> ValidationResult:
    """T32: 用 JSON Schema 校验 manifest (IL-AC-06).

    jsonschema 库未安装时返回 ok=True (graceful degrade, 后续手工校验补位).
    仅捕获 schema 校验层面的问题: 缺必需字段 / 类型错误 / enum 失败.
    """
    errors: list[str] = []
    schema = _load_schema()
    if schema is None:
        msg = "schema file missing, skipping schema validation"
        return ValidationResult(ok=True, warnings=[msg])
    jsonschema = _jsonschema_lib()
    if jsonschema is None:
        msg = "jsonschema not installed, skipping schema validation"
        return ValidationResult(ok=True, warnings=[msg])
    try:
        jsonschema.validate(instance=manifest, schema=schema)
    except jsonschema.ValidationError as e:
        errors.append(f"schema 校验失败: {e.message}")
    except Exception as e:
        _logger.warning("schema 校验异常: %s", e)
        return ValidationResult(ok=True, warnings=[f"schema validation error: {e}"])
    return ValidationResult(ok=len(errors) == 0, errors=errors)


def validate_init_manifest(manifest: dict[str, Any]) -> ValidationResult:
    """校验 init-manifest 内容 (v5.0 §IL.2 + §IL.4 + IL-AC-01~06).

    T32: 先跑 JSON Schema (IL-AC-06), 再跑手工校验 (IL-AC-01~05).

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

    # T32: JSON Schema 校验先跑 (IL-AC-06)
    schema_result = validate_against_schema(manifest)
    errors.extend(schema_result.errors)
    warnings.extend(schema_result.warnings)

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

    # T34: monorepo → 单包降级 WARN (IL-AC-08). 枚举保留, 多包沙箱 YAGNI 推迟.
    if project_type == "monorepo":
        warnings.append(
            "project_type=monorepo: single-package degrade mode. "
            "Multi-package sandbox isolation deferred (YAGNI). "
            "source_root/test_root treated as main package root."
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
# T33 — conventions.ci_platform + structure.design_root (IL-AC-08)
# ============================================================

_VALID_CI_PLATFORMS: frozenset[str] = frozenset({"github", "gitlab", "none"})


def get_ci_platform_from_manifest(manifest: dict[str, Any]) -> str | None:
    """T33: 从 manifest.conventions.ci_platform 提取 CI 平台.

    仅返回 schema 定义的合法值 (github/gitlab/none), 其他返回 None.
    """
    conventions = manifest.get("conventions")
    if not isinstance(conventions, dict):
        return None
    val = conventions.get("ci_platform")
    if isinstance(val, str) and val in _VALID_CI_PLATFORMS:
        return val
    return None


def get_design_root_from_manifest(manifest: dict[str, Any]) -> str:
    """T33: 从 manifest.structure.design_root 提取设计文档目录.

    缺省返回 "design/" (约定优于配置).
    """
    structure = manifest.get("structure")
    if isinstance(structure, dict):
        val = structure.get("design_root")
        if isinstance(val, str) and val.strip():
            return val
    return "design/"


# v5.4 审计 r3 P1-1: get_gate_tools_from_manifest 已迁移到 gates.registry,
# 此处 re-export (见文件顶部 import). 函数体不再重复定义.


__all__ = [
    "INIT_MANIFEST_SCHEMA_PATH",
    "INIT_MANIFEST_SCHEMA_VERSION",
    "LANGUAGE_TOOLS",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_PROJECT_TYPES",
    "ValidationResult",
    "get_ci_platform_from_manifest",
    "get_design_root_from_manifest",
    "get_gate_tools_from_manifest",
    "load_init_manifest",
    "validate_against_schema",
    "validate_init_manifest",
]
