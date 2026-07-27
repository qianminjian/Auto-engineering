"""项目版本与测试基线 SSOT 契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_project_metadata


def _write_fixture(root: Path, *, plugin_version: str = "5.6.0") -> None:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".codex-plugin").mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
version = "5.6.0"

[tool.auto-engineering.baseline]
passed = 1775
skipped = 1
""".lstrip(),
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Auto-Engineering v5.6.0\n\n"
        "<!-- test-baseline --> 1775 passed / 1 skipped\n",
        encoding="utf-8",
    )
    for directory in (".claude-plugin", ".codex-plugin"):
        (root / directory / "plugin.json").write_text(
            json.dumps({"version": plugin_version}),
            encoding="utf-8",
        )
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "metadata": {"version": plugin_version},
                "plugins": [{"version": plugin_version}],
            }
        ),
        encoding="utf-8",
    )


def test_repository_metadata_is_in_sync() -> None:
    root = Path(__file__).parents[1]

    assert check_project_metadata.check_metadata(root) == []


def test_mypy_overrides_only_reference_existing_modules() -> None:
    """类型检查配置不得继续指向已经删除的旧架构模块。"""
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

    for retired_module in (
        "auto_engineering.agents.base",
        "auto_engineering.loop.orchestrator",
        "auto_engineering.loop.semantic_evaluator",
    ):
        assert retired_module not in pyproject


def test_plugin_version_drift_is_reported(tmp_path: Path) -> None:
    _write_fixture(tmp_path, plugin_version="5.5.0")

    errors = check_project_metadata.check_metadata(tmp_path)

    assert any(".claude-plugin/plugin.json" in error for error in errors)
    assert any(".codex-plugin/plugin.json" in error for error in errors)


def test_readme_baseline_drift_is_reported(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text().replace("1775 passed", "1700 passed"))

    errors = check_project_metadata.check_metadata(tmp_path)

    assert errors == [
        "README.md 测试基线漂移: 期望 1775 passed / 1 skipped"
    ]


def test_main_returns_nonzero_for_drift(tmp_path: Path) -> None:
    _write_fixture(tmp_path, plugin_version="5.5.0")

    assert check_project_metadata.main(root=tmp_path) == 1
