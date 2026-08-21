"""Claude Code 本机安装必须与开发工作区彻底解耦。"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_claude_local
from scripts.install_claude_local import (
    CommandRunner,
    install_claude_release,
    prepare_existing_install_for_removal,
    prepare_orphaned_version_cache_for_removal,
    verify_claude_install,
)
from scripts.install_codex_local import StagedRelease

ROOT = Path(__file__).resolve().parents[1]


def test_reinstall_unseals_only_enumerated_owned_cache(tmp_path: Path) -> None:
    boundary = tmp_path / "cache" / "auto-engineering" / "auto-engineering"
    plugin = boundary / "5.8.0-rc.5"
    runtime = plugin / ".ae-runtime"
    runtime.mkdir(parents=True)
    payload = plugin / "build-info.json"
    payload.write_text("{}", encoding="utf-8")
    payload.chmod(0o444)
    runtime.chmod(0o555)
    plugin.chmod(0o555)

    prepare_existing_install_for_removal([{
        "id": "auto-engineering@auto-engineering",
        "scope": "user",
        "installPath": str(plugin),
    }], cache_root=boundary)

    assert stat.S_IMODE(plugin.stat().st_mode) == 0o755
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o755
    assert stat.S_IMODE(payload.stat().st_mode) == 0o644


def test_reinstall_rejects_enumerated_path_outside_owned_cache(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(RuntimeError, match="缓存边界"):
        prepare_existing_install_for_removal([{
            "id": "auto-engineering@auto-engineering",
            "scope": "user",
            "installPath": str(outside),
        }], cache_root=tmp_path / "cache")


def test_reinstall_unseals_exact_valid_orphan_version_cache(tmp_path: Path) -> None:
    boundary = tmp_path / "cache"
    orphan = boundary / "5.8.0-rc.5"
    orphan.mkdir(parents=True)
    (orphan / "build-info.json").write_text(json.dumps({
        "version": "5.8.0-rc.5",
        "build_id": "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
    }), encoding="utf-8")
    orphan.chmod(0o555)

    prepare_orphaned_version_cache_for_removal(
        version="5.8.0-rc.5",
        cache_root=boundary,
    )

    assert stat.S_IMODE(orphan.stat().st_mode) == 0o755


def test_reinstall_rejects_orphan_with_wrong_build_identity(tmp_path: Path) -> None:
    boundary = tmp_path / "cache"
    orphan = boundary / "5.8.0-rc.5"
    orphan.mkdir(parents=True)
    (orphan / "build-info.json").write_text(json.dumps({
        "version": "5.8.0-rc.5",
        "build_id": "different-build",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Build Identity"):
        prepare_orphaned_version_cache_for_removal(
            version="5.8.0-rc.5",
            cache_root=boundary,
        )


def _minimal_release(root: Path) -> None:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"name": "auto-engineering", "plugins": []}),
        encoding="utf-8",
    )


def test_direct_script_entrypoint_loads_without_repository_pythonpath(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/install_claude_local.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--staging-root" in result.stdout


def test_install_registers_only_staged_claude_marketplace(tmp_path: Path) -> None:
    development_root = tmp_path / "source"
    staged_root = tmp_path / "releases/build-id"
    development_root.mkdir()
    _minimal_release(staged_root)
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    install_claude_release(
        staged_root,
        development_root=development_root,
        runner=CommandRunner(runner),
    )

    assert commands == [
        ["claude", "plugin", "uninstall", "auto-engineering@auto-engineering", "--scope", "user", "--yes"],
        ["claude", "plugin", "marketplace", "remove", "auto-engineering", "--scope", "user"],
        ["claude", "plugin", "marketplace", "add", str(staged_root), "--scope", "user"],
        ["claude", "plugin", "install", "auto-engineering@auto-engineering", "--scope", "user"],
    ]


def test_install_rejects_release_inside_development_root(tmp_path: Path) -> None:
    development_root = tmp_path / "source"
    staged_root = development_root / "release"
    development_root.mkdir()
    _minimal_release(staged_root)

    with pytest.raises(ValueError, match="开发目录之外"):
        install_claude_release(staged_root, development_root=development_root)


def test_install_requires_claude_marketplace_manifest(tmp_path: Path) -> None:
    development_root = tmp_path / "source"
    staged_root = tmp_path / "release"
    development_root.mkdir()
    staged_root.mkdir()

    with pytest.raises(RuntimeError, match="Marketplace manifest"):
        install_claude_release(staged_root, development_root=development_root)


def _installed_fixture(tmp_path: Path) -> tuple[Path, Path, StagedRelease]:
    source = tmp_path / "source"
    release_root = tmp_path / "releases/build-id"
    plugin_root = tmp_path / "claude-cache/auto-engineering"
    source.mkdir()
    release_root.mkdir(parents=True)
    (plugin_root / ".ae-runtime/bin").mkdir(parents=True)
    (plugin_root / "auto_engineering").mkdir()
    build_id = "5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa"
    (plugin_root / "build-info.json").write_text(
        json.dumps({"build_id": build_id}), encoding="utf-8"
    )
    (plugin_root / ".ae-runtime/bin/ae").write_text(
        f"#!/bin/sh\nexec {plugin_root}/.ae-runtime/bin/python \"$@\"\n",
        encoding="utf-8",
    )
    return source, plugin_root, StagedRelease(
        root=release_root,
        version="5.8.0-rc.5",
        build_id=build_id,
        content_sha256="a" * 64,
    )


def test_verify_claude_install_binds_build_and_runtime_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, plugin_root, release = _installed_fixture(tmp_path)
    marketplace_root = tmp_path / "claude-marketplace"
    marketplace_root.mkdir()
    responses = iter([
        [{"name": "auto-engineering", "installLocation": str(marketplace_root)}],
        [{
            "id": "auto-engineering@auto-engineering",
            "scope": "user",
            "enabled": True,
            "installPath": str(plugin_root),
        }],
    ])
    monkeypatch.setattr(install_claude_local, "_json_command", lambda command: next(responses))

    observed_environment: dict[str, str] = {}

    def run(command, **kwargs):
        environment = kwargs.get("env", {})
        observed_environment.update(environment)
        assert "CODEX_THREAD_ID" not in environment
        assert "CODEX_SANDBOX" not in environment
        if command[0].endswith("ae-run"):
            assert (Path(kwargs["cwd"]) / ".ae-state").is_dir()
        stdout = ""
        if command[0].endswith("python"):
            stdout = str(plugin_root / "auto_engineering/__init__.py") + "\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(install_claude_local.subprocess, "run", run)

    verify_claude_install(release, source)
    assert observed_environment["CLAUDE_CODE_ENTRYPOINT"] == "cli"


def test_verify_claude_install_rejects_different_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, plugin_root, release = _installed_fixture(tmp_path)
    (plugin_root / "build-info.json").write_text(
        json.dumps({"build_id": "different-build"}), encoding="utf-8"
    )
    responses = iter([
        [{"name": "auto-engineering", "installLocation": str(tmp_path / "marketplace")}],
        [{
            "id": "auto-engineering@auto-engineering",
            "scope": "user",
            "enabled": True,
            "installPath": str(plugin_root),
        }],
    ])
    monkeypatch.setattr(install_claude_local, "_json_command", lambda command: next(responses))

    with pytest.raises(RuntimeError, match="Build Identity"):
        verify_claude_install(release, source)
