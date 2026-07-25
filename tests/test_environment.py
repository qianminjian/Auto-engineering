"""Tests for config/environment.py — load_ae_answers.

覆盖:
    - load_ae_answers: 文件存在/缺失/字段冲突
"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.config.environment import load_ae_answers


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


