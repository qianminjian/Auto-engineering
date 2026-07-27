"""Release 归档 smoke 与真实产品安装验收分层测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


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
