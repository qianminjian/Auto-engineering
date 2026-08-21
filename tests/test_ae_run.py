"""平台无关 ae CLI resolver 的行为测试。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


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


def _write_plugin_venv_executable(plugin: Path, output: str) -> None:
    interpreter = plugin / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.symlink_to("/bin/sh")
    entrypoint = plugin / ".venv" / "bin" / "ae"
    entrypoint.write_text(
        f"#!{interpreter}\nprintf '%s' \"{output}:$*\"\n"
    )
    entrypoint.chmod(0o755)


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


def test_ignores_mutable_plugin_virtualenv_and_uses_dedicated_runtime(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    _write_plugin_venv_executable(tmp_path / "plugin", "venv")
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text(
        "#!/bin/sh\nprintf '%s' \"uv:${UV_PROJECT_ENVIRONMENT}:$*\"\n"
    )
    uv.chmod(0o755)
    _write_executable(bin_dir / "ae", "path")

    result = _run(launcher, str(bin_dir), "status", "--format", "json")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:" + str(tmp_path / "plugin" / ".ae-runtime")
        + ":run --frozen --project " + str(tmp_path / "plugin")
        + " ae status --format json"
    )


def test_rejects_copied_virtualenv_entrypoint_that_escapes_plugin(
    tmp_path: Path,
) -> None:
    launcher = _copy_launcher(tmp_path)
    _write_executable(tmp_path / "plugin" / ".venv" / "bin" / "ae", "escaped")
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text(
        "#!/bin/sh\nprintf '%s' \"uv:${UV_PROJECT_ENVIRONMENT}:$*\"\n"
    )
    uv.chmod(0o755)

    result = _run(launcher, str(bin_dir), "status")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:" + str(tmp_path / "plugin" / ".ae-runtime")
        + ":run --frozen --project " + str(tmp_path / "plugin") + " ae status"
    )


def test_falls_back_to_uv_run_ae(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "uv", "uv")

    result = _run(launcher, str(bin_dir), "doctor")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:run --frozen --project " + str(tmp_path / "plugin") + " ae doctor"
    )


def test_rejects_untrusted_global_ae_fallback(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "ae", "path")

    result = _run(launcher, str(bin_dir), "status")

    assert result.returncode == 127
    assert result.stdout == ""
    assert "AE_CLI_UNTRUSTED" in result.stderr


def test_reports_actionable_error_when_cli_is_unavailable(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    result = _run(launcher, str(empty_bin), "status")

    assert result.returncode == 127
    assert result.stdout == ""
    assert "AE_CLI_UNTRUSTED" in result.stderr
    assert "uv" in result.stderr


def test_bundled_entrypoint_rejects_mutable_venv_when_uv_unavailable(
    tmp_path: Path,
) -> None:
    entrypoint = _copy_bundled_entrypoint(tmp_path)
    _write_plugin_venv_executable(tmp_path / "plugin", "bundled")
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

    assert result.returncode == 127
    assert result.stdout == ""
    assert "AE_CLI_UNTRUSTED" in result.stderr


@pytest.mark.parametrize(
    ("host_dir", "expected"),
    [(".claude", "claude-code"), (".codex", "codex")],
)
def test_bundled_entrypoint_marks_host_from_installed_plugin_path(
    tmp_path: Path,
    host_dir: str,
    expected: str,
) -> None:
    root = Path(__file__).parents[1]
    plugin = tmp_path / host_dir / "plugins" / "cache" / "auto-engineering"
    entrypoint = plugin / "bin" / "ae-run"
    delegated = plugin / "scripts" / "ae-run"
    entrypoint.parent.mkdir(parents=True)
    delegated.parent.mkdir(parents=True)
    shutil.copy2(root / "bin" / "ae-run", entrypoint)
    entrypoint.chmod(0o755)
    delegated.write_text("#!/bin/sh\nprintf '%s' \"${AE_HOST_PLATFORM:-missing}\"\n")
    delegated.chmod(0o755)

    result = subprocess.run(
        [str(entrypoint), "status"],
        env={**os.environ, "CODEX_THREAD_ID": "outer-codex"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == expected


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
