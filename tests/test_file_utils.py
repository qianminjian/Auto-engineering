"""Smoke tests for utils/file_utils.py — safe_json_load + safe_json_save."""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.utils.file_utils import safe_json_load, safe_json_save


class TestSafeJsonLoad:
    """safe_json_load — 安全读取 JSON 文件，失败返回 None + WARN."""

    def test_load_valid_json_object(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text('{"key": "value"}', encoding="utf-8")
        result = safe_json_load(path)
        assert result == {"key": "value"}

    def test_load_valid_json_list(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text('[1, 2, 3]', encoding="utf-8")
        result = safe_json_load(path)
        assert result == [1, 2, 3]

    def test_load_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{invalid json}", encoding="utf-8")
        result = safe_json_load(path)
        assert result is None

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent.json"
        result = safe_json_load(path)
        assert result is None

    def test_load_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        result = safe_json_load(path)
        assert result is None


class TestSafeJsonSave:
    """safe_json_save — 原子写入（tmp → os.replace）."""

    def test_save_and_reload_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "output.json"
        data = {"a": 1, "b": [2, 3]}
        ok = safe_json_save(path, data)
        assert ok is True
        assert path.exists()
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded == data

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deeply" / "nested" / "output.json"
        data = {"x": "y"}
        ok = safe_json_save(path, data)
        assert ok is True
        assert path.exists()

    def test_save_is_atomic_no_tmp_leftover(self, tmp_path: Path) -> None:
        """After successful save, .tmp file should not exist."""
        path = tmp_path / "atomic.json"
        data = {"atomic": True}
        safe_json_save(path, data)
        tmp_file = path.with_suffix(path.suffix + ".tmp")
        assert not tmp_file.exists()
