"""T1: 项目骨架 + 配置文件 — voice-clone 项目结构测试.

验证项目基础配置文件 (package.json, tsconfig.json, vite.config.ts, index.html) 存在且合法.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent / "voice-clone"


class TestPackageJson:
    """package.json — 项目元信息 + 依赖."""

    def test_package_json_exists(self) -> None:
        """package.json 文件必须存在."""
        pkg = PROJECT_ROOT / "package.json"
        assert pkg.is_file(), f"Expected {pkg} to exist"

    def test_package_json_is_valid_json(self) -> None:
        """package.json 必须是合法 JSON."""
        pkg = PROJECT_ROOT / "package.json"
        data = json.loads(pkg.read_text())
        assert isinstance(data, dict), "package.json must be a JSON object"

    def test_package_json_has_name(self) -> None:
        """package.json 必须有 name 字段."""
        pkg = PROJECT_ROOT / "package.json"
        data = json.loads(pkg.read_text())
        assert "name" in data, "package.json must have 'name' field"

    def test_package_json_has_scripts(self) -> None:
        """package.json 必须有 scripts 字段 (dev/build/preview)."""
        pkg = PROJECT_ROOT / "package.json"
        data = json.loads(pkg.read_text())
        assert "scripts" in data, "package.json must have 'scripts' field"
        assert "dev" in data["scripts"], "Must have 'dev' script"
        assert "build" in data["scripts"], "Must have 'build' script"

    def test_package_json_has_vite_dependency(self) -> None:
        """package.json devDependencies 必须包含 vite."""
        pkg = PROJECT_ROOT / "package.json"
        data = json.loads(pkg.read_text())
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        assert any("vite" in k for k in deps), (
            "Must have vite in dependencies or devDependencies"
        )


class TestTypeScriptConfig:
    """tsconfig.json — TypeScript 编译配置."""

    def test_tsconfig_exists(self) -> None:
        """tsconfig.json 文件必须存在."""
        tsconfig = PROJECT_ROOT / "tsconfig.json"
        assert tsconfig.is_file(), f"Expected {tsconfig} to exist"

    def test_tsconfig_is_valid_json(self) -> None:
        """tsconfig.json 必须是合法 JSON."""
        tsconfig = PROJECT_ROOT / "tsconfig.json"
        data = json.loads(tsconfig.read_text())
        assert isinstance(data, dict)

    def test_tsconfig_has_compiler_options(self) -> None:
        """tsconfig.json 必须有 compilerOptions."""
        tsconfig = PROJECT_ROOT / "tsconfig.json"
        data = json.loads(tsconfig.read_text())
        assert "compilerOptions" in data


class TestViteConfig:
    """vite.config.ts — Vite 构建配置."""

    def test_vite_config_exists(self) -> None:
        """vite.config.ts 文件必须存在."""
        vcfg = PROJECT_ROOT / "vite.config.ts"
        assert vcfg.is_file(), f"Expected {vcfg} to exist"

    def test_vite_config_has_content(self) -> None:
        """vite.config.ts 不能为空."""
        vcfg = PROJECT_ROOT / "vite.config.ts"
        content = vcfg.read_text()
        assert len(content.strip()) > 10, "vite.config.ts should have meaningful content"

    def test_vite_config_imports_define_config(self) -> None:
        """vite.config.ts 必须 import defineConfig from vite."""
        vcfg = PROJECT_ROOT / "vite.config.ts"
        content = vcfg.read_text()
        assert "defineConfig" in content, "Must import defineConfig from vite"
        assert "vite" in content, "Must reference 'vite'"


class TestIndexHtml:
    """index.html — Vite 入口 HTML."""

    def test_index_html_exists(self) -> None:
        """index.html 文件必须存在."""
        html = PROJECT_ROOT / "index.html"
        assert html.is_file(), f"Expected {html} to exist"

    def test_index_html_has_doctype(self) -> None:
        """index.html 必须有 DOCTYPE 声明."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert content.lstrip().startswith("<!DOCTYPE html"), "Must start with <!DOCTYPE html>"

    def test_index_html_has_lang_attribute(self) -> None:
        """index.html 的 <html> 必须有 lang 属性."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert re.search(r'<html[^>]*\blang\s*=', content, re.IGNORECASE), (
            "Missing lang attribute on <html>"
        )

    def test_index_html_has_viewport_meta(self) -> None:
        """index.html 必须有 viewport meta."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert 'name="viewport"' in content, "Missing viewport meta tag"

    def test_index_html_has_title(self) -> None:
        """index.html 必须有 <title> 标签."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert "<title>" in content, "Missing <title> tag"

    def test_index_html_has_root_div(self) -> None:
        """index.html 必须有 <div id=\"root\"> 挂载点."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert 'id="root"' in content or "id='root'" in content, (
            "Missing <div id=\"root\"> mount point"
        )

    def test_index_html_links_to_entry_script(self) -> None:
        """index.html 必须引用入口 JS/TS 文件."""
        html = PROJECT_ROOT / "index.html"
        content = html.read_text()
        assert "src" in content and ("main" in content or "index" in content), (
            "Must link to entry script (main.tsx or index.ts)"
        )


class TestDirectoryStructure:
    """项目目录结构."""

    def test_src_directory_exists(self) -> None:
        """src/ 目录必须存在."""
        srcdir = PROJECT_ROOT / "src"
        assert srcdir.is_dir(), f"Expected {srcdir} directory to exist"

    def test_src_has_main_tsx(self) -> None:
        """src/main.tsx 或 src/main.ts 入口文件必须存在."""
        candidates = [
            PROJECT_ROOT / "src" / "main.tsx",
            PROJECT_ROOT / "src" / "main.ts",
            PROJECT_ROOT / "src" / "index.tsx",
            PROJECT_ROOT / "src" / "index.ts",
        ]
        assert any(c.is_file() for c in candidates), (
            "Missing entry file: src/main.tsx or src/main.ts"
        )

    def test_src_has_app_tsx(self) -> None:
        """src/App.tsx 或 src/App.tsx 组件文件必须存在."""
        candidates = [
            PROJECT_ROOT / "src" / "App.tsx",
            PROJECT_ROOT / "src" / "App.ts",
        ]
        assert any(c.is_file() for c in candidates), (
            "Missing App component: src/App.tsx"
        )

    def test_src_types_directory_exists(self) -> None:
        """src/types/ 目录必须存在."""
        d = PROJECT_ROOT / "src" / "types"
        assert d.is_dir(), f"Expected {d} to exist"
