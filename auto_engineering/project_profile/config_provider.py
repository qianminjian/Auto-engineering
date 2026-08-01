"""ae.toml 显式 ProjectProfile Provider。"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from auto_engineering.project_profile.models import (
    ProfileEvidence,
    ProjectProfileError,
    ProjectProfileErrorCode,
)
from auto_engineering.project_profile.providers import ProfileContribution


class AeConfigProvider:
    name = "ae_config"
    priority = 300
    MAX_CONFIG_BYTES = 256 * 1024

    def inspect(self, project_root: Path) -> ProfileContribution:
        path = project_root / "ae.toml"
        if not path.is_file():
            return ProfileContribution(provider=self.name, priority=self.priority)
        if path.stat().st_size > self.MAX_CONFIG_BYTES:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                "ae.toml 超过项目配置大小上限",
            )
        content = path.read_bytes()
        try:
            document = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"ae.toml 无法解析: {exc}",
            ) from exc
        project = document.get("project")
        if project is None:
            return ProfileContribution(
                provider=self.name,
                priority=self.priority,
                evidence=(self._evidence(content, ("config:runtime_only",)),),
            )
        if not isinstance(project, dict):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                "ae.toml [project] 必须为 table",
            )
        commands = self._commands(project.get("commands", {}))
        self._verify_package_scripts(project_root, commands)
        languages = self._strings(project.get("languages", ()), "project.languages")
        return ProfileContribution(
            provider=self.name,
            priority=self.priority,
            project_type=self._optional_string(project.get("type"), "project.type"),
            languages=languages,
            package_manager=self._optional_string(
                project.get("package_manager"),
                "project.package_manager",
            ),
            source_roots=self._strings(project.get("source_roots", ()), "project.source_roots"),
            test_roots=self._strings(project.get("test_roots", ()), "project.test_roots"),
            design_roots=self._strings(project.get("design_roots", ()), "project.design_roots"),
            commands=commands,
            evidence=(self._evidence(content, ("config:project",)),),
        )

    @staticmethod
    def _optional_string(value: object, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"{field} 必须为非空字符串",
            )
        return value.strip()

    @staticmethod
    def _strings(value: object, field: str) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"{field} 必须为字符串数组",
            )
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ProjectProfileError(
                    ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                    f"{field} 只能包含非空字符串",
                )
            result.append(item.strip())
        return tuple(result)

    def _commands(self, value: object) -> dict[str, tuple[str, ...]]:
        if not isinstance(value, Mapping):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_COMMAND_UNVERIFIED,
                "project.commands 必须为 table",
            )
        return {
            str(name): self._strings(command, f"project.commands.{name}")
            for name, command in value.items()
        }

    @staticmethod
    def _verify_package_scripts(
        project_root: Path,
        commands: Mapping[str, tuple[str, ...]],
    ) -> None:
        required_scripts = {
            command[2]
            for command in commands.values()
            if len(command) >= 3 and command[1] == "run" and command[0] in {"npm", "pnpm", "yarn", "bun"}
        }
        if not required_scripts:
            return
        package_path = project_root / "package.json"
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT,
                "ae.toml 声明 package script，但 package.json 不可验证",
            ) from exc
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        missing = sorted(script for script in required_scripts if not isinstance(scripts.get(script), str))
        if missing:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_CONFLICT,
                f"ae.toml 引用不存在的 package script: {', '.join(missing)}",
            )

    @staticmethod
    def _evidence(content: bytes, facts: tuple[str, ...]) -> ProfileEvidence:
        return ProfileEvidence(
            source="ae.toml",
            digest=hashlib.sha256(content).hexdigest(),
            facts=facts,
        )


__all__ = ["AeConfigProvider"]
