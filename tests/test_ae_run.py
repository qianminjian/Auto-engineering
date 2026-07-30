"""平台无关 ae CLI resolver 的行为测试。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _copy_launcher(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "scripts" / "ae-run"
    assert source.is_file(), "scripts/ae-run 尚未实现"
    target = tmp_path / "plugin" / "scripts" / "ae-run"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    target.chmod(0o755)
    return target


def _copy_bundled_entrypoint(tmp_path: Path) -> Path:
    root = Path(__file__).parents[1]
    plugin = tmp_path / "plugin"
    scripts_launcher = _copy_launcher(tmp_path)
    entrypoint = plugin / "bin" / "ae-run"
    entrypoint.parent.mkdir(parents=True)
    shutil.copy2(root / "bin" / "ae-run", entrypoint)
    entrypoint.chmod(0o755)
    assert scripts_launcher.is_file()
    return entrypoint


def _write_executable(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nprintf \'%s\' "{output}:$*"\n')
    path.chmod(0o755)


def _run(launcher: Path, path: str, *args: str) -> subprocess.CompletedProcess[str]:
    environ = os.environ.copy()
    environ["PATH"] = path
    return subprocess.run(
        [str(launcher), *args],
        cwd=launcher.parents[2],
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prefers_plugin_virtualenv_ae(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    _write_executable(tmp_path / "plugin" / ".venv" / "bin" / "ae", "venv")
    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "uv", "uv")
    _write_executable(bin_dir / "ae", "path")

    result = _run(launcher, str(bin_dir), "status", "--format", "json")

    assert result.returncode == 0
    assert result.stdout == "venv:status --format json"


def test_falls_back_to_uv_run_ae(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "uv", "uv")

    result = _run(launcher, str(bin_dir), "doctor")

    assert result.returncode == 0
    assert result.stdout == "uv:run --project " + str(tmp_path / "plugin") + " ae doctor"


def test_falls_back_to_ae_on_path(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "ae", "path")

    result = _run(launcher, str(bin_dir), "status")

    assert result.returncode == 0
    assert result.stdout == "path:status"


def test_reports_actionable_error_when_cli_is_unavailable(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    result = _run(launcher, str(empty_bin), "status")

    assert result.returncode == 127
    assert result.stdout == ""
    assert "AE_CLI_NOT_FOUND" in result.stderr
    assert "uv sync" in result.stderr


def test_bundled_entrypoint_resolves_plugin_from_unrelated_project_cwd(
    tmp_path: Path,
) -> None:
    entrypoint = _copy_bundled_entrypoint(tmp_path)
    _write_executable(
        tmp_path / "plugin" / ".venv" / "bin" / "ae",
        "bundled",
    )
    target_project = tmp_path / "target-project"
    target_project.mkdir()

    result = subprocess.run(
        [str(entrypoint), "status", "--format", "json"],
        cwd=target_project,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "bundled:status --format json"


def test_active_agent_entrypoints_use_shared_launcher() -> None:
    root = Path(__file__).parents[1]

    for relative_path in (
        "skills/auto-engineering/SKILL.md",
        "commands/dev-loop.md",
        "commands/status.md",
        "commands/code-review.md",
    ):
        content = (root / relative_path).read_text()
        assert "ae-run" in content, f"{relative_path} 未使用共享 CLI resolver"
        assert "scripts/ae-run" not in content, (
            f"{relative_path} 不得把 runner 解析到目标项目"
        )


def test_post_edit_hook_does_not_call_deleted_gate_check() -> None:
    root = Path(__file__).parents[1]
    content = (root / "hooks" / "post-edit.sh").read_text()

    assert "ae gate-check" not in content
