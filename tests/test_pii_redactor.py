"""Tests for auto_engineering.pii — PIIDetectionRule + PIIRedactor."""

from __future__ import annotations

import re

import pytest

from auto_engineering.pii.redactor import PIIBlockedError, PIIRedactor
from auto_engineering.pii.rules import (
    PIICategory,
    PIIDetectionRule,
    PIISeverity,
    PII_RULES,
    PII_WHITELIST_PATTERNS,
)


class TestPIIDetectionRule:
    """PIIDetectionRule dataclass tests."""

    def test_default_construction(self) -> None:
        rule = PIIDetectionRule(
            name="test_rule",
            pattern=r"\d{4}",
            replacement="****",
            severity=PIISeverity.WARN,
            category=PIICategory.PII,
        )
        assert rule.name == "test_rule"
        assert rule.enabled is True
        assert rule.exclusion_patterns == []

    def test_frozen_dataclass(self) -> None:
        rule = PIIDetectionRule(
            name="r", pattern=".", replacement="x",
            severity=PIISeverity.WARN, category=PIICategory.PII,
        )
        with pytest.raises(Exception):
            rule.name = "changed"  # type: ignore[misc]

    def test_all_builtin_rules_have_valid_patterns(self) -> None:
        """Every built-in PII_RULE compiles as a regex."""
        for rule in PII_RULES:
            re.compile(rule.pattern)

    def test_builtin_rules_count(self) -> None:
        """5 built-in rules covering the minimum bank scenario."""
        assert len(PII_RULES) == 5

    def test_whitelist_patterns_compile(self) -> None:
        for p in PII_WHITELIST_PATTERNS:
            re.compile(p)


class TestPIIRedactor:
    """PIIRedactor core engine tests."""

    @pytest.fixture
    def redactor(self) -> PIIRedactor:
        return PIIRedactor()

    # -- scan_text (single text) --

    def test_scan_text_redacts_cn_id_card(self, redactor: PIIRedactor) -> None:
        """18-digit Chinese ID card number is redacted."""
        text = "身份证号：320102199001011234"
        result = redactor.scan_text(text)
        assert "320102199001011234" not in result
        assert "**********" in result

    def test_scan_text_redacts_cn_phone(self, redactor: PIIRedactor) -> None:
        """11-digit Chinese mobile number is redacted."""
        text = "联系电话：13812345678"
        result = redactor.scan_text(text)
        assert "13812345678" not in result
        assert "****" in result
        assert "联系电话：" in result

    def test_scan_text_redacts_api_key(self, redactor: PIIRedactor) -> None:
        """API key patterns are redacted."""
        text = 'api_key: sk-ant-api03-abc123xyz'
        result = redactor.scan_text(text)
        assert "sk-ant-api03-abc123xyz" not in result
        assert "***REDACTED***" in result

    def test_scan_text_redacts_email(self, redactor: PIIRedactor) -> None:
        """Email address is redacted."""
        text = "请联系 zhang.san@bankcomm.com 获取更多信息"
        result = redactor.scan_text(text)
        assert "zhang.san@bankcomm.com" not in result
        assert "***@***" in result

    def test_scan_text_preserves_non_pii_content(self, redactor: PIIRedactor) -> None:
        """Text without PII is returned unchanged."""
        text = "请实现一个登录功能，包含用户名和密码验证。"
        result = redactor.scan_text(text)
        assert result == text

    def test_scan_text_bank_card_excludes_git_hash(self, redactor: PIIRedactor) -> None:
        """40-char git hash is NOT matched as bank card number."""
        text = "commit abcdef1234567890abcdef1234567890abcdef12 by developer"
        result = redactor.scan_text(text)
        # git hash should NOT be replaced
        assert "abcdef1234567890abcdef1234567890abcdef12" in result

    def test_scan_text_bank_card_excludes_timestamp(self, redactor: PIIRedactor) -> None:
        """13-digit timestamp is NOT matched as bank card number."""
        text = "timestamp: 1700000000000"
        result = redactor.scan_text(text)
        assert "1700000000000" in result

    def test_disabled_rule_not_applied(self) -> None:
        """A disabled rule is skipped during scanning."""
        rules = [
            PIIDetectionRule(
                name="disabled_test",
                pattern=r"\d{4}",
                replacement="XX",
                severity=PIISeverity.WARN,
                category=PIICategory.PII,
                enabled=False,
            ),
        ]
        redactor = PIIRedactor(rules=rules)
        result = redactor.scan_text("code: 1234")
        assert "1234" in result

    def test_block_mode_raises_on_critical(self) -> None:
        """block_mode with CRITICAL PII raises PIIBlockedError."""
        rules = [
            PIIDetectionRule(
                name="test_critical",
                pattern=r"\d{4}",
                replacement="XX",
                severity=PIISeverity.CRITICAL,
                category=PIICategory.PII,
            ),
        ]
        redactor = PIIRedactor(rules=rules, block_mode=True)
        with pytest.raises(PIIBlockedError) as exc:
            redactor.scan_text("code: 1234")
        assert exc.value.rule_name == "test_critical"

    def test_block_mode_does_not_raise_on_warn(self) -> None:
        """block_mode only blocks CRITICAL, not WARN severity."""
        rules = [
            PIIDetectionRule(
                name="test_warn",
                pattern=r"\d{4}",
                replacement="XX",
                severity=PIISeverity.WARN,
                category=PIICategory.PII,
            ),
        ]
        redactor = PIIRedactor(rules=rules, block_mode=True)
        result = redactor.scan_text("code: 1234")
        assert "1234" not in result

    # -- scan (messages list) --

    def test_scan_str_content_message(self, redactor: PIIRedactor) -> None:
        """Messages with string content are scanned."""
        messages = [
            {"role": "user", "content": "手机号 13800001111"},
        ]
        result = redactor.scan(messages)
        assert "13800001111" not in result[0]["content"]

    def test_scan_list_content_message(self, redactor: PIIRedactor) -> None:
        """Messages with list content blocks are scanned."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "身份证 320102199001011234"},
                    {"type": "text", "text": "普通文本"},
                ],
            },
        ]
        result = redactor.scan(messages)
        blocks = result[0]["content"]
        assert "320102199001011234" not in blocks[0]["text"]
        assert blocks[1]["text"] == "普通文本"

    def test_scan_preserves_input(self, redactor: PIIRedactor) -> None:
        """scan() returns a copy, does not mutate input."""
        messages = [
            {"role": "user", "content": "手机号 13800001111"},
        ]
        original_content = messages[0]["content"]
        redactor.scan(messages)
        assert messages[0]["content"] == original_content

    def test_scan_skips_non_text_blocks(self, redactor: PIIRedactor) -> None:
        """Non-text content blocks are passed through unchanged."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"data": "base64..."}},
                ],
            },
        ]
        result = redactor.scan(messages)
        assert result[0]["content"][0]["type"] == "image"

    def test_whitelist_source_skips_scan(self) -> None:
        """File paths matching whitelist patterns are NOT scanned."""
        redactor = PIIRedactor()
        text = "身份证号：320102199001011234"
        result = redactor.scan_text(text, source="tests/test_pii_redactor.py")
        # Whitelist pattern r'test.*pii' should match this source
        assert "320102199001011234" in result

    def test_scan_empty_messages(self, redactor: PIIRedactor) -> None:
        """Empty message list returns empty list."""
        assert redactor.scan([]) == []


class TestPIIToolResultScan:
    """T57 — Tool result PII scan integration."""

    @pytest.fixture
    def redactor(self) -> PIIRedactor:
        return PIIRedactor()

    def test_scan_text_on_tool_output(self, redactor: PIIRedactor) -> None:
        """scan_text redacts PII in tool output strings."""
        tool_output = "用户数据：姓名张三，身份证 320102199001011234，电话 13800001111"
        result = redactor.scan_text(tool_output, source="tool:read_file")
        assert "320102199001011234" not in result
        assert "13800001111" not in result

    def test_scan_text_on_tool_output_preserves_code(self, redactor: PIIRedactor) -> None:
        """Tool output containing code is mostly preserved."""
        code = "def calculate(a: int, b: int) -> int:\n    return a + b"
        result = redactor.scan_text(code, source="tool:read_file")
        assert result == code

    def test_scan_text_on_json_tool_output(self, redactor: PIIRedactor) -> None:
        """PII embedded in JSON tool output is redacted."""
        json_output = '{"user": "张三", "phone": "13912345678", "id_card": "320102199001011234"}'
        result = redactor.scan_text(json_output, source="tool:api_call")
        assert "13912345678" not in result
        assert "320102199001011234" not in result

    def test_scan_text_source_parameter_tracks_origin(self, redactor: PIIRedactor) -> None:
        """The source parameter is used for whitelist and log context."""
        # Source doesn't match any whitelist pattern → still redacts
        result = redactor.scan_text("电话 13800001111", source="tools/bash_output.txt")
        assert "13800001111" not in result

    def test_multiple_tool_results_batched(self, redactor: PIIRedactor) -> None:
        """Multiple tool results are each scanned independently."""
        results = [
            "手机 13800001111",
            "身份证 320102199001011234",
        ]
        redacted = [redactor.scan_text(r) for r in results]
        assert "13800001111" not in redacted[0]
        assert "320102199001011234" not in redacted[1]


# ── T109a: scan_dict / redact_dict for file-bridge PII protection ──


class TestPIIRedactorDict:
    """T109a: scan_dict() and redact_dict() for nested dict PII scanning."""

    @staticmethod
    def _redactor() -> PIIRedactor:
        return PIIRedactor()

    def test_scan_dict_finds_pii_in_flat_dict(self) -> None:
        """scan_dict finds PII in flat dict values."""
        r = self._redactor()
        data = {"requirement": "用户手机号 13800001111", "name": "test"}
        findings = r.scan_dict(data)
        assert len(findings) >= 1
        phone_findings = [f for f in findings if f["rule"] == "cn_phone"]
        assert len(phone_findings) >= 1
        assert "138" in phone_findings[0]["matched"]

    def test_scan_dict_finds_pii_in_nested_dict(self) -> None:
        """scan_dict recursively finds PII in nested dicts."""
        r = self._redactor()
        data = {
            "action": {
                "context": {"note": "身份证 320102199001011234"},
                "plan": "普通文本",
            },
        }
        findings = r.scan_dict(data)
        id_findings = [f for f in findings if f["rule"] == "cn_id_card"]
        assert len(id_findings) >= 1
        assert "320102" in id_findings[0]["matched"]

    def test_scan_dict_finds_pii_in_list_values(self) -> None:
        """scan_dict finds PII in list items."""
        r = self._redactor()
        data = {"messages": ["电话 13800001111", "普通"]}
        findings = r.scan_dict(data)
        phone_findings = [f for f in findings if f["rule"] == "cn_phone"]
        assert len(phone_findings) >= 1

    def test_scan_dict_returns_empty_for_clean_data(self) -> None:
        """scan_dict returns empty list when no PII found."""
        r = self._redactor()
        data = {"name": "test", "count": 42, "items": ["a", "b"]}
        findings = r.scan_dict(data)
        assert findings == []

    def test_redact_dict_returns_copy_with_pii_masked(self) -> None:
        """redact_dict returns a copy with PII values redacted."""
        r = self._redactor()
        data = {"note": "手机 13800001111", "other": "keep"}
        result = r.redact_dict(data)
        assert result is not data  # returns a copy
        assert "13800001111" not in result["note"]
        assert result["other"] == "keep"

    def test_redact_dict_handles_nested_structures(self) -> None:
        """redact_dict recursively redacts nested dicts and lists."""
        r = self._redactor()
        data = {
            "requirement": "用户 13800001111",
            "context": {"desc": "身份证 320102199001011234"},
            "items": ["电话 13900001111", "ok"],
        }
        result = r.redact_dict(data)
        assert "13800001111" not in result["requirement"]
        assert "320102199001011234" not in result["context"]["desc"]
        assert "13900001111" not in result["items"][0]
        assert result["items"][1] == "ok"

    def test_redact_dict_preserves_non_string_values(self) -> None:
        """redact_dict preserves int, float, bool, None values."""
        r = self._redactor()
        data = {"count": 42, "flag": True, "nothing": None, "pi": 3.14}
        result = r.redact_dict(data)
        assert result["count"] == 42
        assert result["flag"] is True
        assert result["nothing"] is None
        assert result["pi"] == 3.14

    def test_scan_and_redact_dict_roundtrip(self) -> None:
        """scan_dict detects what redact_dict removes."""
        r = self._redactor()
        data = {"msg": "手机 13800001111 身份证 320102199001011234"}
        findings = r.scan_dict(data)
        assert len(findings) >= 2
        redacted = r.redact_dict(data)
        # After redaction, re-scan should find nothing
        refindings = r.scan_dict(redacted)
        assert refindings == []
