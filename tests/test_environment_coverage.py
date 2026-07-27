"""工程环境发现、同步与持久化行为。"""

from __future__ import annotations

from pathlib import Path


def test_detects_project_environment_and_persists_answers(tmp_path: Path) -> None:
    from auto_engineering.config.environment import ProjectEnvironment

    (tmp_path / "uv.lock").touch()
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "lefthook.yml").write_text("")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".git").mkdir()

    environment = ProjectEnvironment.resolve_and_persist(tmp_path)

    assert environment.project_name == tmp_path.name
    assert environment.package_manager == "uv"
    assert environment.test_runner == "pytest"
    assert environment.use_typescript is True
    assert environment.use_lefthook is True
    assert environment.ci_platform == "github"
    assert environment.has_git is True
    assert (tmp_path / ".ae-answers.yml").is_file()


def test_existing_answers_are_filtered_and_synced(tmp_path: Path) -> None:
    from auto_engineering.config.environment import ProjectEnvironment

    answers = tmp_path / ".ae-answers.yml"
    answers.write_text(
        "_meta:\n  created_at: original\n"
        "project_name: demo\n"
        "package_manager: npm\n"
        "unknown_field: ignored\n",
    )
    (tmp_path / "pnpm-lock.yaml").touch()
    (tmp_path / "vitest.config.ts").touch()
    (tmp_path / ".gitlab-ci.yml").touch()

    environment = ProjectEnvironment.resolve_and_persist(tmp_path)

    assert environment.package_manager == "pnpm"
    assert environment.test_runner == "vitest"
    assert environment.ci_platform == "gitlab"
    content = answers.read_text()
    assert "created_at: original" in content
    assert "unknown_field" not in content


def test_detection_defaults_and_undetectable_fields(tmp_path: Path) -> None:
    from auto_engineering.config.environment import ProjectEnvironment

    environment = ProjectEnvironment._from_detection(tmp_path)
    missing = environment.get_undetectable_fields(tmp_path)

    assert environment.package_manager == "npm"
    assert environment.test_runner == ""
    assert {
        "package_manager",
        "test_runner",
        "ci_platform",
        "use_typescript",
        "use_lefthook",
        "has_git",
    }.issubset(missing)


def test_package_and_test_runner_detectors_cover_supported_files(
    tmp_path: Path,
) -> None:
    from auto_engineering.config.environment import ProjectEnvironment

    for filename, expected in (
        ("poetry.lock", "poetry"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lock", "bun"),
    ):
        path = tmp_path / filename
        path.touch()
        assert ProjectEnvironment._detect_package_manager(tmp_path) == expected
        path.unlink()

    for filename, expected in (
        ("pytest.ini", "pytest"),
        ("vitest.config.js", "vitest"),
        ("jest.config.ts", "jest"),
    ):
        path = tmp_path / filename
        path.touch()
        assert ProjectEnvironment._detect_test_runner(tmp_path) == expected
        path.unlink()


def test_load_answers_handles_missing_empty_and_yaml(tmp_path: Path) -> None:
    from auto_engineering.config.environment import load_ae_answers

    assert load_ae_answers(tmp_path) is None
    answers = tmp_path / ".ae-answers.yml"
    answers.write_text("")
    assert load_ae_answers(tmp_path) == {}
    answers.write_text("project_name: demo\n")
    assert load_ae_answers(tmp_path) == {"project_name": "demo"}
