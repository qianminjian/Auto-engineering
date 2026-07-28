"""Release 归档 smoke 与真实产品安装验收分层测试。"""

from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest


def test_verify_checkpoint_lifecycle_checks_status_and_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import install_acceptance

    commands: list[list[str]] = []
    responses = iter(
        [
            CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {"thread_id": "thread-1", "stage": "architect"},
                    ensure_ascii=False,
                ),
                stderr="",
            ),
            CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {"thread_id": "thread-1", "stage": "architect"},
                    ensure_ascii=False,
                ),
                stderr="",
            ),
        ]
    )

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int = 120,
    ) -> CompletedProcess[str]:
        commands.append(command)
        return next(responses)

    monkeypatch.setattr(install_acceptance, "_run", fake_run)

    evidence = install_acceptance._verify_checkpoint_lifecycle(
        "scripts/ae-run",
        tmp_path,
        {},
        '{"thread_id": "thread-1", "stage": "architect"}\n',
    )

    assert evidence == ["status", "resume"]
    assert commands == [
        [
            "scripts/ae-run",
            "dev-loop",
            "--status",
            "--format",
            "json",
            "--project-root",
            str(tmp_path),
        ],
        [
            "scripts/ae-run",
            "dev-loop",
            "--resume",
            "thread-1",
            "--project-root",
            str(tmp_path),
        ],
    ]


def test_safe_extract_archive_extracts_regular_member(tmp_path: Path) -> None:
    from scripts.install_acceptance import _safe_extract_archive

    source = tmp_path / "source"
    source.mkdir()
    (source / "asset.txt").write_text("ok", encoding="utf-8")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(source / "asset.txt", arcname="plugin/asset.txt")

    destination = tmp_path / "destination"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as package:
        _safe_extract_archive(package, destination)

    assert (destination / "plugin/asset.txt").read_text(encoding="utf-8") == "ok"


def test_safe_extract_archive_rejects_path_traversal(tmp_path: Path) -> None:
    from scripts.install_acceptance import _safe_extract_archive

    source = tmp_path / "escape.txt"
    source.write_text("blocked", encoding="utf-8")
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        package.add(source, arcname="../escape.txt")

    destination = tmp_path / "destination"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as package:
        with pytest.raises(ValueError, match="不安全的归档路径"):
            _safe_extract_archive(package, destination)


def test_main_reports_product_install_as_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import install_acceptance

    archive = tmp_path / "release.tar.gz"
    archive.touch()
    monkeypatch.setattr(
        install_acceptance,
        "accept_archive",
        lambda archive, host, workspace: {
            "host": host,
            "archive_smoke": {
                "status": "pass",
                "evidence": ["package", "doctor", "minimal_tick"],
            },
            "product_install": {
                "status": "not_run",
                "reason": "需要在真实宿主产品内执行",
            },
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "install_acceptance.py",
            "--archive",
            str(archive),
            "--host",
            "codex",
        ],
    )

    assert install_acceptance.main() == 0
    report = json.loads(capsys.readouterr().out)

    assert report["archive_smoke"]["status"] == "pass"
    assert report["product_install"]["status"] == "not_run"
    assert report["product_install"]["reason"]
