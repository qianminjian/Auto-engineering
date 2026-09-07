"""多 Provider ProjectProfile 确定性解析与冲突治理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from auto_engineering.project_profile.models import (
    PROJECT_PROFILE_SCHEMA_VERSION,
    ProfileEvidence,
    ProjectProfile,
    ProjectProfileError,
    ProjectProfileErrorCode,
)
from auto_engineering.project_profile.providers import ProfileContribution, ProjectProfileProvider


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    SETUP_REQUIRED = "setup_required"


@dataclass(frozen=True, slots=True)
class ProjectProfileResolution:
    status: ResolutionStatus
    profile: ProjectProfile | None
    missing_capabilities: tuple[str, ...] = ()


class ProjectProfileResolver:
    def __init__(self, providers: tuple[ProjectProfileProvider, ...]) -> None:
        self.providers = providers

    @staticmethod
    def _select_scalar(
        field: str,
        contributions: list[ProfileContribution],
    ) -> Any | None:
        candidates = [
            (item.priority, item.provider, getattr(item, field))
            for item in contributions
            if getattr(item, field) not in (None, (), "")
        ]
        if not candidates:
            return None
        highest = max(priority for priority, _, _ in candidates)
        peers = [(provider, value) for priority, provider, value in candidates if priority == highest]
        values = {repr(value) for _, value in peers}
        if len(values) > 1:
            sources = ", ".join(provider for provider, _ in sorted(peers))
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT,
                f"ProjectProfile 字段 {field} 在同级 Provider 冲突: {sources}",
            )
        return sorted(peers, key=lambda item: item[0])[0][1]

    @staticmethod
    def _merge_commands(contributions: list[ProfileContribution]) -> dict[str, tuple[str, ...]]:
        names = sorted({name for item in contributions for name in item.commands})
        result: dict[str, tuple[str, ...]] = {}
        for name in names:
            candidates = [
                (item.priority, item.provider, item.commands[name])
                for item in contributions
                if name in item.commands
            ]
            highest = max(priority for priority, _, _ in candidates)
            peers = [(provider, value) for priority, provider, value in candidates if priority == highest]
            if len({value for _, value in peers}) > 1:
                sources = ", ".join(provider for provider, _ in sorted(peers))
                raise ProjectProfileError(
                    ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT,
                    f"ProjectProfile 命令 {name} 在同级 Provider 冲突: {sources}",
                )
            result[name] = sorted(peers, key=lambda item: item[0])[0][1]
        return result

    @staticmethod
    def _design_toolchain_requirement(
        project_root: Path,
        design_doc_path: str | Path | None,
    ) -> str | None:
        """从 binding 设计中识别必须先建立的前端工具链。

        这不是从自然语言猜框架：只有设计明确同时声明 Vite、React 和
        TypeScript 时才产生能力约束。这样可以阻止 ``pyproject.toml`` 等
        偶然存在的入口把业务工程误判为 Python，而不替代设计文档对架构的
        权威性。
        """

        if design_doc_path is None:
            return None
        candidate = Path(design_doc_path)
        resolved = (candidate if candidate.is_absolute() else project_root / candidate).resolve()
        try:
            if not resolved.is_relative_to(project_root.resolve()):
                return None
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        if len(content.encode("utf-8")) > 1024 * 1024:
            return None
        normalized = content.casefold()
        if all(re.search(rf"(?<![\w-]){term}(?![\w-])", normalized) for term in ("vite", "react", "typescript")):
            return "node_typescript"
        return None

    def resolve(
        self,
        project_root: Path,
        *,
        design_doc_path: str | Path | None = None,
        require_test_command: bool = True,
    ) -> ProjectProfileResolution:
        contributions = [provider.inspect(project_root) for provider in self.providers]
        active = [
            item
            for item in contributions
            if item.evidence
            or item.project_type
            or item.languages
            or item.source_roots
            or item.commands
        ]
        languages = self._select_scalar("languages", active)
        source_roots = self._select_scalar("source_roots", active)
        commands = self._merge_commands(active)
        design_toolchain = self._design_toolchain_requirement(
            project_root,
            design_doc_path,
        )
        missing: list[str] = []
        if not languages:
            missing.append("primary_language")
        if not source_roots:
            missing.append("source_roots")
        if (
            (
                require_test_command
                or design_toolchain == "node_typescript"
                or (not languages and not source_roots)
            )
            and not commands.get("test")
        ):
            missing.append("test_command")
        if design_toolchain == "node_typescript" and "typescript" not in (languages or ()):
            missing.append("design_toolchain:node_typescript")
        missing.extend(
            capability
            for item in active
            for capability in item.missing_capabilities
            if capability not in missing
        )
        # A partial profile must not be treated as executable.  In
        # particular, a project with source roots but no verified test
        # command used to reach Architect/Developer directly, where the
        # Worker could only fail after writing business files.  All missing
        # capabilities are setup prerequisites; the setup Action is the
        # single place allowed to establish and re-probe them.
        if missing:
            return ProjectProfileResolution(
                status=ResolutionStatus.SETUP_REQUIRED,
                profile=None,
                missing_capabilities=tuple(missing),
            )

        evidence = self._merge_evidence(active)
        providers = tuple(
            item.provider
            for item in sorted(active, key=lambda item: (-item.priority, item.provider))
        )
        payload = {
            "schema_version": PROJECT_PROFILE_SCHEMA_VERSION,
            "project": {
                "type": self._select_scalar("project_type", active) or "application",
                "languages": list(languages or ()),
                "package_manager": self._select_scalar("package_manager", active),
            },
            "paths": {
                "source_roots": list(source_roots or ()),
                "test_roots": list(self._select_scalar("test_roots", active) or ()),
                "design_roots": list(self._select_scalar("design_roots", active) or ()),
            },
            "commands": {name: list(command) for name, command in commands.items()},
            "evidence": [
                {"source": item.source, "digest": item.digest, "facts": list(item.facts)}
                for item in evidence
            ],
            "resolution": {
                "providers": list(providers),
                "confidence": "confirmed" if not missing else "partial",
            },
        }
        return ProjectProfileResolution(
            status=ResolutionStatus.RESOLVED,
            profile=ProjectProfile.from_dict(payload, project_root=project_root),
            missing_capabilities=tuple(missing),
        )

    @staticmethod
    def _merge_evidence(contributions: list[ProfileContribution]) -> tuple[ProfileEvidence, ...]:
        items: dict[tuple[str, str], ProfileEvidence] = {}
        for contribution in contributions:
            for evidence in contribution.evidence:
                items[(evidence.source, evidence.digest)] = evidence
        return tuple(items[key] for key in sorted(items))


__all__ = [
    "ProjectProfileResolution",
    "ProjectProfileResolver",
    "ResolutionStatus",
]
