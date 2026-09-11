"""Codex 本机安装必须与开发工作区彻底解耦。"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_codex_local
from scripts.build_release import build_archive
from scripts.install_codex_local import (
    CommandRunner,
    StagedRelease,
    _seal_release_tree,
    install_codex_marketplace,
    install_codex_release,
    stage_archive,
    stage_release,
    verify_codex_hook_wire_contract,
    verify_runtime_paths,
)

ROOT = Path(__file__).resolve().parents[1]


def test_sealed_release_is_read_only(tmp_path: Path) -> None:
    release = tmp_path / "release"
    plugin = release / "plugins" / "auto-engineering"
    plugin.mkdir(parents=True)
    launcher = plugin / "bin" / "ae-run"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)

    _seal_release_tree(release)

    assert stat.S_IMODE(release.stat().st_mode) == 0o555
    assert stat.S_IMODE(plugin.stat().st_mode) == 0o555
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o555


def test_direct_script_entrypoint_loads_without_repository_pythonpath(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "scripts/install_codex_local.py"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--staging-root" in result.stdout
    assert "--archive" in result.stdout


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


def test_stage_archive_preserves_content_addressed_build_identity(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "release.tar.gz"
    build_archive(ROOT, archive)

    release = stage_archive(archive, tmp_path / "staging")

    assert release.root == (tmp_path / "staging" / release.build_id).resolve()
    assert release.build_id.startswith("5.8.0-rc.5+sha256.")
    assert (release.root / "build-info.json").is_file()
    assert (release.root / "plugins/auto-engineering/build-info.json").is_file()


def test_stage_archive_reuses_release_won_by_concurrent_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一 Build 的并发暂存不能因目录移动竞争失败。"""
    archive = tmp_path / "release.tar.gz"
    build_archive(ROOT, archive)
    original_replace = install_codex_local.os.replace

    def racing_replace(source: str | Path, destination: str | Path) -> None:
        destination_path = Path(destination)
        shutil.copytree(source, destination_path)
        raise OSError("simulated concurrent directory move")

    monkeypatch.setattr(install_codex_local.os, "replace", racing_replace)

    release = stage_archive(archive, tmp_path / "staging")

    assert release.root.is_dir()
    assert release.build_id in release.root.name
    monkeypatch.setattr(install_codex_local.os, "replace", original_replace)


def test_archive_cli_installs_and_verifies_exact_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"archive")
    staged = StagedRelease(
        root=tmp_path / "staged/5.8.0-rc.5+sha256.test",
        version="5.8.0-rc.5",
        build_id="5.8.0-rc.5+sha256.test",
        content_sha256="a" * 64,
    )
    calls: list[tuple[str, Path, Path]] = []

    def stage(
        archive_path: Path,
        staging_root: Path,
        *,
        development_root: Path,
    ) -> StagedRelease:
        assert archive_path == archive
        assert staging_root == tmp_path / "staging"
        assert development_root == tmp_path / "source"
        return staged

    monkeypatch.setattr(install_codex_local, "stage_archive", stage)
    monkeypatch.setattr(
        install_codex_local,
        "install_codex_release",
        lambda release_root, *, development_root: calls.append(
            ("install", release_root, development_root)
        ),
    )
    monkeypatch.setattr(
        install_codex_local,
        "verify_codex_install",
        lambda release, development_root: calls.append(
            ("verify", release.root, development_root)
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_codex_local.py",
            "--root", str(tmp_path / "source"),
            "--staging-root", str(tmp_path / "staging"),
            "--archive", str(archive),
        ],
    )

    assert install_codex_local.main() == 0
    assert calls == [
        ("install", staged.root, tmp_path / "source"),
        ("verify", staged.root, tmp_path / "source"),
    ]


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


def test_standard_install_uses_host_managed_github_marketplace() -> None:
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    install_codex_marketplace(
        source="qianminjian/Auto-engineering",
        ref="main",
        runner=CommandRunner(runner),
    )

    assert commands == [
        ["codex", "plugin", "remove", "auto-engineering@auto-engineering", "--json"],
        ["codex", "plugin", "marketplace", "remove", "auto-engineering", "--json"],
        [
            "codex", "plugin", "marketplace", "add",
            "qianminjian/Auto-engineering", "--ref", "main", "--json",
        ],
        ["codex", "plugin", "add", "auto-engineering@auto-engineering", "--json"],
    ]


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
            runtime_root=install_root / "project/.ae-state/.ae-runtime",
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
    (tmp_path / "project/.ae-state/.ae-runtime").mkdir(parents=True)

    verify_runtime_paths(
        development_root=development_root,
        marketplace_root=marketplace_root,
        plugin_root=plugin_root,
        module_origin=plugin_root / "auto_engineering/__init__.py",
        runtime_root=tmp_path / "project/.ae-state/.ae-runtime",
    )


def test_installed_codex_hook_wire_contract_blocks_before_mutation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / ".ae-state").mkdir(parents=True)
    verify_codex_hook_wire_contract(
        plugin_root=ROOT,
        project_root=project,
        environment={"PATH": os.environ["PATH"]},
    )


def test_codex_install_rejects_loaded_plugin_with_different_build_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marketplace 注册正确但缓存内容过期时，安装验收必须 fail-closed。"""
    development_root = tmp_path / "source"
    release_root = tmp_path / "releases/5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa"
    plugin_root = release_root / "plugins/auto-engineering"
    runtime_root = tmp_path / "project/.ae-state/.ae-runtime"
    development_root.mkdir()
    (plugin_root / "bin").mkdir(parents=True)
    (plugin_root / "build-info.json").write_text(
        json.dumps({
            "version": "5.8.0-rc.5",
            "build_id": "5.8.0-rc.5+sha256.bbbbbbbbbbbbbbbb",
            "content_sha256": "b" * 64,
        }),
        encoding="utf-8",
    )
    release = StagedRelease(
        root=release_root,
        version="5.8.0-rc.5",
        build_id="5.8.0-rc.5+sha256.aaaaaaaaaaaaaaaa",
        content_sha256="a" * 64,
    )

    def list_command(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[-1] == "list" and "marketplace" in command:
            return subprocess.CompletedProcess(command, 0, str(release_root), "")
        if command == ["codex", "plugin", "list"]:
            return subprocess.CompletedProcess(command, 0, f"PLUGIN TABLE {plugin_root}", "")
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({
                "installed": [{
                    "pluginId": "auto-engineering@auto-engineering",
                    "source": {"source": "local", "path": str(plugin_root)},
                }],
            }),
            "",
        )

    monkeypatch.setattr(install_codex_local, "_default_runner", list_command)

    project_root = tmp_path / "project"
    project_root.mkdir(exist_ok=True)

    class TemporaryProject:
        def __enter__(self) -> str:
            return str(project_root)

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(
        install_codex_local.tempfile,
        "TemporaryDirectory",
        lambda **_: TemporaryProject(),
    )

    def fake_subprocess_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "doctor" in command:
            runtime_root.mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(
            command, 0, str(plugin_root / "auto_engineering/__init__.py"), ""
        )

    monkeypatch.setattr(install_codex_local.subprocess, "run", fake_subprocess_run)

    with pytest.raises(RuntimeError, match="Build Identity"):
        install_codex_local.verify_codex_install(
            release,
            development_root,
        )
