"""Init Engineering manifest 的只读兼容 Provider。"""

from __future__ import annotations

import hashlib
import shlex
from pathlib import Path

from auto_engineering.loop.init_contract import load_init_manifest, validate_init_manifest
from auto_engineering.project_profile.models import (
    ProfileEvidence,
    ProjectProfileError,
    ProjectProfileErrorCode,
)
from auto_engineering.project_profile.providers import ProfileContribution


class LegacyInitProvider:
    name = "legacy_init"
    priority = 100

    def inspect(self, project_root: Path) -> ProfileContribution:
        path = project_root / ".ae-state" / "init-manifest.json"
        if not path.is_file():
            return ProfileContribution(provider=self.name, priority=self.priority)
        content = path.read_bytes()
        manifest = load_init_manifest(project_root)
        if manifest is None:
            raise ProjectProfileError(
                ProjectProfileErrorCode.LEGACY_PROFILE_INVALID,
                "旧版 init-manifest.json 无法读取",
            )
        validation = validate_init_manifest(manifest)
        if not validation.ok:
            raise ProjectProfileError(
                ProjectProfileErrorCode.LEGACY_PROFILE_INVALID,
                "; ".join(validation.errors),
            )
        structure = manifest.get("structure", {})
        conventions = manifest.get("conventions", {})
        commands: dict[str, tuple[str, ...]] = {}
        if isinstance(conventions, dict):
            for legacy_name, capability in (
                ("linter", "lint"),
                ("type_checker", "type_check"),
                ("test_runner", "test"),
                ("build_cmd", "build"),
            ):
                command = conventions.get(legacy_name)
                if isinstance(command, str) and command.strip():
                    commands[capability] = tuple(shlex.split(command))
        source_root = structure.get("source_root") if isinstance(structure, dict) else None
        test_root = structure.get("test_root") if isinstance(structure, dict) else None
        design_root = structure.get("design_root") if isinstance(structure, dict) else None
        return ProfileContribution(
            provider=self.name,
            priority=self.priority,
            project_type=str(manifest.get("project_type") or "application"),
            languages=(str(manifest["language"]),),
            source_roots=(str(source_root).rstrip("/"),) if source_root else (),
            test_roots=(str(test_root).rstrip("/"),) if test_root else (),
            design_roots=(str(design_root).rstrip("/"),) if design_root else (),
            commands=commands,
            evidence=(
                ProfileEvidence(
                    source=".ae-state/init-manifest.json",
                    digest=hashlib.sha256(content).hexdigest(),
                    facts=("compat:legacy_init",),
                ),
            ),
        )


__all__ = ["LegacyInitProvider"]
