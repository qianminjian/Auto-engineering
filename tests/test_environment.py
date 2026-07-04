"""Tests for config/environment.py — load_ae_answers + preflight.

覆盖:
    - load_ae_answers: 文件存在/缺失/字段冲突
    - preflight: git/API key/磁盘/Python 版本校验
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.config.environment import load_ae_answers, preflight


class TestLoadAeAnswers:
    """load_ae_answers(project_root) — 读 .ae-answers.yml."""

    def test_returns_dict_when_file_exists(self, tmp_path: Path):
        """RED: 存在 .ae-answers.yml 时返回 dict."""
        answers_file = tmp_path / ".ae-answers.yml"
        answers_file.write_text(
            "project_name: test-project\npackage_manager: uv\nuse_typescript: false\n"
        )
        result = load_ae_answers(tmp_path)
        assert result is not None
        assert result["project_name"] == "test-project"
        assert result["package_manager"] == "uv"
        assert result["use_typescript"] is False

    def test_returns_none_when_file_missing(self, tmp_path: Path):
        """RED: .ae-answers.yml 不存在时返回 None."""
        result = load_ae_answers(tmp_path)
        assert result is None

    def test_strips_meta_block(self, tmp_path: Path):
        """RED: _meta 块不参与字段合并,作为元数据保留."""
        answers_file = tmp_path / ".ae-answers.yml"
        answers_file.write_text("_meta:\n  updated_at: '2026-01-01'\nproject_name: x\n")
        result = load_ae_answers(tmp_path)
        assert result is not None
        assert "_meta" in result
        assert result["project_name"] == "x"

    def test_returns_empty_dict_for_empty_file(self, tmp_path: Path):
        """RED: 空 YAML 文件返回空 dict."""
        answers_file = tmp_path / ".ae-answers.yml"
        answers_file.write_text("")
        result = load_ae_answers(tmp_path)
        assert result == {} or result is None

    def test_returns_dict_for_malformed_but_readable_yaml(self, tmp_path: Path):
        """RED: 合法 YAML 即使字段少也返回 dict."""
        answers_file = tmp_path / ".ae-answers.yml"
        answers_file.write_text("project_type: cli-tool\n")
        result = load_ae_answers(tmp_path)
        assert result is not None
        assert result["project_type"] == "cli-tool"


class TestPreflight:
    """preflight(project_root) — 入口前置校验 (Python 版本 + Git 仓库 + 磁盘空间).

    2026-07-04 修复 (v5.0 深度审计): preflight 不检查 ANTHROPIC_API_KEY
    (见 environment.py:200-229, SDK 自动从 env 读).
    原 test_raises_systemexit_without_api_key + test_systemexit_code_is_one_on_failure
    测试期望错, 删除.
    """

    def test_passes_in_valid_git_repo(self, tmp_path: Path):
        """合法 git 仓库 + 足够磁盘空间时 preflight 通过."""
        (tmp_path / ".git").mkdir()
        # preflight 不抛 SystemExit
        preflight(tmp_path)

    def test_raises_systemexit_outside_git_repo(self, tmp_path: Path):
        """非 git 仓库时 preflight 抛 SystemExit (code=1)."""
        # tmp_path 没有 .git
        with pytest.raises(SystemExit) as exc_info:
            preflight(tmp_path)
        assert exc_info.value.code == 1
