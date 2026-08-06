"""T360-T361 Provider SPI、Resolver 与有限本地探测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.project_profile import (
    LegacyInitProvider,
    ProjectProfileError,
    ProjectProfileErrorCode,
)
from auto_engineering.project_profile.config_provider import AeConfigProvider
from auto_engineering.project_profile.providers import LocalProbeProvider, ProfileContribution
from auto_engineering.project_profile.resolver import ProjectProfileResolver, ResolutionStatus


class _StaticProvider:
    def __init__(self, name: str, priority: int, contribution: ProfileContribution) -> None:
        self.name = name
        self.priority = priority
        self._contribution = contribution

    def inspect(self, project_root: Path) -> ProfileContribution:
        return self._contribution


def _contribution(
    *,
    provider: str,
    priority: int,
    language: str = "typescript",
    source_root: str = "src",
) -> ProfileContribution:
    return ProfileContribution(
        provider=provider,
        priority=priority,
        project_type="web_application",
        languages=(language,),
        package_manager="npm" if language == "typescript" else None,
        source_roots=(source_root,),
        test_roots=("tests",),
        design_roots=("design",),
        commands={"test": ("npm", "run", "test")},
        evidence=(),
    ).with_synthetic_evidence()


def test_resolver_prefers_higher_authority_and_preserves_evidence(tmp_path: Path) -> None:
    explicit = _StaticProvider("ae_config", 300, _contribution(provider="ae_config", priority=300))
    local = _StaticProvider(
        "local_probe",
        200,
        _contribution(provider="local_probe", priority=200, language="javascript"),
    )

    result = ProjectProfileResolver((local, explicit)).resolve(tmp_path)

    assert result.status is ResolutionStatus.RESOLVED
    assert result.profile is not None
    assert result.profile.languages == ("typescript",)
    assert result.profile.resolution.providers == ("ae_config", "local_probe")
    assert {item.source for item in result.profile.evidence} == {
        ".ae-state/provider-ae_config",
        ".ae-state/provider-local_probe",
    }


def test_resolver_rejects_same_priority_conflict(tmp_path: Path) -> None:
    first = _StaticProvider("first", 200, _contribution(provider="first", priority=200))
    second = _StaticProvider(
        "second",
        200,
        _contribution(provider="second", priority=200, language="python"),
    )

    with pytest.raises(ProjectProfileError) as exc_info:
        ProjectProfileResolver((first, second)).resolve(tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT
    assert "languages" in str(exc_info.value)


def test_resolver_returns_setup_required_for_empty_project(tmp_path: Path) -> None:
    result = ProjectProfileResolver((LocalProbeProvider(),)).resolve(tmp_path)

    assert result.status is ResolutionStatus.SETUP_REQUIRED
    assert result.profile is None
    assert result.missing_capabilities == (
        "primary_language",
        "source_roots",
        "test_command",
    )


def test_legacy_manifest_is_read_only_profile_input(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    manifest_path = state_dir / "init-manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "1.0",
        "project_type": "app-service",
        "language": "python",
        "structure": {"source_root": "src/", "test_root": "tests/"},
        "conventions": {
            "linter": "ruff check .",
            "type_checker": "mypy src",
            "test_runner": "pytest -q",
        },
    }))
    before = manifest_path.stat().st_mtime_ns

    result = ProjectProfileResolver((LegacyInitProvider(),)).resolve(tmp_path)

    assert result.status is ResolutionStatus.RESOLVED
    assert result.profile is not None
    assert result.profile.languages == ("python",)
    assert result.profile.source_roots == ("src",)
    assert result.profile.commands["test"] == ("pytest", "-q")
    assert result.profile.resolution.providers == ("legacy_init",)
    assert result.profile.evidence[0].facts == ("compat:legacy_init",)
    assert manifest_path.stat().st_mtime_ns == before


def test_invalid_legacy_manifest_has_stable_error(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    (state_dir / "init-manifest.json").write_text("{broken")

    with pytest.raises(ProjectProfileError) as exc_info:
        LegacyInitProvider().inspect(tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.LEGACY_PROFILE_INVALID


def test_local_probe_reads_node_entry_files_and_declared_scripts(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "design").mkdir()
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "scripts": {
                    "lint": "eslint .",
                    "typecheck": "tsc --noEmit",
                    "test": "vitest run",
                    "build": "vite build",
                },
            }
        ),
        encoding="utf-8",
    )

    result = ProjectProfileResolver((LocalProbeProvider(),)).resolve(tmp_path)

    assert result.status is ResolutionStatus.RESOLVED
    assert result.profile is not None
    assert result.profile.languages == ("typescript",)
    assert result.profile.package_manager == "npm"
    assert result.profile.commands == {
        "build": ("npm", "run", "build"),
        "lint": ("npm", "run", "lint"),
        "test": ("npm", "run", "test"),
        "type_check": ("npm", "run", "typecheck"),
    }
    assert {item.source for item in result.profile.evidence} == {
        "package-lock.json",
        "package.json",
        "tsconfig.json",
    }


def test_local_probe_derives_pnpm_type_check_from_local_typescript(tmp_path: Path) -> None:
    """无 typecheck script 时，只从本地 TypeScript 依赖推导 pnpm 原生命令。"""
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"typescript": "^5.8.0"}, "scripts": {}}),
        encoding="utf-8",
    )

    contribution = LocalProbeProvider().inspect(tmp_path)

    assert contribution.commands["type_check"] == (
        "pnpm", "exec", "tsc", "--noEmit",
    )


def test_local_probe_does_not_guess_tsc_without_local_dependency(tmp_path: Path) -> None:
    """只有 tsconfig 不足以证明全局或本地 tsc 可执行。"""
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {}}), encoding="utf-8"
    )

    contribution = LocalProbeProvider().inspect(tmp_path)

    assert "type_check" not in contribution.commands


@pytest.mark.parametrize(
    ("entry", "content", "source_root", "language"),
    [
        ("pyproject.toml", '[project]\nname = "demo-app"\n', "demo_app", "python"),
        ("go.mod", "module example.com/demo\n\ngo 1.24\n", "cmd", "go"),
        ("Cargo.toml", '[package]\nname = "demo"\nversion = "0.1.0"\n', "src", "rust"),
    ],
)
def test_local_probe_supports_bounded_language_entries(
    tmp_path: Path,
    entry: str,
    content: str,
    source_root: str,
    language: str,
) -> None:
    (tmp_path / source_root).mkdir()
    (tmp_path / entry).write_text(content, encoding="utf-8")

    contribution = LocalProbeProvider().inspect(tmp_path)

    assert contribution.languages == (language,)
    assert contribution.source_roots == (source_root,)
    assert tuple(item.source for item in contribution.evidence) == (entry,)


def test_local_probe_rejects_oversized_entry_file(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_bytes(b"x" * (LocalProbeProvider.MAX_ENTRY_BYTES + 1))

    with pytest.raises(ProjectProfileError) as exc_info:
        LocalProbeProvider().inspect(tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_INVALID


def test_ae_config_provider_reads_explicit_project_capabilities(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "vitest run"}}',
        encoding="utf-8",
    )
    (tmp_path / "ae.toml").write_text(
        """
[project]
type = "web_application"
languages = ["typescript"]
package_manager = "pnpm"
source_roots = ["frontend"]
test_roots = []
design_roots = ["design"]

[project.commands]
test = ["pnpm", "run", "test"]
""".strip(),
        encoding="utf-8",
    )

    contribution = AeConfigProvider().inspect(tmp_path)

    assert contribution.languages == ("typescript",)
    assert contribution.source_roots == ("frontend",)
    assert contribution.commands == {"test": ("pnpm", "run", "test")}
    assert contribution.evidence[0].source == "ae.toml"


def test_ae_config_rejects_missing_declared_package_script(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    (tmp_path / "ae.toml").write_text(
        """
[project]
type = "web_application"
languages = ["typescript"]
source_roots = ["src"]

[project.commands]
test = ["npm", "run", "test"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ProjectProfileError) as exc_info:
        AeConfigProvider().inspect(tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT
