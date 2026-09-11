"""双平台 Release 包完整性契约。"""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_release_builder_runs_with_documented_plain_python_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_release.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_archive_contains_both_host_adapters(tmp_path: Path) -> None:
    from scripts.build_release import REQUIRED_PATHS, build_archive

    archive = tmp_path / "auto-engineering-test.tar.gz"
    build_archive(ROOT, archive)

    with tarfile.open(archive, "r:gz") as package:
        members = {member.name.rstrip("/") for member in package.getmembers()}

    assert ".codex-plugin/plugin.json" in members
    assert ".agents/plugins/marketplace.json" in members
    assert "plugins/auto-engineering/.codex-plugin/plugin.json" in members
    assert "CLAUDE.md" in members
    assert "AGENTS.md" in members
    assert "plugins/auto-engineering/CLAUDE.md" not in members
    assert "plugins/auto-engineering/AGENTS.md" not in members
    for required in REQUIRED_PATHS:
        assert required.as_posix() in members


def test_release_embeds_one_content_addressed_build_identity(tmp_path: Path) -> None:
    from auto_engineering import __version__
    from scripts.build_release import build_archive

    archive = tmp_path / "auto-engineering-build-id.tar.gz"
    build_archive(ROOT, archive)

    with tarfile.open(archive, "r:gz") as package:
        root_file = package.extractfile("build-info.json")
        plugin_file = package.extractfile(
            "plugins/auto-engineering/build-info.json"
        )
        assert root_file is not None
        assert plugin_file is not None
        root_info = json.load(root_file)
        plugin_info = json.load(plugin_file)

    assert root_info == plugin_info
    assert root_info["version"] == __version__
    assert root_info["build_id"] != __version__
    assert root_info["build_id"].endswith(
        root_info["content_sha256"][:16]
    )


def test_release_digest_includes_generated_marketplace_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_release

    original = build_release._marketplace_manifests
    first = build_release._release_content_digest(ROOT)

    def changed_manifest(root: Path) -> tuple[dict[str, object], dict[str, object]]:
        claude, codex = original(root)
        claude = {**claude, "description": "changed"}
        return claude, codex

    monkeypatch.setattr(build_release, "_marketplace_manifests", changed_manifest)
    second = build_release._release_content_digest(ROOT)

    assert second != first


def test_release_archive_is_self_contained_dual_host_marketplace(
    tmp_path: Path,
) -> None:
    from scripts.build_release import build_archive

    archive = tmp_path / "auto-engineering-marketplace.tar.gz"
    build_archive(ROOT, archive)

    with tarfile.open(archive, "r:gz") as package:
        members = {member.name.rstrip("/") for member in package.getmembers()}
        claude_file = package.extractfile(".claude-plugin/marketplace.json")
        codex_file = package.extractfile(".agents/plugins/marketplace.json")
        assert claude_file is not None
        assert codex_file is not None
        claude_marketplace = json.load(claude_file)
        codex_marketplace = json.load(codex_file)

    plugin_root = "plugins/auto-engineering"
    assert f"{plugin_root}/.claude-plugin/plugin.json" in members
    assert f"{plugin_root}/.codex-plugin/plugin.json" in members
    assert f"{plugin_root}/skills/auto-engineering/SKILL.md" in members
    assert f"{plugin_root}/bin/ae-run" in members
    assert f"{plugin_root}/scripts/ae-run" in members
    assert f"{plugin_root}/hooks-codex.json" in members
    assert f"{plugin_root}/auto_engineering" in members
    assert claude_marketplace["description"]
    assert claude_marketplace["plugins"][0]["source"] == "./plugins/auto-engineering"
    assert (
        codex_marketplace["plugins"][0]["source"]["path"]
        == "./plugins/auto-engineering"
    )


def test_release_build_fails_when_required_path_is_missing(
    tmp_path: Path,
) -> None:
    from scripts.build_release import build_archive

    with pytest.raises(FileNotFoundError, match="Release 必需路径缺失"):
        build_archive(tmp_path, tmp_path / "broken.tar.gz")


def test_release_workflow_uses_validated_builder_without_swallowing_errors() -> None:
    content = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in content
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in content
    assert "softprops/action-gh-release@3d0d9888cb7fd7b750713d6e236d1fcb99157228" in content
    assert "needs: verify" in content
    assert "uv sync --frozen" in content
    assert "python3 scripts/build_release.py" in content
    assert "scripts/check_project_metadata.py" in content
    assert "--host claude-code" in content
    assert "--host codex" in content
    assert content.count('--wheel-cache "$(uv cache dir)"') == 2
    assert "shasum -a 256" in content
    assert "release/*.sha256" in content
    assert "|| true" not in content
    assert "2>/dev/null" not in content


def test_ci_has_independent_claude_and_codex_contract_matrix() -> None:
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert content.count("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1") == 2
    assert content.count("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9") == 2
    assert content.count("enable-cache: false") == 2
    assert "host-contract:" in content
    assert "host: claude-code" in content
    assert "host: codex" in content
    assert "scripts/build_release.py" in content
    assert "scripts/install_acceptance.py" in content
    assert '--wheel-cache "$(uv cache dir)"' in content
    assert "scripts/sync_agent_instructions.py --check" in content
    assert content.count("uv sync --frozen --extra dev --extra otel") == 2
    assert "macos-latest" in content
    acceptance = (ROOT / "scripts" / "install_acceptance.py").read_text()
    assert "check_host_package" in acceptance


def test_release_includes_install_acceptance_runner() -> None:
    from scripts.build_release import REQUIRED_PATHS

    assert Path("scripts/install_acceptance.py") in REQUIRED_PATHS
    assert Path("scripts/collect_product_evidence.py") in REQUIRED_PATHS
    assert Path("scripts/generate_business_evidence.py") in REQUIRED_PATHS
    assert Path("bin/ae-run") in REQUIRED_PATHS
    assert Path("uv.lock") in REQUIRED_PATHS


def test_host_package_rejects_retired_runtime_surface(tmp_path: Path) -> None:
    from scripts.check_host_package import check_host_package

    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "auto-engineering"}), encoding="utf-8"
    )
    for relative in (
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    stop_report = tmp_path / "auto_engineering/host/stop_report.py"
    stop_report.parent.mkdir(parents=True)
    stop_report.write_text(
        'reason_code = "HOST_SUPERVISOR_PROTOCOL_ERROR"\n',
        encoding="utf-8",
    )

    errors = check_host_package(tmp_path, "codex")

    assert any("退役运行时符号" in error for error in errors)


def test_current_host_packages_have_no_retired_runtime_surface() -> None:
    from scripts.check_host_package import check_host_package

    assert check_host_package(ROOT, "claude-code") == []
    assert check_host_package(ROOT, "codex") == []


def test_host_package_rejects_retired_nested_plugin_surface(tmp_path: Path) -> None:
    from scripts.check_host_package import check_host_package

    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "auto-engineering"}), encoding="utf-8"
    )
    for relative in (
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    nested_supervisor = (
        tmp_path
        / "plugins/auto-engineering/auto_engineering/host/supervisor.py"
    )
    nested_supervisor.parent.mkdir(parents=True)
    nested_supervisor.write_text("# retired", encoding="utf-8")

    errors = check_host_package(tmp_path, "codex")

    assert any("退役文件" in error for error in errors)


def test_host_package_rejects_retired_runtime_content_marker(tmp_path: Path) -> None:
    from scripts.check_host_package import check_host_package

    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "auto-engineering"}), encoding="utf-8"
    )
    for relative in (
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    leaked = tmp_path / "auto_engineering/loop/legacy_entry.py"
    leaked.parent.mkdir(parents=True)
    leaked.write_text(
        "from auto_engineering.host.supervisor import Supervisor\n",
        encoding="utf-8",
    )

    errors = check_host_package(tmp_path, "codex")

    assert any("已退役 Supervisor 导入" in error for error in errors)


def test_host_package_rejects_retired_nested_backend_import(tmp_path: Path) -> None:
    from scripts.check_host_package import check_host_package

    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "auto-engineering"}), encoding="utf-8"
    )
    for relative in (
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    leaked = tmp_path / "auto_engineering/host/legacy_adapter.py"
    leaked.parent.mkdir(parents=True)
    leaked.write_text(
        "from auto_engineering.host.backends import legacy\n",
        encoding="utf-8",
    )

    errors = check_host_package(tmp_path, "codex")

    assert any("已退役嵌套宿主后端导入" in error for error in errors)


def test_host_package_does_not_exclude_nested_same_named_checker(tmp_path: Path) -> None:
    from scripts.check_host_package import check_host_package

    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "auto-engineering"}), encoding="utf-8"
    )
    for relative in (
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    nested_checker = tmp_path / "auto_engineering/legacy/check_host_package.py"
    nested_checker.parent.mkdir(parents=True)
    nested_checker.write_text(
        "from auto_engineering.host.supervisor import Supervisor\n",
        encoding="utf-8",
    )

    errors = check_host_package(tmp_path, "codex")

    assert any("已退役 Supervisor 导入" in error for error in errors)


def test_documented_archive_acceptance_is_hermetic() -> None:
    """验收命令必须显式使用受控 uv 缓存，避免启动即联网解析。"""

    expected = '--wheel-cache "$(uv cache dir)"'
    for relative in (
        "AGENTS.md",
        "CLAUDE.md",
        "docs/EARS-v5.0.md",
        "design/v5.7-Protocol-Kernel-PLAN.md",
        "design/v5.8-Protocol-Kernel-Convergence-PLAN.md",
    ):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert expected in content, relative

    for relative in ("AGENTS.md", "CLAUDE.md"):
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert "uv run python scripts/sync_agent_instructions.py" in content
