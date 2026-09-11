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


def _write_fake_uv(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"venv\" ]; then\n"
        "  mkdir -p \"$UV_PROJECT_ENVIRONMENT/bin\"\n"
        "  touch \"$UV_PROJECT_ENVIRONMENT/bin/python\"\n"
        "  chmod +x \"$UV_PROJECT_ENVIRONMENT/bin/python\"\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s' \"{output}:$*\"\n"
    )
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


def test_release_shell_entrypoints_and_embedded_watchdog_are_parseable() -> None:
    """发布边界脚本必须通过真实 shell 与内嵌 Python 解析。"""

    root = Path(__file__).parents[1]
    shell_scripts = (
        root / "scripts/ae-run",
        root / "scripts/ae-host-run",
        root / "bin/ae-run",
    )
    for script in shell_scripts:
        result = subprocess.run(
            ["sh", "-n", str(script)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"

    source = (root / "scripts/ae-host-run").read_text(encoding="utf-8")
    watchdog = source.split("python3 - \\\n", 1)[1].split("\nPY\n", 1)[0]
    watchdog_source = watchdog.split("<<'PY'\n", 1)[1]
    compile(watchdog_source, "scripts/ae-host-run:<watchdog>", "exec")


def _run(
    launcher: Path,
    path: str,
    *args: str,
    cache_dir: Path | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environ = os.environ.copy()
    # fake uv/ae 优先，但保留 Runner 依赖的 POSIX 基础命令（mkdir/read/sleep）。
    environ["PATH"] = os.pathsep.join((path, "/usr/bin", "/bin"))
    environ.pop("UV_CACHE_DIR", None)
    if cache_dir is not None:
        environ["UV_CACHE_DIR"] = str(cache_dir)
    if env_overrides:
        environ.update(env_overrides)
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
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}")
    _write_executable(bin_dir / "ae", "path")

    result = _run(launcher, str(bin_dir), "status", "--format", "json")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:" + str(tmp_path / ".ae-state" / ".ae-runtime")
        + ":run --frozen --no-dev --project " + str(tmp_path / "plugin")
        + " ae status --format json"
    )


def test_preserves_uv_default_cache_without_rebinding_it_to_runtime(
    tmp_path: Path,
) -> None:
    """Runner 不把依赖缓存误当成项目运行时状态。"""

    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}:${UV_CACHE_DIR}")

    result = _run(launcher, str(bin_dir), "status")

    runtime = tmp_path / ".ae-state" / ".ae-runtime"
    assert result.returncode == 0
    assert result.stdout == (
        f"uv:{runtime}::run --frozen --no-dev --project "
        f"{tmp_path / 'plugin'} ae status"
    )


def test_preserves_explicit_uv_cache_override(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}:${UV_CACHE_DIR}")
    cache_dir = tmp_path / "controlled-cache"

    result = _run(launcher, str(bin_dir), "status", cache_dir=cache_dir)

    runtime = tmp_path / ".ae-state" / ".ae-runtime"
    assert result.returncode == 0
    assert result.stdout == (
        f"uv:{runtime}:{cache_dir}:run --frozen --no-dev --project "
        f"{tmp_path / 'plugin'} ae status"
    )


def test_explicit_project_root_controls_writable_runtime_location(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}:${UV_CACHE_DIR}")

    result = _run(launcher, str(bin_dir), "status", "--project-root", str(project))

    runtime = project / ".ae-state" / ".ae-runtime"
    assert result.returncode == 0
    assert result.stdout == (
        f"uv:{runtime}::run --frozen --no-dev --project "
        f"{tmp_path / 'plugin'} ae status --project-root {project}"
    )


def test_rejects_project_root_drift_from_host_invocation_root(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    invocation_root = tmp_path / "invocation"
    requested_root = tmp_path / "other-project"
    invocation_root.mkdir()
    requested_root.mkdir()
    bin_dir = tmp_path / "bin"
    _write_fake_uv(bin_dir / "uv", "unexpected")

    result = _run(
        launcher,
        str(bin_dir),
        "status",
        "--project-root",
        str(requested_root),
        env_overrides={"AE_INVOCATION_PROJECT_ROOT": str(invocation_root)},
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "AE_PROJECT_ROOT_DRIFT" in result.stderr


def test_print_runtime_root_uses_project_root_without_starting_uv(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    project = tmp_path / "project"
    project.mkdir()

    result = _run(
        launcher,
        str(tmp_path / "empty-bin"),
        "--print-runtime-root",
        "--project-root",
        str(project),
    )

    assert result.returncode == 0
    assert result.stdout.strip() == str(project / ".ae-state" / ".ae-runtime")


def test_rejects_project_root_without_value(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)

    result = _run(launcher, str(tmp_path / "empty-bin"), "status", "--project-root")

    assert result.returncode == 2
    assert "AE_PROJECT_ROOT_INVALID" in result.stderr


def test_rejects_busy_runtime_bootstrap_lock(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    (state_dir / ".ae-runtime.bootstrap.lock").mkdir()
    uv = tmp_path / "bin/uv"
    _write_fake_uv(uv, "unexpected")

    result = _run(
        launcher,
        str(tmp_path / "bin"),
        "status",
        env_overrides={"AE_RUNTIME_BOOTSTRAP_TIMEOUT": "0"},
    )

    assert result.returncode == 75
    assert "AE_RUNTIME_BUSY" in result.stderr


def test_reclaims_bootstrap_lock_owned_by_dead_process(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    lock = state_dir / ".ae-runtime.bootstrap.lock"
    lock.mkdir()
    (lock / "owner.pid").write_text("2147483647\n", encoding="utf-8")
    uv = tmp_path / "bin/uv"
    _write_fake_uv(uv, "recovered")

    result = _run(launcher, str(tmp_path / "bin"), "status")

    assert result.returncode == 0
    assert result.stdout.startswith("recovered")
    assert not lock.exists()


def test_host_module_mode_reuses_the_same_bootstrapped_runtime(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    uv = tmp_path / "bin/uv"
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}:${UV_CACHE_DIR}")

    result = _run(
        launcher,
        str(tmp_path / "bin"),
        "--run-module",
        "auto_engineering.host.codex_hooks",
        "--project-root",
        str(project),
    )

    runtime = project / ".ae-state" / ".ae-runtime"
    assert result.returncode == 0
    assert result.stdout == (
        f"uv:{runtime}::run --frozen --no-dev --project "
        f"{tmp_path / 'plugin'} python -m auto_engineering.host.codex_hooks "
        f"--project-root {project}"
    )


def test_rejects_copied_virtualenv_entrypoint_that_escapes_plugin(
    tmp_path: Path,
) -> None:
    launcher = _copy_launcher(tmp_path)
    _write_executable(tmp_path / "plugin" / ".venv" / "bin" / "ae", "escaped")
    bin_dir = tmp_path / "bin"
    uv = bin_dir / "uv"
    _write_fake_uv(uv, "uv:${UV_PROJECT_ENVIRONMENT}")

    result = _run(launcher, str(bin_dir), "status")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:" + str(tmp_path / ".ae-state" / ".ae-runtime")
        + ":run --frozen --no-dev --project " + str(tmp_path / "plugin") + " ae status"
    )


def test_falls_back_to_uv_run_ae(tmp_path: Path) -> None:
    launcher = _copy_launcher(tmp_path)
    bin_dir = tmp_path / "bin"
    _write_fake_uv(bin_dir / "uv", "uv")

    result = _run(launcher, str(bin_dir), "doctor")

    assert result.returncode == 0
    assert result.stdout == (
        "uv:run --frozen --no-dev --project " + str(tmp_path / "plugin") + " ae doctor"
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


def test_bundled_entrypoint_prefers_claude_signal_for_staged_release(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[1]
    plugin = tmp_path / "staging" / "release"
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
        env={
            **os.environ,
            "CODEX_THREAD_ID": "outer-codex",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "claude-code"


def test_bundled_entrypoint_prefers_claudecode_signal_over_outer_codex(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[1]
    plugin = tmp_path / "staging" / "release"
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
        env={
            **os.environ,
            "AE_HOST_PLATFORM": "codex",
            "CODEX_THREAD_ID": "outer-codex",
            "CLAUDECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "claude-code"


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
