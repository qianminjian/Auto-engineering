"""Python 包装前置契约回归。"""

from pathlib import Path

import pytest

from auto_engineering.project_profile.python_packaging import (
    python_build_command,
    python_packaging_gaps,
)


def test_src_package_without_build_backend_is_setup_gap(tmp_path: Path) -> None:
    package = tmp_path / "src" / "voice_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")

    gaps = python_packaging_gaps(
        tmp_path,
        {"project": {"name": "voice-app"}},
        ("src",),
    )

    assert gaps == ("python_packaging",)
    assert python_build_command(("src",), gaps) == (
        "uv", "run", "python", "-m", "compileall", "-q", "src",
    )


def test_hatchling_src_package_requires_existing_explicit_wheel_mapping(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "voice_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "project": {"name": "voice-app"},
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
        "tool": {
            "hatch": {
                "build": {
                    "targets": {"wheel": {"packages": ["src/missing"]}},
                },
            },
        },
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("src",)) == (
        "python_packaging",
    )


def test_hatchling_mapping_to_non_package_directory_is_a_gap(tmp_path: Path) -> None:
    (tmp_path / "src" / "voice_app").mkdir(parents=True)
    (tmp_path / "src" / "voice_app" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    (tmp_path / "src" / "wrong").mkdir()
    pyproject = {
        "build-system": {"build-backend": "hatchling.build"},
        "tool": {
            "hatch": {
                "build": {
                    "targets": {"wheel": {"packages": ["src/wrong"]}},
                },
            },
        },
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("src",)) == (
        "python_packaging",
    )


def test_build_backend_without_declared_build_requirement_is_a_gap(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "voice_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "build-system": {"build-backend": "setuptools.build_meta"},
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("src",)) == (
        "python_packaging",
    )


def test_hatchling_package_without_runtime_sdist_excludes_is_a_gap(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "voice_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
        "tool": {
            "hatch": {
                "build": {
                    "targets": {
                        "wheel": {"packages": ["src/voice_app"]},
                        "sdist": {"exclude": ["/.venv"]},
                    },
                },
            },
        },
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("src",)) == (
        "python_packaging",
    )


def test_hatchling_root_package_also_requires_runtime_sdist_excludes(
    tmp_path: Path,
) -> None:
    package = tmp_path / "voice_app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("voice_app",)) == (
        "python_packaging",
    )


def test_valid_hatchling_src_package_uses_real_build_gate(tmp_path: Path) -> None:
    package = tmp_path / "src" / "voice_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    pyproject = {
        "project": {"name": "voice-app"},
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
        "tool": {
            "hatch": {
                "build": {
                    "targets": {
                        "wheel": {"packages": ["src/voice_app"]},
                        "sdist": {"exclude": [
                            "/.ae-state", "/.ae-runtime", "/.venv", "/dist",
                            "/build", "/_scratch", "/**/__pycache__",
                        ]},
                    },
                },
            },
        },
    }

    assert python_packaging_gaps(tmp_path, pyproject, ("src",)) == ()
    assert python_build_command(("src",), (), packaged_source=True) == ("uv", "build")


def test_script_only_python_project_keeps_compileall_gate(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('ok')\n", encoding="utf-8")

    assert python_packaging_gaps(
        tmp_path,
        {"project": {"name": "script-project"}},
        ("src",),
    ) == ()
    assert python_build_command(("src",), ()) == (
        "uv", "run", "python", "-m", "compileall", "-q", "src",
    )


def test_packaging_preflight_does_not_follow_source_symlink_outside_project(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "voice_app").mkdir()
    (outside / "voice_app" / "__init__.py").write_text("", encoding="utf-8")
    try:
        (tmp_path / "src").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前文件系统不支持创建 symlink")

    assert python_packaging_gaps(
        tmp_path,
        {"project": {"name": "voice-app"}},
        ("src",),
    ) == ()
