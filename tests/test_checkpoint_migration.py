"""Phase 14.3 (P2-3): CheckpointEnvelope schema_version 迁移测试.

测试范围:
  - migrate_envelope: 4 条路径 (1.0 pass-through / 0.9→1.0 / <0.9 reject / no version)
  - validate_envelope: 合法/非法 envelope 判定
  - 边界: 额外字段保留 / 幂等 / 未来版本拒绝 / 类型错误

设计原则 (Phase A 教训):
  - 纯逻辑测试 (无 I/O, 无 SQLite), 每用例 <10ms
  - 单文件 pytest --timeout=60 --no-cov
"""

from __future__ import annotations

import pytest

from auto_engineering.loop.checkpoint.migration import (
    ENVELOPE_SCHEMA_VERSION,
    _parse_version,
    migrate_envelope,
    validate_envelope,
)

# ============================================================
# 辅助: 构造 1.0 / 0.9 envelope
# ============================================================


def _make_1_0_envelope(**overrides: object) -> dict:
    """构造合法的 1.0 envelope dict."""
    base: dict = {
        "round": 0,
        "step": 0,
        "status": "running",
        "tasks": {},
        "task_results": {},
        "gate_results": {},
        "signals": [],
        "metrics": {"values": {}},
        "channels": {},
        "channel_versions": {},
        "schema_version": ENVELOPE_SCHEMA_VERSION,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _make_0_9_envelope(**overrides: object) -> dict:
    """构造合法的 0.9 envelope dict (缺 1.0 新增字段)."""
    base: dict = {
        "round": 1,
        "status": "running",
        "tasks": {},
        "channels": {},
        "schema_version": "0.9",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


# ============================================================
# _parse_version 单元测试
# ============================================================


class TestParseVersion:
    """版本字符串 → 元组 解析."""

    def test_parse_simple(self) -> None:
        assert _parse_version("1.0") == (1, 0)

    def test_parse_three_part(self) -> None:
        assert _parse_version("0.9.1") == (0, 9, 1)

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid schema_version"):
            _parse_version("not-a-version")


# ============================================================
# migrate_envelope — 1.0 pass-through
# ============================================================


class TestMigrate1_0Passthrough:
    """schema_version=1.0 直接返回, 不修改."""

    def test_1_0_returns_as_is(self) -> None:
        env = _make_1_0_envelope()
        result = migrate_envelope(env)
        assert result is env  # 同一对象, 不拷贝
        assert result["schema_version"] == ENVELOPE_SCHEMA_VERSION

    def test_1_0_preserves_extra_fields(self) -> None:
        """额外字段保留, 不被删除."""
        env = _make_1_0_envelope(custom_field="keep_me")
        result = migrate_envelope(env)
        assert result["custom_field"] == "keep_me"

    def test_1_0_preserves_all_values(self) -> None:
        """所有字段值不变."""
        env = _make_1_0_envelope(
            round=5,
            step=3,
            status="converged",
            tasks={"t1": {"id": "t1", "status": "done"}},
        )
        result = migrate_envelope(env)
        assert result["round"] == 5
        assert result["step"] == 3
        assert result["status"] == "converged"
        assert result["tasks"] == {"t1": {"id": "t1", "status": "done"}}


# ============================================================
# migrate_envelope — 0.9 → 1.0
# ============================================================


class TestMigrate0_9To1_0:
    """schema_version=0.9 迁移到 1.0."""

    def test_0_9_adds_missing_fields(self) -> None:
        env = _make_0_9_envelope()
        result = migrate_envelope(env)
        assert result["schema_version"] == ENVELOPE_SCHEMA_VERSION
        assert result["step"] == 0
        assert result["task_results"] == {}
        assert result["gate_results"] == {}
        assert result["signals"] == []
        assert result["metrics"] == {"values": {}}
        assert result["channel_versions"] == {}

    def test_0_9_preserves_existing_fields(self) -> None:
        env = _make_0_9_envelope(round=7, status="converged")
        result = migrate_envelope(env)
        assert result["round"] == 7
        assert result["status"] == "converged"
        assert result["tasks"] == {}

    def test_0_9_does_not_overwrite_existing(self) -> None:
        """已有字段不被默认值覆盖."""
        env = _make_0_9_envelope(step=5, task_results={"t1": "done"})
        result = migrate_envelope(env)
        assert result["step"] == 5  # 保留原值
        assert result["task_results"] == {"t1": "done"}  # 保留原值

    def test_0_9_preserves_extra_fields(self) -> None:
        """额外字段在迁移后保留."""
        env = _make_0_9_envelope(legacy_field="old_data")
        result = migrate_envelope(env)
        assert result["legacy_field"] == "old_data"
        assert result["schema_version"] == ENVELOPE_SCHEMA_VERSION

    def test_migrate_is_idempotent(self) -> None:
        """两次迁移结果一致."""
        env = _make_0_9_envelope()
        first = migrate_envelope(env)
        second = migrate_envelope(first)
        assert first == second


# ============================================================
# migrate_envelope — <0.9 reject
# ============================================================


class TestMigrateRejectOld:
    """schema_version < 0.9 → ValueError."""

    def test_0_8_rejected(self) -> None:
        env = _make_0_9_envelope()
        env["schema_version"] = "0.8"
        with pytest.raises(ValueError, match="too old"):
            migrate_envelope(env)

    def test_0_1_rejected(self) -> None:
        env = _make_0_9_envelope()
        env["schema_version"] = "0.1"
        with pytest.raises(ValueError, match="too old"):
            migrate_envelope(env)


# ============================================================
# migrate_envelope — 无 schema_version
# ============================================================


class TestMigrateNoVersion:
    """无 schema_version → 按 0.9 处理."""

    def test_no_version_treated_as_0_9(self) -> None:
        env = {"round": 1, "status": "running", "tasks": {}, "channels": {}}
        result = migrate_envelope(env)
        assert result["schema_version"] == ENVELOPE_SCHEMA_VERSION
        assert result["step"] == 0
        assert result["channel_versions"] == {}

    def test_no_version_preserves_existing(self) -> None:
        env = {"round": 3, "status": "converged", "tasks": {"t1": {}}, "channels": {}}
        result = migrate_envelope(env)
        assert result["round"] == 3
        assert result["status"] == "converged"


# ============================================================
# migrate_envelope — 错误输入
# ============================================================


class TestMigrateErrors:
    """边界 / 错误输入."""

    def test_future_version_rejected(self) -> None:
        """未来版本 (高于当前) 拒绝降级."""
        env = _make_1_0_envelope()
        env["schema_version"] = "2.0"
        with pytest.raises(ValueError, match="newer"):
            migrate_envelope(env)

    def test_non_dict_raises_typeerror(self) -> None:
        with pytest.raises(TypeError, match="expects dict"):
            migrate_envelope("not a dict")  # type: ignore[arg-type]

    def test_invalid_version_string_raises(self) -> None:
        env = _make_1_0_envelope()
        env["schema_version"] = "abc"
        with pytest.raises(ValueError, match="Invalid schema_version"):
            migrate_envelope(env)

    def test_non_string_version_raises(self) -> None:
        env = _make_1_0_envelope()
        env["schema_version"] = 1  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="schema_version must be str"):
            migrate_envelope(env)


# ============================================================
# validate_envelope
# ============================================================


class TestValidateEnvelope:
    """validate_envelope 合法性判定."""

    def test_valid_1_0_returns_true(self) -> None:
        env = _make_1_0_envelope()
        assert validate_envelope(env) is True

    def test_missing_required_field_returns_false(self) -> None:
        env = _make_1_0_envelope()
        del env["channel_versions"]
        assert validate_envelope(env) is False

    def test_wrong_type_returns_false(self) -> None:
        env = _make_1_0_envelope()
        env["round"] = "not_an_int"  # type: ignore[arg-type]
        assert validate_envelope(env) is False

    def test_wrong_schema_version_returns_false(self) -> None:
        env = _make_1_0_envelope()
        env["schema_version"] = "0.9"
        assert validate_envelope(env) is False

    def test_no_schema_version_returns_false(self) -> None:
        env = _make_1_0_envelope()
        del env["schema_version"]
        assert validate_envelope(env) is False

    def test_non_dict_returns_false(self) -> None:
        assert validate_envelope("not a dict") is False  # type: ignore[arg-type]
        assert validate_envelope(None) is False  # type: ignore[arg-type]
        assert validate_envelope([]) is False  # type: ignore[arg-type]

    def test_migrated_0_9_validates_true(self) -> None:
        """0.9 迁移后通过 validate_envelope."""
        env = _make_0_9_envelope()
        migrated = migrate_envelope(env)
        assert validate_envelope(migrated) is True


# ============================================================
# ENVELOPE_SCHEMA_VERSION 常量
# ============================================================


def test_schema_version_is_1_0_string() -> None:
    """ENVELOPE_SCHEMA_VERSION 是字符串 '1.0'."""
    assert ENVELOPE_SCHEMA_VERSION == "1.0"
    assert isinstance(ENVELOPE_SCHEMA_VERSION, str)
