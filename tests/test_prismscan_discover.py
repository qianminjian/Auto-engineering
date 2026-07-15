"""Tests for PrismScan discover.py — 项目形态识别."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class TestDiscover:
    """discover() 核心功能测试."""

    def test_discovers_python_project(self):
        from auto_engineering.prismscan.discover import discover
        from auto_engineering.prismscan.schemas import ProjectShape

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('hello')")
            (root / "src" / "lib.py").write_text("def foo(): pass")
            (root / "tests").mkdir()
            (root / "tests" / "test_main.py").write_text("def test(): pass")
            (root / "Dockerfile").write_text("FROM python:3.13")

            shape = discover(str(root))
            assert isinstance(shape, ProjectShape)
            assert shape.project_name == os.path.basename(str(root))
            assert "python" in [l.lower() for l in shape.languages]
            assert shape.build_system == "uv"  # pyproject.toml → uv
            assert shape.has_docker is True
            assert shape.total_files >= 4
            assert len(shape.modules) > 0

    def test_discovers_java_maven_project(self):
        from auto_engineering.prismscan.discover import discover

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project></project>")
            (root / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
            (root / "src" / "main" / "java" / "com" / "example" / "App.java").write_text(
                "public class App {}"
            )

            shape = discover(str(root))
            assert shape.build_system == "maven"
            assert "java" in [l.lower() for l in shape.languages]

    def test_empty_directory(self):
        from auto_engineering.prismscan.discover import discover

        with tempfile.TemporaryDirectory() as tmp:
            shape = discover(str(tmp))
            assert shape.project_name == os.path.basename(str(tmp))
            assert shape.total_files == 0
            assert shape.languages == []

    def test_identify_modules_single(self):
        from auto_engineering.prismscan.discover import identify_modules

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "core").mkdir(parents=True)
            (root / "src" / "core" / "main.py").write_text("pass")
            (root / "src" / "cli").mkdir(parents=True)
            (root / "src" / "cli" / "app.py").write_text("pass")

            modules = identify_modules(root, ".py")
            assert len(modules) >= 1  # src/core, src/cli grouped under src

    def test_find_entry_points_python(self):
        from auto_engineering.prismscan.discover import find_entry_points

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text('if __name__ == "__main__": pass')
            (root / "app").mkdir(parents=True)
            (root / "app" / "cli.py").write_text(
                "import click\n@click.command()\ndef main(): pass"
            )

            entries = find_entry_points(root, ".py")
            assert len(entries) >= 1

    def test_detect_languages_counts_extensions(self):
        from auto_engineering.prismscan.discover import detect_languages

        files = [
            Path("src/main.py"),
            Path("src/lib.py"),
            Path("src/App.java"),
            Path("src/utils.ts"),
            Path("README.md"),
        ]
        langs = detect_languages(files)
        assert "python" in langs
        assert "java" in langs
        assert "typescript" in langs

    def test_directory_tree_summary(self):
        from auto_engineering.prismscan.discover import generate_tree_summary

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "core").mkdir(parents=True)
            (root / "src" / "core" / "main.py").write_text("pass")
            (root / "tests").mkdir()
            (root / "README.md").write_text("# Test")

            summary = generate_tree_summary(root)
            assert "src/" in summary
            assert "README.md" in summary
