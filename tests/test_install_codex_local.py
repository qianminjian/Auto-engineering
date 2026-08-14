"""Codex 本机安装必须与开发工作区彻底解耦。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.install_codex_local import (
    CommandRunner,
    install_codex_release,
    stage_release,
    verify_runtime_paths,
)


def _minimal_release(root: Path) -> None:
    (root / ".agents/plugins").mkdir(parents=True)
    (root / "plugins/auto-engineering/bin").mkdir(parents=True)
    (root / ".agents/plugins/marketplace.json").write_text(
        json.dumps({"name": "auto-engineering", "plugins": []}),
        encoding="utf-8",
    )
    (root / "build-info.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "5.8.0-rc.5",
                "content_sha256": "a" * 64,
                "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
            }
        ),
        encoding="utf-8",
    )


def test_stage_release_rejects_destination_inside_development_root(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / "source"
    development_root.mkdir()

    with pytest.raises(ValueError, match="开发目录之外"):
        stage_release(
            development_root,
            development_root / ".release-install",
        )


def test_install_registers_only_staged_marketplace(tmp_path: Path) -> None:
    development_root = tmp_path / "source"
    staged_root = tmp_path / "releases" / "build-id"
    development_root.mkdir()
    _minimal_release(staged_root)
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    install_codex_release(
        staged_root,
        development_root=development_root,
        runner=CommandRunner(runner),
    )

    assert commands == [
        ["codex", "plugin", "remove", "auto-engineering@auto-engineering", "--json"],
        ["codex", "plugin", "marketplace", "remove", "auto-engineering", "--json"],
        ["codex", "plugin", "marketplace", "add", str(staged_root), "--json"],
        ["codex", "plugin", "add", "auto-engineering@auto-engineering", "--json"],
    ]


def test_fresh_install_tolerates_only_missing_old_registration(tmp_path: Path) -> None:
    development_root = tmp_path / "source"
    staged_root = tmp_path / "releases" / "build-id"
    development_root.mkdir()
    _minimal_release(staged_root)
    calls = 0

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls <= 2:
            return subprocess.CompletedProcess(command, 1, "", "not installed")
        return subprocess.CompletedProcess(command, 0, "{}", "")

    install_codex_release(
        staged_root,
        development_root=development_root,
        runner=CommandRunner(runner),
    )
    assert calls == 4


def test_runtime_path_verification_rejects_development_origin(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / "source"
    install_root = tmp_path / "installed"
    development_root.mkdir()
    install_root.mkdir()

    with pytest.raises(RuntimeError, match="开发目录"):
        verify_runtime_paths(
            development_root=development_root,
            marketplace_root=install_root,
            plugin_root=install_root / "plugin",
            module_origin=development_root / "auto_engineering/__init__.py",
            launcher_shebang=f"#!{install_root}/.ae-runtime/bin/python",
        )


def test_runtime_path_verification_accepts_isolated_origins(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / "source"
    marketplace_root = tmp_path / "releases" / "build-id"
    plugin_root = tmp_path / "cache" / "auto-engineering"
    development_root.mkdir()
    marketplace_root.mkdir(parents=True)
    plugin_root.mkdir(parents=True)

    verify_runtime_paths(
        development_root=development_root,
        marketplace_root=marketplace_root,
        plugin_root=plugin_root,
        module_origin=plugin_root / "auto_engineering/__init__.py",
        launcher_shebang=f"#!/bin/sh\n'exec' {plugin_root}/.ae-runtime/bin/python",
    )
