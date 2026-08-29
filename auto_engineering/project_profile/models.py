"""ProjectProfile v1.0 不可变领域模型。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_PROFILE_SCHEMA_VERSION = "1.0"
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMAND_NAMES = frozenset({
    "install", "lint", "type_check", "test", "build", "browser_e2e",
})
_CONFIDENCE_VALUES = frozenset({"confirmed", "partial"})


class ProjectProfileErrorCode(StrEnum):
    """ProjectProfile 跨调用方稳定错误码。"""

    PROJECT_PROFILE_INVALID = "PROJECT_PROFILE_INVALID"
    PROJECT_PROFILE_CONFLICT = "PROJECT_PROFILE_CONFLICT"
    PROJECT_CAPABILITY_MISSING = "PROJECT_CAPABILITY_MISSING"
    PROJECT_SETUP_UNVERIFIED = "PROJECT_SETUP_UNVERIFIED"
    LEGACY_PROFILE_INVALID = "LEGACY_PROFILE_INVALID"
    PROJECT_COMMAND_UNVERIFIED = "PROJECT_COMMAND_UNVERIFIED"


class ProjectProfileError(ValueError):
    """Profile 校验、解析或能力验证失败。"""

    def __init__(self, code: ProjectProfileErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 必须为 object",
        )
    return value


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 必须为非空字符串",
        )
    return value.strip()


def _string_tuple(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 必须为字符串数组",
        )
    result = tuple(_require_non_empty_string(item, field) for item in value)
    if not result and not allow_empty:
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 不得为空",
        )
    if len(set(result)) != len(result):
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 不得包含重复值",
        )
    return result


def _validate_relative_path(value: str, project_root: Path | None) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts) or normalized in {"", "."}:
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"项目路径越界或无效: {value}",
        )
    canonical = path.as_posix().rstrip("/")
    if project_root is not None:
        root = project_root.resolve()
        candidate = project_root / canonical
        if candidate.exists() and not candidate.resolve().is_relative_to(root):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"项目路径通过符号链接逃逸: {value}",
            )
    return canonical


def _path_tuple(value: object, field: str, project_root: Path | None) -> tuple[str, ...]:
    paths = _string_tuple(value, field, allow_empty=True)
    result = tuple(_validate_relative_path(path, project_root) for path in paths)
    if len(set(result)) != len(result):
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
            f"{field} 规范化后存在重复路径",
        )
    return result


def _command_tuple(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_COMMAND_UNVERIFIED,
            f"{field} 必须为非空参数数组",
        )
    if any(not isinstance(part, str) or not part.strip() for part in value):
        raise ProjectProfileError(
            ProjectProfileErrorCode.PROJECT_COMMAND_UNVERIFIED,
            f"{field} 参数必须为非空字符串",
        )
    return tuple(part.strip() for part in value)


@dataclass(frozen=True, slots=True)
class ProfileEvidence:
    source: str
    digest: str
    facts: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> ProfileEvidence:
        raw = _require_mapping(value, "evidence[]")
        source = _validate_relative_path(
            _require_non_empty_string(raw.get("source"), "evidence.source"),
            None,
        )
        digest = _require_non_empty_string(raw.get("digest"), "evidence.digest")
        if not _DIGEST_PATTERN.fullmatch(digest):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                "evidence.digest 必须为 64 位小写 SHA-256",
            )
        facts = _string_tuple(raw.get("facts"), "evidence.facts", allow_empty=False)
        return cls(source=source, digest=digest, facts=facts)


@dataclass(frozen=True, slots=True)
class ProjectResolution:
    providers: tuple[str, ...]
    confidence: str

    @classmethod
    def from_dict(cls, value: object) -> ProjectResolution:
        raw = _require_mapping(value, "resolution")
        providers = _string_tuple(raw.get("providers"), "resolution.providers", allow_empty=False)
        confidence = _require_non_empty_string(raw.get("confidence"), "resolution.confidence")
        if confidence not in _CONFIDENCE_VALUES:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"resolution.confidence 不支持: {confidence}",
            )
        return cls(providers=providers, confidence=confidence)


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    schema_version: str
    profile_id: str
    project_type: str
    languages: tuple[str, ...]
    package_manager: str | None
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    design_roots: tuple[str, ...]
    commands: Mapping[str, tuple[str, ...]]
    evidence: tuple[ProfileEvidence, ...]
    resolution: ProjectResolution

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        project_root: Path | None = None,
    ) -> ProjectProfile:
        schema_version = value.get("schema_version")
        if schema_version != PROJECT_PROFILE_SCHEMA_VERSION:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                f"不支持 ProjectProfile schema_version={schema_version!r}",
            )
        project = _require_mapping(value.get("project"), "project")
        paths = _require_mapping(value.get("paths"), "paths")
        raw_commands = _require_mapping(value.get("commands"), "commands")
        unknown_commands = sorted(set(raw_commands) - _COMMAND_NAMES)
        if unknown_commands:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_COMMAND_UNVERIFIED,
                f"未知项目命令: {', '.join(unknown_commands)}",
            )
        commands = {
            name: _command_tuple(command, f"commands.{name}")
            for name, command in sorted(raw_commands.items())
        }
        raw_evidence = value.get("evidence")
        if isinstance(raw_evidence, (str, bytes)) or not isinstance(raw_evidence, Sequence):
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                "evidence 必须为数组",
            )
        evidence = tuple(ProfileEvidence.from_dict(item) for item in raw_evidence)
        package_manager_value = project.get("package_manager")
        package_manager = (
            None
            if package_manager_value is None
            else _require_non_empty_string(package_manager_value, "project.package_manager")
        )
        project_type = _require_non_empty_string(project.get("type"), "project.type")
        languages = _string_tuple(project.get("languages"), "project.languages", allow_empty=False)
        source_roots = _path_tuple(paths.get("source_roots"), "paths.source_roots", project_root)
        test_roots = _path_tuple(paths.get("test_roots"), "paths.test_roots", project_root)
        design_roots = _path_tuple(paths.get("design_roots"), "paths.design_roots", project_root)
        resolution = ProjectResolution.from_dict(value.get("resolution"))
        semantic: dict[str, Any] = {
            "schema_version": PROJECT_PROFILE_SCHEMA_VERSION,
            "project": {
                "type": project_type,
                "languages": list(languages),
                "package_manager": package_manager,
            },
            "paths": {
                "source_roots": list(source_roots),
                "test_roots": list(test_roots),
                "design_roots": list(design_roots),
            },
            "commands": {name: list(command) for name, command in commands.items()},
            "evidence": [asdict(item) for item in evidence],
            "resolution": asdict(resolution),
        }
        encoded = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        profile_id = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        supplied_id = value.get("profile_id")
        if supplied_id is not None and supplied_id != profile_id:
            raise ProjectProfileError(
                ProjectProfileErrorCode.PROJECT_PROFILE_INVALID,
                "profile_id 与规范化内容不一致",
            )
        return cls(
            schema_version=PROJECT_PROFILE_SCHEMA_VERSION,
            profile_id=profile_id,
            project_type=project_type,
            languages=languages,
            package_manager=package_manager,
            source_roots=source_roots,
            test_roots=test_roots,
            design_roots=design_roots,
            commands=commands,
            evidence=evidence,
            resolution=resolution,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "project": {
                "type": self.project_type,
                "languages": list(self.languages),
                "package_manager": self.package_manager,
            },
            "paths": {
                "source_roots": list(self.source_roots),
                "test_roots": list(self.test_roots),
                "design_roots": list(self.design_roots),
            },
            "commands": {name: list(command) for name, command in sorted(self.commands.items())},
            "evidence": [
                {
                    "source": item.source,
                    "digest": item.digest,
                    "facts": list(item.facts),
                }
                for item in self.evidence
            ],
            "resolution": {
                "providers": list(self.resolution.providers),
                "confidence": self.resolution.confidence,
            },
        }
