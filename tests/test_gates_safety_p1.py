"""SafetyGate 5 种缺失检测测试 (P1-1 全面深度审计 2026-07-04).

设计 §B12.4 列 7 种检测模式, 实际 SafetyGate 已实现 9 种 (比设计多),
但仍缺 5 种 PII/金融检测:
    - Anthropic-style API Key (sk-...)
    - Generic long Token (32+ chars + keyword context)
    - 中国身份证号 (18 位)
    - 中国手机号 (11 位)
    - 银行卡号 (13-19 位)

覆盖范围:
- 每种 pattern 正向命中 (应该检测到)
- 边界 (不应误报: 短数字 / 普通字符 / 日期格式 / 版本号)
- 与现有 9 种 pattern 共存
"""

from __future__ import annotations

from pathlib import Path


class TestSafetyGateNewPatterns:
    """SafetyGate P1-1 新增 5 种检测模式."""

    def _scan(self, content: str, tmp_path: Path) -> list[str]:
        """Helper: 写 tmp 文件 + 扫描, 返回命中的 descs."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "test.txt"
        target.write_text(content, encoding="utf-8")
        return _scan_file(target)

    # ============================================================
    # 1. Anthropic-style API Key (sk-...)
    # ============================================================

    def test_anthropic_api_key_detected(
        self, tmp_path: Path
    ) -> None:
        """Anthropic sk-ant-... key → 检测到."""
        hits = self._scan("key = sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890", tmp_path)
        assert "Anthropic API Key" in hits

    def test_openai_api_key_detected(
        self, tmp_path: Path
    ) -> None:
        """OpenAI sk-... key (52 chars) → 检测到."""
        hits = self._scan('OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ12"', tmp_path)
        assert "Anthropic API Key" in hits

    def test_short_sk_prefix_not_detected(
        self, tmp_path: Path
    ) -> None:
        """sk-... 少于 32 chars → 不应误报."""
        hits = self._scan("short = sk-abc123", tmp_path)
        # 不应匹配 Anthropic API Key (需 32+ chars)
        assert "Anthropic API Key" not in hits

    # ============================================================
    # 2. Long Token (32+ chars + keyword context)
    # ============================================================

    def test_long_token_with_keyword_detected(
        self, tmp_path: Path
    ) -> None:
        """token= + 32+ chars → 检测到."""
        hits = self._scan(
            "access_token = abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
            tmp_path,
        )
        assert "Long Token (32+ chars)" in hits

    def test_long_token_bearer_keyword_detected(
        self, tmp_path: Path
    ) -> None:
        """bearer: + 32+ chars → 检测到."""
        hits = self._scan(
            "Authorization: bearer abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
            tmp_path,
        )
        assert "Long Token (32+ chars)" in hits

    def test_short_token_not_detected(
        self, tmp_path: Path
    ) -> None:
        """token= + 少于 32 chars → 不应误报."""
        hits = self._scan("token = short_value", tmp_path)
        assert "Long Token (32+ chars)" not in hits

    def test_random_long_string_without_keyword_not_detected(
        self, tmp_path: Path
    ) -> None:
        """无 keyword 的 32+ chars 字符串 → 不应误报 (避免 false positive)."""
        hits = self._scan(
            "This is just a long description string that exceeds the 32 character threshold",
            tmp_path,
        )
        assert "Long Token (32+ chars)" not in hits

    # ============================================================
    # 3. 中国身份证号 (18 位)
    # ============================================================

    def test_china_id_card_detected(
        self, tmp_path: Path
    ) -> None:
        """18 位身份证号 (前 17 数字 + 末位数字) → 检测到."""
        hits = self._scan("用户 110101199003075517 提交", tmp_path)
        assert "中国身份证号" in hits

    def test_china_id_card_with_x_checksum_detected(
        self, tmp_path: Path
    ) -> None:
        """18 位身份证号 (末位 X 校验) → 检测到."""
        hits = self._scan("ID: 11010119900307551X", tmp_path)
        assert "中国身份证号" in hits

    def test_short_number_not_detected(
        self, tmp_path: Path
    ) -> None:
        """少于 18 位数字 → 不应误报 (避免普通数字 false positive)."""
        hits = self._scan("year 2026 month 07", tmp_path)
        assert "中国身份证号" not in hits

    def test_long_number_not_match_id_card_pattern(
        self, tmp_path: Path
    ) -> None:
        """19+ 位数字 → 不应误报 (身份证严格 18 位)."""
        hits = self._scan("1234567890123456789", tmp_path)
        # 19 位数字可能匹配银行卡号, 但不应匹配身份证
        assert "中国身份证号" not in hits

    # ============================================================
    # 4. 中国手机号 (11 位)
    # ============================================================

    def test_china_mobile_detected(
        self, tmp_path: Path
    ) -> None:
        """13X-XXXX-XXXX 格式手机号 → 检测到."""
        hits = self._scan("电话: 13800138000", tmp_path)
        assert "中国手机号" in hits

    def test_china_mobile_various_prefix_detected(
        self, tmp_path: Path
    ) -> None:
        """各种 1[3-9] 开头手机号 → 检测到."""
        for mobile in ["13912345678", "15812345678", "17812345678", "18812345678"]:
            hits = self._scan(f"电话 {mobile}", tmp_path)
            assert "中国手机号" in hits, f"未检测到 {mobile}"

    def test_short_number_not_detected_as_mobile(
        self, tmp_path: Path
    ) -> None:
        """少于 11 位数字 → 不应误报."""
        hits = self._scan("order 12345", tmp_path)
        assert "中国手机号" not in hits

    def test_long_number_match_mobile_or_bankcard(
        self, tmp_path: Path
    ) -> None:
        """11 位数字 (1[3-9] 开头) → 至少匹配手机号."""
        hits = self._scan("13800138000", tmp_path)  # 1[3] 开头, 11 位
        assert "中国手机号" in hits

    def test_12_digit_not_match_mobile(
        self, tmp_path: Path
    ) -> None:
        """12 位数字 → 不应匹配手机号 (严格 11 位), 可能匹配银行卡."""
        hits = self._scan("123456789012", tmp_path)
        assert "中国手机号" not in hits

    # ============================================================
    # 5. 银行卡号 (13-19 位连续数字)
    # ============================================================

    def test_bank_card_16_digits_detected(
        self, tmp_path: Path
    ) -> None:
        """16 位 Visa/Mastercard 卡号 → 检测到."""
        hits = self._scan("card: 4532015112830366", tmp_path)
        assert "银行卡号" in hits

    def test_bank_card_with_dashes_detected(
        self, tmp_path: Path
    ) -> None:
        """16 位 + dash 分隔 (4-4-4-4) → 检测到."""
        hits = self._scan("card 4532-0151-1283-0366", tmp_path)
        assert "银行卡号" in hits

    def test_bank_card_with_spaces_detected(
        self, tmp_path: Path
    ) -> None:
        """16 位 + 空格分隔 (4 4 4 4) → 检测到."""
        hits = self._scan("card 4532 0151 1283 0366", tmp_path)
        assert "银行卡号" in hits

    def test_bank_card_13_digits_detected(
        self, tmp_path: Path
    ) -> None:
        """13 位旧 Visa 卡号 → 检测到."""
        hits = self._scan("card 4222222222222", tmp_path)
        assert "银行卡号" in hits

    def test_short_number_not_match_bankcard(
        self, tmp_path: Path
    ) -> None:
        """少于 13 位数字 → 不应匹配银行卡号."""
        hits = self._scan("order 1234567890", tmp_path)
        assert "银行卡号" not in hits


class TestSafetyGateExistingPatternsUnchanged:
    """回归测试: P1-1 新增 5 种不应破坏原有 9 种."""

    def test_aws_access_key_still_works(self, tmp_path: Path) -> None:
        """原有 AWS Access Key 检测不受影响."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "test.txt"
        target.write_text("AKIAIOSFODNN7EXAMPLE", encoding="utf-8")
        hits = _scan_file(target)
        assert "AWS Access Key" in hits

    def test_github_token_still_works(self, tmp_path: Path) -> None:
        """原有 GitHub Token 检测不受影响."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "test.txt"
        target.write_text("ghp_1234567890abcdefghijklmnopqrstuvwxyzAB", encoding="utf-8")
        hits = _scan_file(target)
        assert "GitHub Token" in hits

    def test_private_key_still_works(self, tmp_path: Path) -> None:
        """原有 Private Key 检测不受影响."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "test.txt"
        target.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
            encoding="utf-8",
        )
        hits = _scan_file(target)
        assert "Private Key" in hits

    def test_db_dsn_still_works(self, tmp_path: Path) -> None:
        """原有 DB DSN with password 检测不受影响."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "test.txt"
        target.write_text(
            'DB_URL = "postgres://admin:secretpass@localhost:5432/mydb"',
            encoding="utf-8",
        )
        hits = _scan_file(target)
        assert "DB DSN with password" in hits

    def test_clean_file_no_hits(self, tmp_path: Path) -> None:
        """干净文件无任何 secret 命中."""
        from auto_engineering.gates.safety import _scan_file

        target = tmp_path / "clean.py"
        target.write_text(
            '"""Clean module."""\n'
            "import os\n"
            "def hello() -> str:\n"
            '    return "Hello, world!"\n',
            encoding="utf-8",
        )
        hits = _scan_file(target)
        assert hits == [], f"clean 文件不应命中任何 secret, 实际: {hits}"