"""双平台 Release 包完整性契约。"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_release_archive_contains_both_host_adapters(tmp_path: Path) -> None:
    from scripts.build_release import REQUIRED_PATHS, build_archive

    archive = tmp_path / "auto-engineering-test.tar.gz"
    build_archive(ROOT, archive)

    with tarfile.open(archive, "r:gz") as package:
        members = {member.name.rstrip("/") for member in package.getmembers()}

    assert ".codex-plugin/plugin.json" in members
    for required in REQUIRED_PATHS:
        assert required.as_posix() in members


def test_release_build_fails_when_required_path_is_missing(
    tmp_path: Path,
) -> None:
    from scripts.build_release import build_archive

    with pytest.raises(FileNotFoundError, match="Release 必需路径缺失"):
        build_archive(tmp_path, tmp_path / "broken.tar.gz")


def test_release_workflow_uses_validated_builder_without_swallowing_errors() -> None:
    content = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    assert "python3 scripts/build_release.py" in content
    assert "|| true" not in content
    assert "2>/dev/null" not in content


def test_ci_has_independent_claude_and_codex_contract_matrix() -> None:
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "host-contract:" in content
    assert "host: claude-code" in content
    assert "host: codex" in content
    assert "scripts/build_release.py" in content
    assert "scripts/install_acceptance.py" in content
    assert "scripts/sync_agent_instructions.py --check" in content
    acceptance = (ROOT / "scripts" / "install_acceptance.py").read_text()
    assert "check_host_package" in acceptance


def test_release_includes_install_acceptance_runner() -> None:
    from scripts.build_release import REQUIRED_PATHS

    assert Path("scripts/install_acceptance.py") in REQUIRED_PATHS
