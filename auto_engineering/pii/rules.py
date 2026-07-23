"""PII detection rules and data model.

Design ref: v5.6-Design-Loop.md appendix E §E.3.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PIISeverity(Enum):
    CRITICAL = "CRITICAL"  # 身份证/手机号/银行卡/API Key — 必须脱敏
    WARN = "WARN"          # 邮箱 — 记录但不阻断


class PIICategory(Enum):
    PERSONAL_ID = "PERSONAL_ID"
    CONTACT = "CONTACT"
    FINANCIAL = "FINANCIAL"
    CREDENTIAL = "CREDENTIAL"
    PII = "PII"


@dataclass(frozen=True)
class PIIDetectionRule:
    """Single PII detection rule."""

    name: str
    pattern: str
    replacement: str
    severity: PIISeverity
    category: PIICategory
    description: str = ""
    exclusion_patterns: list[str] = field(default_factory=list)
    enabled: bool = True


# Built-in rule set (minimum bank scenario)
PII_RULES: list[PIIDetectionRule] = [
    PIIDetectionRule(
        name="cn_id_card",
        pattern=r"[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
        replacement="**********",
        severity=PIISeverity.CRITICAL,
        category=PIICategory.PERSONAL_ID,
        description="中国身份证号（18 位，含校验位）",
    ),
    PIIDetectionRule(
        name="cn_phone",
        pattern=r"\b1[3-9]\d{9}\b",
        replacement="****",
        severity=PIISeverity.CRITICAL,
        category=PIICategory.CONTACT,
        description="中国手机号（11 位）",
    ),
    PIIDetectionRule(
        name="bank_card",
        pattern=r"\b\d{16,19}\b",
        replacement="****",
        severity=PIISeverity.CRITICAL,
        category=PIICategory.FINANCIAL,
        description="银行卡号（16-19 位）",
        exclusion_patterns=[r"[0-9a-f]{40}", r"[0-9a-f]{64}", r"\d{10,15}\b", r"\d{4}-\d{2}-\d{2}", r"^\d{10,13}$"],
    ),
    PIIDetectionRule(
        name="api_key",
        pattern=r'(?:sk|api[_-]?key|token|secret|password|passwd)\s*[:=]\s*["\']?([^\s"\']+)["\']?',
        replacement="***REDACTED***",
        severity=PIISeverity.CRITICAL,
        category=PIICategory.CREDENTIAL,
        description="API Key / Token / 密码",
        # DS-14 (T153, 2026-07-23): 排除 URL hostname 中的 "api"（如 api.minimaxi.chat）
        # 和已脱敏占位符 ***REDACTED***、API 版本路径 /v1/ 等
        exclusion_patterns=[
            r"https?://[a-z0-9.-]+",  # URL hostname（含 api.xxx.com）
            r"\*\*\*REDACTED\*\*\*",  # 已脱敏占位符
            r"/v\d+/[a-z_]+",         # API 版本路径
        ],
    ),
    PIIDetectionRule(
        name="email",
        pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        replacement="***@***",
        severity=PIISeverity.WARN,
        category=PIICategory.PII,
        description="邮箱地址",
    ),
]

# File paths matching these patterns are NOT scanned for PII
PII_WHITELIST_PATTERNS: list[str] = [
    r"test.*pii",
    r"pii.*rule",
    r"_\w*pii\w*_pattern",
]
