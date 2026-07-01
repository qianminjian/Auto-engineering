"""v5.0 Phase 08 — Init-Loop 接口契约 (Loop 侧) 测试.

设计来源: design/v5.0-Design-Loop.md §IL.1-IL.6

EARS 验收条件 (IL.6):
    IL-AC-01 — When Loop 启动且 .ae-state/init-manifest.json 不存在,
              ae doctor shall 报错并提示运行 Init
    IL-AC-02 — When Loop 启动且 init-manifest.json 存在,
              Loop shall 读取 conventions 并配置对应 Gate
    IL-AC-03 — When Init 写入 tasks.yml 含 B1.3 Task 数据模型未定义的未知字段
              (排除 init_metadata 已知字段), Loop shall 静默忽略
    IL-AC-04 — When Init manifest schema_version < Loop 支持的最低版本,
              Loop shall 拒绝运行
    IL-AC-05 — When Loop 完成, Loop shall 不修改 .ae-state/init-manifest.json

测试覆盖:
    - test_il_ac_01_missing_manifest_returns_error
    - test_il_ac_02_manifest_conventions_to_gates
    - test_il_ac_03_unknown_field_silently_ignored
    - test_il_ac_04_old_schema_version_rejected
    - test_il_ac_05_manifest_mtime_unchanged_after_run
    - test_load_init_manifest_success
    - test_validate_init_manifest_missing_required_fields
    - test_validate_init_manifest_unsupported_language
    - test_tasks_yaml_init_metadata_ignored
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ============================================================
# 1. IL-AC-01: 文件缺失 → ✗ + 提示运行 Init
# ============================================================


def test_il_ac_01_missing_manifest_returns_error(tmp_path: Path) -> None:
    """IL-AC-01: 缺失 init-manifest.json → ae doctor 报错."""
    from auto_engineering.cli.doctor import _check_init_manifest
    from auto_engineering.loop.init_contract import load_init_manifest

    # 验证 load_init_manifest 在缺失时返回 None
    assert load_init_manifest(tmp_path) is None

    # 验证 ae doctor 检查项返回 (False, "...")
    ok, message = _check_init_manifest(tmp_path)
    assert ok is False
    assert "init-manifest" in message.lower() or "init engineering" in message.lower()


# ============================================================
# 2. IL-AC-02: conventions 替换默认 Gate 配置
# ============================================================


def test_il_ac_02_manifest_conventions_to_gates(tmp_path: Path) -> None:
    """IL-AC-02: init-manifest.json 的 conventions 配置替换默认 Gate."""
    from auto_engineering.loop.init_contract import (
        get_gate_tools_from_manifest,
        load_init_manifest,
        validate_init_manifest,
    )

    manifest_path = tmp_path / ".ae-state" / "init-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_type": "app-service",
                "language": "python",
                "framework": "fastapi",
                "created_at": "2026-06-30T10:00:00Z",
                "init_version": "1.0.0",
                "structure": {
                    "source_root": "src/",
                    "test_root": "tests/",
                    "config_files": ["pyproject.toml"],
                    "entry_point": "src/main.py",
                },
                "conventions": {
                    "package_manager": "uv",
                    "linter": "ruff",
                    "type_checker": "pyright",
                    "test_runner": "pytest",
                    "build_cmd": "uv build",
                    "test_cmd": "pytest tests/ -v",
                    "lint_cmd": "ruff check src/",
                    "type_check_cmd": "pyright src/",
                },
            }
        )
    )

    manifest = load_init_manifest(tmp_path)
    assert manifest is not None

    result = validate_init_manifest(manifest)
    assert result.ok is True, f"validation errors: {result.errors}"

    tools = get_gate_tools_from_manifest(manifest)
    assert tools["linter"] == "ruff"
    assert tools["type_checker"] == "pyright"
    assert tools["test_runner"] == "pytest"


# ============================================================
# 3. IL-AC-03: 未知字段静默忽略 (WARN log, 不阻断)
# ============================================================


def test_il_ac_03_unknown_field_silently_ignored(tmp_path: Path) -> None:
    """IL-AC-03: 未知字段静默忽略, 不阻断 (WARN log)."""
    from auto_engineering.loop.init_contract import (
        validate_init_manifest,
    )

    manifest = {
        "schema_version": "1.0",
        "project_type": "app-service",
        "language": "python",
        "framework": "fastapi",
        "created_at": "2026-06-30T10:00:00Z",
        "init_version": "1.0.0",
        # 未来 Init 写入的未知字段
        "future_feature_x": {"nested": "data"},
        "experimental_flag": True,
        "structure": {
            "source_root": "src/",
            "test_root": "tests/",
            "config_files": ["pyproject.toml"],
            "entry_point": "src/main.py",
        },
        "conventions": {
            "package_manager": "uv",
            "linter": "ruff",
            "type_checker": "pyright",
            "test_runner": "pytest",
        },
    }
    result = validate_init_manifest(manifest)
    # 未知字段不阻断, 但有 WARN
    assert result.ok is True
    # 至少一条 WARN 关于未知字段
    assert any("unknown" in w.lower() or "future" in w.lower() for w in result.warnings)


# ============================================================
# 4. IL-AC-04: 旧版 schema_version 拒绝
# ============================================================


def test_il_ac_04_old_schema_version_rejected() -> None:
    """IL-AC-04: schema_version < 1.0 → 拒绝 + 重新 Init 提示."""
    from auto_engineering.loop.init_contract import (
        INIT_MANIFEST_SCHEMA_VERSION,
        validate_init_manifest,
    )

    manifest = {
        "schema_version": "0.9",
        "project_type": "app-service",
        "language": "python",
        "structure": {
            "source_root": "src/",
            "test_root": "tests/",
            "config_files": [],
            "entry_point": "src/main.py",
        },
        "conventions": {
            "linter": "ruff",
            "type_checker": "pyright",
            "test_runner": "pytest",
        },
    }
    result = validate_init_manifest(manifest)
    assert result.ok is False
    assert any(
        "schema_version" in e or "0.9" in e or "reinit" in e.lower() or "重新" in e
        for e in result.errors
    )
    # 当前 schema version 是 1.0
    assert INIT_MANIFEST_SCHEMA_VERSION == "1.0"


# ============================================================
# 5. IL-AC-05: Loop 运行后 init-manifest.json mtime 不变
# ============================================================


def test_il_ac_05_manifest_mtime_unchanged_after_run(tmp_path: Path) -> None:
    """IL-AC-05: 调 validate/load 后 init-manifest.json mtime 不变."""
    from auto_engineering.loop.init_contract import (
        load_init_manifest,
        validate_init_manifest,
    )

    manifest_path = tmp_path / ".ae-state" / "init-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_type": "app-service",
                "language": "python",
                "framework": "fastapi",
                "created_at": "2026-06-30T10:00:00Z",
                "init_version": "1.0.0",
                "structure": {
                    "source_root": "src/",
                    "test_root": "tests/",
                    "config_files": ["pyproject.toml"],
                    "entry_point": "src/main.py",
                },
                "conventions": {
                    "package_manager": "uv",
                    "linter": "ruff",
                    "type_checker": "pyright",
                    "test_runner": "pytest",
                },
            }
        )
    )
    mtime_before_ns = manifest_path.stat().st_mtime_ns

    # 多次调用 load + validate
    manifest = load_init_manifest(tmp_path)
    assert manifest is not None
    for _ in range(5):
        result = validate_init_manifest(manifest)
        assert result.ok is True

    mtime_after_ns = manifest_path.stat().st_mtime_ns
    assert mtime_before_ns == mtime_after_ns, (
        f"init-manifest.json mtime changed: {mtime_before_ns} -> {mtime_after_ns}"
    )


# ============================================================
# 6. load_init_manifest 基础: 正常路径
# ============================================================


def test_load_init_manifest_success(tmp_path: Path) -> None:
    """load_init_manifest: 存在 + 合法 JSON → 返回 dict."""
    from auto_engineering.loop.init_contract import load_init_manifest

    manifest_path = tmp_path / ".ae-state" / "init-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    expected = {"schema_version": "1.0", "project_type": "app-service"}
    manifest_path.write_text(json.dumps(expected))

    result = load_init_manifest(tmp_path)
    assert result == expected


# ============================================================
# 7. validate_init_manifest 缺失必需字段
# ============================================================


def test_validate_init_manifest_missing_required_fields() -> None:
    """validate_init_manifest: 缺 project_type/language/conventions → ✗."""
    from auto_engineering.loop.init_contract import validate_init_manifest

    manifest = {
        "schema_version": "1.0",
        "project_type": "app-service",
        # 缺 language
        "structure": {
            "source_root": "src/",
            "test_root": "tests/",
        },
        "conventions": {
            "linter": "ruff",
            "type_checker": "pyright",
            "test_runner": "pytest",
        },
    }
    result = validate_init_manifest(manifest)
    assert result.ok is False
    assert any("language" in e for e in result.errors)


# ============================================================
# 8. validate_init_manifest language 不在 enum
# ============================================================


def test_validate_init_manifest_unsupported_language() -> None:
    """validate_init_manifest: language=cpp (不支持) → ✗ + 列支持值."""
    from auto_engineering.loop.init_contract import validate_init_manifest

    manifest = {
        "schema_version": "1.0",
        "project_type": "app-service",
        "language": "cpp",  # 不在 5 语言 enum
        "structure": {
            "source_root": "src/",
            "test_root": "tests/",
        },
        "conventions": {
            "linter": "clang-tidy",
            "type_checker": "clang",
            "test_runner": "gtest",
        },
    }
    result = validate_init_manifest(manifest)
    assert result.ok is False
    assert any("language" in e or "cpp" in e for e in result.errors)


# ============================================================
# 9. tasks.yml init_metadata 字段静默忽略 (IL-AC-03 跨 §IL.3)
# ============================================================


def test_tasks_yaml_init_metadata_ignored() -> None:
    """tasks.yml 含 init_metadata + B1.3 未定义字段 → Plan.validate() 不报错."""
    from auto_engineering.loop.plan import Plan, Task

    # tasks.yml 含 init_metadata 已知扩展字段 + 完全未知的字段
    task_with_unknown = Task(
        id="init-data-models",
        title="Create SQLAlchemy data models",
        description="Create models",
        expected_output="models.py",
        role="developer",
        depends_on=[],
        target_files=frozenset({"src/models.py"}),
    )
    # 模拟 tasks.yml 解析时附带的 init_metadata 字段 (用 __dict__ 注入)
    task_with_unknown.__dict__["init_metadata"] = {
        "template_source": "app-service/python/fastapi/models.py.jinja",
        "generated_by": "init-engineering 1.0.0",
    }
    task_with_unknown.__dict__["future_unknown_field"] = {"foo": "bar"}

    plan = Plan(
        tasks=[task_with_unknown],
        requirement="Create models",
    )
    # 不抛异常 = 静默忽略成功
    plan.validate()


# ============================================================
# 辅助: sanity check (确认 init_contract 模块存在)
# ============================================================


def test_init_contract_module_imports() -> None:
    """Sanity: init_contract 模块可被导入."""
    from auto_engineering.loop import init_contract

    assert hasattr(init_contract, "load_init_manifest")
    assert hasattr(init_contract, "validate_init_manifest")
    assert hasattr(init_contract, "get_gate_tools_from_manifest")
    assert hasattr(init_contract, "INIT_MANIFEST_SCHEMA_VERSION")
    assert hasattr(init_contract, "SUPPORTED_PROJECT_TYPES")
    assert hasattr(init_contract, "SUPPORTED_LANGUAGES")
    assert hasattr(init_contract, "LANGUAGE_TOOLS")
