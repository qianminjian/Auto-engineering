"""多 Provider ProjectProfile 确定性解析与冲突治理。"""

from __future__ import annotations

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

    def resolve(self, project_root: Path) -> ProjectProfileResolution:
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
        missing: list[str] = []
        if not languages:
            missing.append("primary_language")
        if not source_roots:
            missing.append("source_roots")
        if not commands.get("test"):
            missing.append("test_command")
        if missing and (not languages or not source_roots):
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
