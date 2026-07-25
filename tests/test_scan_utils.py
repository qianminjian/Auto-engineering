"""Smoke tests for gates/_scan_utils.py — scan infrastructure utilities."""

from __future__ import annotations

from pathlib import Path

from auto_engineering.gates._scan_utils import (
    DEFAULT_MAX_FILE_MB,
    iter_scan_files,
    read_file_safe,
    should_skip_path,
)


class TestReadFileSafe:
    """read_file_safe: 文件内容安全读取 + 大小保护."""

    def test_read_normal_text_file(self, tmp_path: Path) -> None:
        path = tmp_path / "hello.txt"
        path.write_text("hello world", encoding="utf-8")
        content = read_file_safe(path)
        assert content == "hello world"

    def test_read_missing_file_returns_none(self) -> None:
        content = read_file_safe(Path("/nonexistent/file_xyz.txt"))
        assert content is None

    def test_read_large_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "large.bin"
        path.write_bytes(b"x" * (1 * 1024 * 1024 + 100))
        content = read_file_safe(path, max_size_mb=1)
        assert content is None

    def test_read_within_size_limit_succeeds(self, tmp_path: Path) -> None:
        path = tmp_path / "small.txt"
        path.write_text("small content", encoding="utf-8")
        content = read_file_safe(path, max_size_mb=10)
        assert content == "small content"


class TestShouldSkipPath:
    """should_skip_path: 判断路径是否在 skip_dir 集合中."""

    def test_path_in_skip_dir(self) -> None:
        path = Path("project/node_modules/pkg/index.js")
        assert should_skip_path(path, {"node_modules"}) is True

    def test_path_not_in_skip_dir(self) -> None:
        path = Path("project/src/main.py")
        assert should_skip_path(path, {"node_modules", ".git"}) is False

    def test_git_dir_skipped(self) -> None:
        path = Path("project/.git/config")
        assert should_skip_path(path, {".git"}) is True

    def test_venv_skipped(self) -> None:
        path = Path("project/.venv/lib/site.py")
        assert should_skip_path(path, {".venv", "__pycache__"}) is True


class TestIterScanFiles:
    """iter_scan_files: 收集匹配扩展名的文件，跳过指定目录."""

    def test_finds_py_files(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x")
        (tmp_path / "util.py").write_text("y")
        (tmp_path / "readme.md").write_text("z")
        files = iter_scan_files(tmp_path, extensions={".py"})
        rels = {rel for _, rel in files}
        assert "main.py" in rels
        assert "util.py" in rels
        assert "readme.md" not in rels

    def test_skips_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("x")
        skip_dir = tmp_path / "node_modules"
        skip_dir.mkdir()
        (skip_dir / "lib.js").write_text("y")
        files = iter_scan_files(tmp_path, extensions={".py", ".js"}, skip_dirs={"node_modules"})
        rels = {rel for _, rel in files}
        assert "main.py" in rels
        assert "node_modules/lib.js" not in rels

    def test_no_extensions_returns_all_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.md").write_text("y")
        files = iter_scan_files(tmp_path)
        assert len(files) >= 2

    def test_empty_directory(self, tmp_path: Path) -> None:
        files = iter_scan_files(tmp_path, extensions={".py"})
        assert files == []


class TestDefaultConstant:
    """DEFAULT_MAX_FILE_MB 常量."""

    def test_default_max_file_mb_is_5(self) -> None:
        assert DEFAULT_MAX_FILE_MB == 5
