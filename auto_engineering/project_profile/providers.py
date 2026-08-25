"""ProjectProfile Provider SPI 与有限本地探测。"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from auto_engineering.project_profile.models import (
    ProfileEvidence,
    ProjectProfileError,
    ProjectProfileErrorCode,
)


@dataclass(frozen=True, slots=True)
class ProfileContribution:
    """单个 Provider 提供的候选事实，不是最终 Profile。"""

    provider: str
    priority: int
    project_type: str | None = None
    languages: tuple[str, ...] = ()
    package_manager: str | None = None
    source_roots: tuple[str, ...] = ()
    test_roots: tuple[str, ...] = ()
    design_roots: tuple[str, ...] = ()
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    missing_capabilities: tuple[str, ...] = ()
    evidence: tuple[ProfileEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider or self.priority < 0:
            raise ValueError("Provider 名称和优先级无效")

    def with_synthetic_evidence(self) -> ProfileContribution:
        """测试/内存 Provider 使用的确定性证据；生产 Provider 应引用真实入口。"""
        if self.evidence:
            return self
        payload = repr(
            (
                self.provider,
                self.project_type,
                self.languages,
                self.package_manager,
                self.source_roots,
                self.test_roots,
                self.design_roots,
                sorted(self.commands.items()),
            )
        ).encode("utf-8")
        evidence = ProfileEvidence(
            source=f".ae-state/provider-{self.provider}",
            digest=hashlib.sha256(payload).hexdigest(),
            facts=(f"provider:{self.provider}",),
        )
        return replace(self, evidence=(evidence,))


class ProjectProfileProvider(Protocol):
    name: str
    priority: int

    def inspect(self, project_root: Path) -> ProfileContribution:
        ...


class LocalProbeProvider:
    """只读取固定工程入口文件，不递归扫描项目。"""

    name = "local_probe"
    priority = 200
    MAX_ENTRY_BYTES = 1024 * 1024
    _ENTRY_NAMES = (
        "Cargo.toml",
        "go.mod",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "tsconfig.json",
        "uv.lock",
        "yarn.lock",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "eslint.config.ts",
        "vitest.config.js",
        "vitest.config.ts",
        "vitest.config.mjs",
        "vitest.config.mts",
    )

    def _read_entry(self, project_root: Path, name: str) -> tuple[bytes, ProfileEvidence] | None:
        path = project_root / name
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > self.MAX_ENTRY_BYTES:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"项目入口文件超过 {self.MAX_ENTRY_BYTES} 字节上限: {name}",
            )
        content = path.read_bytes()
        return content, ProfileEvidence(
            source=name,
            digest=hashlib.sha256(content).hexdigest(),
            facts=(f"entry:{name}",),
        )

    @staticmethod
    def _existing_roots(project_root: Path, candidates: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in candidates if (project_root / name).is_dir())

    def inspect(self, project_root: Path) -> ProfileContribution:
        entries: dict[str, bytes] = {}
        evidence: list[ProfileEvidence] = []
        for name in self._ENTRY_NAMES:
            inspected = self._read_entry(project_root, name)
            if inspected is not None:
                entries[name], item = inspected
                evidence.append(item)

        languages: list[str] = []
        package_manager: str | None = None
        project_type: str | None = None
        source_roots: list[str] = []
        test_roots = list(self._existing_roots(project_root, ("tests", "test", "__tests__")))
        design_roots = list(self._existing_roots(project_root, ("design", "docs")))
        commands: dict[str, tuple[str, ...]] = {}
        missing_capabilities: list[str] = []

        if "package.json" in entries:
            try:
                package = json.loads(entries["package.json"])
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProjectProfileError(
                    ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                    f"package.json 无法解析: {exc}",
                ) from exc
            if not isinstance(package, dict):
                raise ProjectProfileError(
                    ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                    "package.json 顶层必须为 object",
                )
            languages.append("typescript" if "tsconfig.json" in entries else "javascript")
            project_type = "web_application"
            package_manager = self._node_package_manager(entries)
            source_roots.extend(self._existing_roots(project_root, ("src", "app", "lib")))
            scripts = package.get("scripts", {})
            if isinstance(scripts, dict):
                commands.update(
                    self._node_commands(
                        scripts,
                        package_manager,
                        has_tsconfig="tsconfig.json" in entries,
                        has_local_typescript=self._has_node_dependency(
                            package, "typescript"
                        ),
                    )
                )
            dependencies = {
                **(package.get("dependencies", {}) if isinstance(package.get("dependencies"), dict) else {}),
                **(package.get("devDependencies", {}) if isinstance(package.get("devDependencies"), dict) else {}),
            }
            eslint_version = str(dependencies.get("eslint", ""))
            has_flat_config = any(name.startswith("eslint.config.") for name in entries)
            requires_flat_config = bool(
                re.search(r"(?:^|[^0-9])9(?:\.|$)", eslint_version)
                or eslint_version.strip().lower() in {"latest", "next"}
            )
            if requires_flat_config and not has_flat_config:
                missing_capabilities.append("eslint_flat_config")
            elif requires_flat_config and has_flat_config:
                flat_config = b"\n".join(
                    content for name, content in entries.items()
                    if name.startswith("eslint.config.")
                ).decode("utf-8", errors="replace")
                compact_config = re.sub(r"\s+", "", flat_config)
                if re.fullmatch(
                    r"exportdefault(?:\[\]|\[\{\}\]);?",
                    compact_config,
                ):
                    missing_capabilities.append("eslint_effective_config")
            vitest_config = b"\n".join(
                content for name, content in entries.items()
                if name.startswith("vitest.config.")
            ).decode("utf-8", errors="replace")
            if re.search(r"environment\s*:\s*['\"]jsdom['\"]", vitest_config) and "jsdom" not in dependencies:
                missing_capabilities.append("jsdom_dependency")

        if "pyproject.toml" in entries:
            try:
                pyproject = tomllib.loads(entries["pyproject.toml"].decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise ProjectProfileError(
                    ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                    f"pyproject.toml 无法解析: {exc}",
                ) from exc
            languages.append("python")
            project_type = project_type or "application"
            package_manager = package_manager or ("uv" if "uv.lock" in entries else None)
            source_roots.extend(self._python_roots(project_root, pyproject))
            tool = pyproject.get("tool")
            if isinstance(tool, dict) and isinstance(tool.get("pytest"), dict):
                commands["test"] = ("python", "-m", "pytest")

        if "go.mod" in entries:
            languages.append("go")
            project_type = project_type or "application"
            source_roots.extend(self._existing_roots(project_root, ("cmd", "internal", "pkg")))

        if "Cargo.toml" in entries:
            languages.append("rust")
            project_type = project_type or "application"
            package_manager = package_manager or "cargo"
            source_roots.extend(self._existing_roots(project_root, ("src",)))

        return ProfileContribution(
            provider=self.name,
            priority=self.priority,
            project_type=project_type,
            languages=tuple(dict.fromkeys(languages)),
            package_manager=package_manager,
            source_roots=tuple(dict.fromkeys(source_roots)),
            test_roots=tuple(test_roots),
            design_roots=tuple(design_roots),
            commands=commands,
            missing_capabilities=tuple(missing_capabilities),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _node_package_manager(entries: Mapping[str, bytes]) -> str:
        if "pnpm-lock.yaml" in entries:
            return "pnpm"
        if "yarn.lock" in entries:
            return "yarn"
        return "npm"

    @staticmethod
    def _has_node_dependency(package: Mapping[object, object], name: str) -> bool:
        for field_name in ("dependencies", "devDependencies"):
            dependencies = package.get(field_name)
            if isinstance(dependencies, Mapping) and name in dependencies:
                return True
        return False

    @staticmethod
    def _node_commands(
        scripts: Mapping[object, object],
        package_manager: str,
        *,
        has_tsconfig: bool = False,
        has_local_typescript: bool = False,
    ) -> dict[str, tuple[str, ...]]:
        aliases = {
            "lint": ("lint",),
            "type_check": ("typecheck", "type-check", "check-types"),
            "test": ("test",),
            "build": ("build",),
        }
        commands: dict[str, tuple[str, ...]] = {}
        for capability, candidates in aliases.items():
            script = None
            for candidate in candidates:
                value = scripts.get(candidate)
                if isinstance(value, str) and value.strip():
                    script = candidate
                    break
            if script is not None:
                commands[capability] = (package_manager, "run", script)
        if (
            "type_check" not in commands
            and has_tsconfig
            and has_local_typescript
        ):
            if package_manager == "npm":
                commands["type_check"] = (
                    "npm", "exec", "--", "tsc", "--noEmit"
                )
            else:
                commands["type_check"] = (
                    package_manager, "exec", "tsc", "--noEmit"
                )
        return commands

    @staticmethod
    def _python_roots(project_root: Path, pyproject: Mapping[str, object]) -> tuple[str, ...]:
        roots = list(LocalProbeProvider._existing_roots(project_root, ("src",)))
        project = pyproject.get("project")
        if isinstance(project, dict):
            name = project.get("name")
            if isinstance(name, str) and name.strip():
                package_name = re.sub(r"[-.]+", "_", name.strip())
                if (project_root / package_name).is_dir():
                    roots.append(package_name)
        return tuple(dict.fromkeys(roots))


__all__ = [
    "LocalProbeProvider",
    "ProfileContribution",
    "ProjectProfileProvider",
]
