"""Phase 73 ProjectProfile 中立运行时契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.project_profile import (
    ProjectProfile,
    ProjectProfileError,
    ProjectProfileErrorCode,
)


def _profile_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project": {
            "type": "web_application",
            "languages": ["typescript"],
            "package_manager": "npm",
        },
        "paths": {
            "source_roots": ["src"],
            "test_roots": ["tests"],
            "design_roots": ["design"],
        },
        "commands": {
            "test": ["npm", "run", "test"],
            "build": ["npm", "run", "build"],
        },
        "evidence": [
            {
                "source": "package.json",
                "digest": "a" * 64,
                "facts": ["language:typescript", "script:test"],
            }
        ],
        "resolution": {
            "providers": ["local_probe"],
            "confidence": "confirmed",
        },
    }


def test_same_semantic_profile_has_stable_id(tmp_path: Path) -> None:
    first = ProjectProfile.from_dict(_profile_payload(), project_root=tmp_path)
    reordered = _profile_payload()
    reordered["commands"] = {
        "build": ["npm", "run", "build"],
        "test": ["npm", "run", "test"],
    }
    second = ProjectProfile.from_dict(reordered, project_root=tmp_path)

    assert first.profile_id == second.profile_id
    assert first.profile_id.startswith("sha256:")
    assert len(first.profile_id) == len("sha256:") + 64
    assert first.to_dict()["profile_id"] == first.profile_id


@pytest.mark.parametrize(
    "command",
    ["npm test", [], ["npm", ""], ["npm", 1]],
)
def test_command_must_be_non_empty_argument_array(
    tmp_path: Path,
    command: object,
) -> None:
    payload = _profile_payload()
    payload["commands"] = {"test": command}

    with pytest.raises(ProjectProfileError) as exc_info:
        ProjectProfile.from_dict(payload, project_root=tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_COMMAND_UNVERIFIED


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside", "src/../../outside"])
def test_profile_rejects_path_escape(tmp_path: Path, path: str) -> None:
    payload = _profile_payload()
    payload["paths"] = {
        "source_roots": [path],
        "test_roots": [],
        "design_roots": [],
    }

    with pytest.raises(ProjectProfileError) as exc_info:
        ProjectProfile.from_dict(payload, project_root=tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_INVALID


def test_profile_rejects_existing_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    payload = _profile_payload()
    payload["paths"] = {
        "source_roots": ["linked"],
        "test_roots": [],
        "design_roots": [],
    }

    with pytest.raises(ProjectProfileError) as exc_info:
        ProjectProfile.from_dict(payload, project_root=tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_INVALID


def test_profile_rejects_unsupported_schema(tmp_path: Path) -> None:
    payload = _profile_payload()
    payload["schema_version"] = "2.0"

    with pytest.raises(ProjectProfileError) as exc_info:
        ProjectProfile.from_dict(payload, project_root=tmp_path)

    assert exc_info.value.code is ProjectProfileErrorCode.PROJECT_PROFILE_INVALID


def test_profile_schema_is_valid_json() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "auto_engineering"
        / "project_profile"
        / "project-profile.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$id"].endswith("project-profile.schema.json")
    assert schema["additionalProperties"] is False
