"""Init manifest 可选兼容输入的边界回归。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.loop import init_contract


def test_init_manifest_loader_fails_closed_for_malformed_and_non_object_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".ae-state" / "init-manifest.json"
    path.parent.mkdir()
    path.write_text("not-json", encoding="utf-8")
    assert init_contract.load_init_manifest(tmp_path) is None
    path.write_text(json.dumps(["not-an-object"]), encoding="utf-8")
    assert init_contract.load_init_manifest(tmp_path) is None


def test_init_manifest_validation_covers_forward_and_shape_warnings(
    monkeypatch,
) -> None:
    monkeypatch.setattr(init_contract, "_load_schema", lambda: None)
    monkeypatch.setattr(init_contract, "_jsonschema_lib", lambda: None)
    result = init_contract.validate_init_manifest({
        "schema_version": "10.0",
        "project_type": "unsupported",
        "language": "klingon",
        "conventions": {"linter": "ruff"},
        "future": True,
    })
    assert result.ok is False
    assert any("forward-compat" in warning for warning in result.warnings)
    assert any("project_type" in error for error in result.errors)
    assert any("language" in error for error in result.errors)
    assert any("type_checker" in error for error in result.errors)
    monkeypatch.setattr(init_contract, "_load_schema", lambda: {})
    assert init_contract.validate_against_schema({}).warnings

    wrong_shape = init_contract.validate_init_manifest({
        "schema_version": "1.0",
        "project_type": "app-service",
        "language": "python",
        "structure": {},
        "conventions": [],
    })
    assert any("类型错误" in error for error in wrong_shape.errors)


def test_init_manifest_optional_projection_helpers_are_conservative() -> None:
    assert init_contract.get_ci_platform_from_manifest({}) is None
    assert init_contract.get_ci_platform_from_manifest({"conventions": {"ci_platform": "github"}}) == "github"
    assert init_contract.get_ci_platform_from_manifest({"conventions": {"ci_platform": "other"}}) is None
    assert init_contract.get_design_root_from_manifest({}) == "design/"
    assert init_contract.get_design_root_from_manifest({"structure": {"design_root": "docs"}}) == "docs"
    assert init_contract.get_design_root_from_manifest({"structure": {"design_root": "  "}}) == "design/"
