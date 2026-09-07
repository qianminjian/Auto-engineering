"""Build Identity 预检命令的行为契约。"""

from __future__ import annotations

import json

from click.testing import CliRunner

from auto_engineering import __version__
from auto_engineering.cli import main


def test_build_info_exposes_content_addressed_identity_without_starting_loop(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["build-info"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["version"] == __version__
    assert payload["build_id"].startswith(f"{__version__}+")
    assert payload["source_kind"] in {"source", "packaged"}
    assert ".ae-state" not in result.output


def test_build_info_is_visible_from_main_help() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "build-info" in result.output


def test_build_info_fails_closed_when_expected_identity_differs(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["build-info", "--expect-build-id", "old-build"])

    assert result.exit_code != 0
    assert "Build Identity 不匹配" in result.output
