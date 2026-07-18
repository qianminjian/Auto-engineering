"""PII detection and redaction engine.

Design ref: v5.6-Design-Loop.md appendix E §E.3.2 (T56/T57).

Non-invasive design — inserted into BaseAgent.execute() call chain without
modifying existing function signatures. Fail-safe: redact + WARN by default;
block_mode is an optional switch.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_engineering.pii.rules import PIIDetectionRule

from auto_engineering.pii.rules import PIISeverity, PII_RULES, PII_WHITELIST_PATTERNS

logger = logging.getLogger(__name__)


class PIIBlockedError(Exception):
    """Raised in block_mode when a CRITICAL PII rule matches."""

    def __init__(self, rule_name: str, category: str) -> None:
        self.rule_name = rule_name
        self.category = category
        super().__init__(f"PII blocked: {rule_name} ({category})")


class PIIRedactor:
    """PII detection and redaction engine.

    Usage::

        redactor = PIIRedactor()
        clean_messages = redactor.scan(messages)         # T56 — prompt messages
        clean_text = redactor.scan_text(tool_output)      # T57 — tool results
    """

    def __init__(
        self,
        rules: list[PIIDetectionRule] | None = None,
        whitelist_patterns: list[str] | None = None,
        block_mode: bool = False,
    ) -> None:
        self._rules = rules if rules is not None else PII_RULES
        self._whitelist = whitelist_patterns if whitelist_patterns is not None else PII_WHITELIST_PATTERNS
        self._block_mode = block_mode

    # ---- public API ----------------------------------------------------

    def scan(self, messages: list[dict]) -> list[dict]:
        """Scan and redact PII in *messages* (T56 entry point).

        Returns a redacted **copy** — the input is never mutated.
        """
        redacted: list[dict] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                redacted.append({**msg, "content": self.scan_text(content)})
            elif isinstance(content, list):
                new_blocks = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        new_blocks.append({**block, "text": self.scan_text(block["text"])})
                    else:
                        new_blocks.append(block)
                redacted.append({**msg, "content": new_blocks})
            else:
                redacted.append(msg)
        return redacted

    def scan_text(self, text: str, source: str = "") -> str:
        """Scan a single text block and redact PII (T57 entry point)."""
        if self._is_whitelisted(source):
            return text

        result = text
        for rule in self._rules:
            if not rule.enabled:
                continue
            for match in re.finditer(rule.pattern, text):
                matched_text = match.group()
                if any(re.search(ep, matched_text) for ep in rule.exclusion_patterns):
                    continue
                result = result.replace(matched_text, rule.replacement, 1)
                logger.warning(
                    "PII detected: rule=%s category=%s severity=%s source=%s",
                    rule.name,
                    rule.category.value,
                    rule.severity.value,
                    source or "prompt",
                )
                if self._block_mode and rule.severity == PIISeverity.CRITICAL:
                    raise PIIBlockedError(rule.name, rule.category.value)
        return result

    # ---- internal ------------------------------------------------------

    def _is_whitelisted(self, source: str) -> bool:
        if not source:
            return False
        return any(re.search(p, source) for p in self._whitelist)
