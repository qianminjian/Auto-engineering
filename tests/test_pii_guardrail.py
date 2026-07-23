"""Tests for PIIGuardrail — post-agent file PII scan (E3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from auto_engineering.engine.guardrail_types import GuardrailResult
from auto_engineering.pii.guardrail import PIIGuardrail


class TestPIIGuardrailInit:
    def test_block_mode_defaults_to_retry_when_env_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            g = PIIGuardrail()
            assert g._block_mode is False

    def test_block_mode_true_from_env(self) -> None:
        with patch.dict("os.environ", {"AE_PII_GUARDRAIL_MODE": "block"}):
            g = PIIGuardrail()
            assert g._block_mode is True

    def test_block_mode_explicit_overrides_env(self) -> None:
        with patch.dict("os.environ", {"AE_PII_GUARDRAIL_MODE": "block"}):
            g = PIIGuardrail(block_mode=False)
            assert g._block_mode is False


class TestPIIGuardrailCheck:
    def test_no_files_changed_returns_pass(self) -> None:
        g = PIIGuardrail(block_mode=False)
        result = g.check(files_changed=[])
        assert result.action == "pass"
        assert result.message == ""

    def test_no_pii_in_clean_file_returns_pass(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.py"
        f.write_text("print('hello world')\n")
        g = PIIGuardrail(block_mode=False, project_root=tmp_path)
        result = g.check(files_changed=["clean.py"])
        assert result.action == "pass"

    def test_pii_detected_returns_retry_when_not_block_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "leak.py"
        f.write_text("api_key = 'sk-1234567890abcdef'\n")
        g = PIIGuardrail(block_mode=False, project_root=tmp_path)
        result = g.check(files_changed=["leak.py"])
        assert result.action == "retry"
        assert "PII detected" in result.message

    def test_pii_detected_returns_block_in_block_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "leak.py"
        f.write_text("api_key = 'sk-1234567890abcdef'\n")
        g = PIIGuardrail(block_mode=True, project_root=tmp_path)
        result = g.check(files_changed=["leak.py"])
        assert result.action == "block"

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        g = PIIGuardrail(block_mode=True, project_root=tmp_path)
        result = g.check(files_changed=["nonexistent.py"])
        assert result.action == "pass"

    def test_chinese_id_card_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "data.py"
        f.write_text("id_number = '320106199001011234'\n")
        g = PIIGuardrail(block_mode=False, project_root=tmp_path)
        result = g.check(files_changed=["data.py"])
        assert result.action == "retry"

    def test_chinese_phone_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "data.py"
        f.write_text("phone = '13812345678'\n")
        g = PIIGuardrail(block_mode=False, project_root=tmp_path)
        result = g.check(files_changed=["data.py"])
        assert result.action == "retry"

    def test_timing_is_post(self) -> None:
        assert PIIGuardrail.timing == "post"

    def test_applies_to_developer_stage(self) -> None:
        assert PIIGuardrail.applies_to_stages == ("developer",)
