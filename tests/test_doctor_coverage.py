"""Doctor 诊断、可观测性与配置向导的行为覆盖。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner


def test_version_checks_report_missing_old_and_failed_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.cli.doctor as doctor

    monkeypatch.setattr(
        doctor.sys,
        "version_info",
        SimpleNamespace(major=3, minor=11, micro=9),
    )
    assert doctor._check_python()[0] is False

    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor._check_uv()[0] is False
    assert doctor._check_git()[0] is False

    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="uv 0.4.0" if args[0][0] == "uv" else "git version 2.30.0",
        ),
    )
    assert doctor._check_uv()[0] is False
    assert doctor._check_git()[0] is False

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("broken")),
    )
    assert "检查失败" in doctor._check_uv()[1]
    assert "检查失败" in doctor._check_git()[1]

    monkeypatch.setattr(doctor.sqlite3, "sqlite_version", "3.40.0")
    assert doctor._check_sqlite3()[0] is False


def test_ae_state_and_project_profile_statuses(tmp_path: Path) -> None:
    import auto_engineering.cli.doctor as doctor

    assert doctor._check_ae_state(tmp_path)[0] is False
    ok, message = doctor._check_project_profile(tmp_path)
    assert ok is True
    assert "setup_required" in message

    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "init-manifest.json").write_text("{broken")
    ok, message = doctor._check_project_profile(tmp_path)
    assert ok is False
    assert "ProjectProfile legacy" in message
    assert "LEGACY_PROFILE_INVALID" in message


def test_project_profile_doctor_reports_resolved(tmp_path: Path) -> None:
    import auto_engineering.cli.doctor as doctor

    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n',
    )

    ok, message = doctor._check_project_profile(tmp_path)

    assert ok is True
    assert "ProjectProfile resolved" in message
    assert "sha256:" in message


def test_project_profile_doctor_reports_config_conflict(tmp_path: Path) -> None:
    import auto_engineering.cli.doctor as doctor

    (tmp_path / "ae.toml").write_text("[project\n")

    ok, message = doctor._check_project_profile(tmp_path)

    assert ok is False
    assert "ProjectProfile conflict" in message
    assert "PROJECT_PROFILE_INVALID" in message


def test_pr_backend_detects_available_and_missing_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.cli.doctor as doctor

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if command[0] == "gh":
            return SimpleNamespace(returncode=0)
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(doctor.subprocess, "run", run)
    assert "gh" in doctor._check_pr_backend()[1]

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    assert "均未安装" in doctor._check_pr_backend()[1]


@pytest.mark.parametrize(
    ("endpoint", "connection_result", "expected"),
    [
        ("", None, "disabled"),
        ("http://localhost:4317", None, "connected"),
        ("http://bad:9999", OSError("down"), "unreachable"),
    ],
)
def test_otlp_connectivity_states(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    connection_result: Exception | None,
    expected: str,
) -> None:
    import socket

    import auto_engineering.cli.doctor as doctor

    monkeypatch.setenv("AE_OTLP_ENDPOINT", endpoint)

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def connect(*args: object, **kwargs: object) -> Connection:
        if connection_result is not None:
            raise connection_result
        return Connection()

    monkeypatch.setattr(socket, "create_connection", connect)

    assert doctor._check_otlp_connectivity() == expected
    if endpoint:
        assert ":" in doctor._otlp_status_text()
    else:
        assert "未设置" in doctor._otlp_status_text()


def test_optional_features_reports_otlp_and_learning_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.cli.doctor as doctor
    import auto_engineering.config.feature_flags as flags

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ae.toml").write_text("")
    status = {
        feature.key: {
            "active": feature.key in {"AE_METRICS", "AE_OTLP_ENDPOINT", "AE_STRICT_RED"},
            "agent_mode": feature.agent_mode,
            "activation": feature.activation,
        }
        for feature in flags.FEATURE_MANIFEST
    }
    monkeypatch.setattr(flags, "get_feature_status", lambda: status)
    monkeypatch.setattr(flags, "_count_requirements", lambda: 35)
    monkeypatch.setattr(doctor, "_check_otlp_connectivity", lambda: "connected")
    monkeypatch.setattr(doctor, "_otlp_status_text", lambda: "localhost:4317")

    lines = doctor.render_optional_features()
    texts = [line for _, line in lines]

    assert any("collector 已连接" in line for line in texts)
    assert any("贝叶斯阈值学习: ✓" in line for line in texts)
    assert any("仅 agent only" in line for line in texts)

    monkeypatch.setattr(doctor, "_check_otlp_connectivity", lambda: "unreachable")
    texts = [line for _, line in doctor.render_optional_features()]
    assert any("collector 不可达" in line for line in texts)
    assert any("setup-observability" in line for line in texts)


def test_setup_observability_handles_no_docker_and_running_collector(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import auto_engineering.cli.doctor as doctor

    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    doctor._setup_observability()
    assert "Docker 未安装" in capsys.readouterr().out

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(doctor, "_check_otlp_connectivity", lambda: "connected")
    monkeypatch.setattr(doctor, "_otlp_status_text", lambda: "localhost:4317")
    doctor._setup_observability()
    assert "已在运行" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("result", "raises", "expected"),
    [
        (SimpleNamespace(returncode=1, stderr="compose failed"), None, "启动失败"),
        (None, OSError("docker broken"), "执行失败"),
    ],
)
def test_setup_observability_reports_start_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: SimpleNamespace | None,
    raises: Exception | None,
    expected: str,
) -> None:
    import auto_engineering.cli.doctor as doctor

    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(doctor, "_check_otlp_connectivity", lambda: "unreachable")

    def run(*args: object, **kwargs: object) -> SimpleNamespace:
        if raises is not None:
            raise raises
        assert result is not None
        return result

    monkeypatch.setattr(doctor.subprocess, "run", run)
    doctor._setup_observability()
    assert expected in capsys.readouterr().out


def test_setup_observability_waits_until_connected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import time

    import auto_engineering.cli.doctor as doctor

    states = iter(["unreachable", "unreachable", "connected"])
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(doctor, "_check_otlp_connectivity", lambda: next(states))
    monkeypatch.setattr(doctor, "_otlp_status_text", lambda: "localhost:4317")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    doctor._setup_observability()

    assert "collector 已启动" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("result", "raises", "expected"),
    [
        (SimpleNamespace(returncode=0, stderr=""), None, "已停止"),
        (SimpleNamespace(returncode=1, stderr="failed"), None, "停止失败"),
        (None, subprocess.TimeoutExpired("docker", 30), "执行失败"),
    ],
)
def test_teardown_observability_reports_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: SimpleNamespace | None,
    raises: Exception | None,
    expected: str,
) -> None:
    import auto_engineering.cli.doctor as doctor

    def run(*args: object, **kwargs: object) -> SimpleNamespace:
        if raises is not None:
            raise raises
        assert result is not None
        return result

    monkeypatch.setattr(doctor.subprocess, "run", run)
    doctor._teardown_observability()
    assert expected in capsys.readouterr().out


def test_init_config_refuses_to_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import auto_engineering.cli.doctor as doctor

    (tmp_path / "ae.toml").write_text("existing")

    doctor._init_config(tmp_path)

    assert (tmp_path / "ae.toml").read_text() == "existing"
    assert "已存在" in capsys.readouterr().out


def test_wizard_can_cancel_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import auto_engineering.cli.doctor as doctor

    monkeypatch.setattr(doctor.click, "prompt", lambda *args, **kwargs: "N")
    monkeypatch.setattr(doctor.click, "confirm", lambda *args, **kwargs: False)

    doctor._run_wizard(tmp_path)

    assert not (tmp_path / "ae.toml").exists()
    assert "已取消" in capsys.readouterr().out


def test_wizard_enables_categories_and_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.cli.doctor as doctor

    monkeypatch.setattr(doctor.click, "prompt", lambda *args, **kwargs: "y")
    monkeypatch.setattr(doctor.click, "confirm", lambda *args, **kwargs: True)

    doctor._run_wizard(tmp_path)

    content = (tmp_path / "ae.toml").read_text()
    assert "[observability]" in content
    assert 'metrics = "1"' in content
    assert "AE_METRICS" in content


@pytest.mark.parametrize(
    ("option", "target"),
    [
        ("--wizard", "_run_wizard"),
        ("--init-config", "_init_config"),
        ("--setup-observability", "_setup_observability"),
        ("--teardown-observability", "_teardown_observability"),
    ],
)
def test_doctor_command_dispatches_maintenance_options(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    target: str,
) -> None:
    import auto_engineering.cli.doctor as doctor
    from auto_engineering.cli import main

    called: list[object] = []
    monkeypatch.setattr(
        doctor,
        target,
        lambda *args, **kwargs: called.append(args),
    )

    result = CliRunner().invoke(main, ["doctor", option])

    assert result.exit_code == 0
    assert called


def test_doctor_acceptance_profile_fails_without_token_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.cli import main

    monkeypatch.setenv("AE_METRICS", "1")
    monkeypatch.setenv("AE_AUDIT_LOG", "1")
    monkeypatch.setenv("AE_TOKEN_TRACKING", "0")

    result = CliRunner().invoke(
        main,
        ["doctor", "--acceptance-profile", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "AE_TOKEN_TRACKING=1" in result.output


def test_doctor_acceptance_profile_passes_with_complete_evidence_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.cli import main

    monkeypatch.setenv("AE_METRICS", "1")
    monkeypatch.setenv("AE_AUDIT_LOG", "1")
    monkeypatch.setenv("AE_TOKEN_TRACKING", "1")

    result = CliRunner().invoke(
        main,
        ["doctor", "--acceptance-profile", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "真实产品验收前置条件已满足" in result.output
