"""PIIGuardrail — G10 post-agent file PII scan (T91).

Second defense line after prompt redaction (T56/T57). Scans developer
files_changed for PII patterns and blocks if found in block_mode.

Design ref: BEACON decisions #67/68.

PII patterns are sourced from pii/rules.py PII_RULES (SSOT), not duplicated.
"""

from __future__ import annotations

import re
from pathlib import Path

from auto_engineering.pii.rules import PII_RULES
from auto_engineering.shared.guardrail import Guardrail, GuardrailResult


class PIIGuardrail(Guardrail):
    """G10: Post-agent PII scan on developer output files.

    Scans all files in files_changed for PII patterns (phone, API key,
    ID card, bank card, email). In block_mode, detection produces a
    block verdict; otherwise produces a pass with warning message.

    Chain integration: GuardrailChain.default() includes this guardrail.
    """

    name = "PIIGuardrail"
    timing = "post"
    applies_to_stages = ("developer",)

    def __init__(self, project_root: Path | None = None, block_mode: bool | None = None) -> None:
        self._project_root = project_root
        if block_mode is None:
            from auto_engineering.config.runtime_config import get_default_config
            block_mode = get_default_config().pii_guardrail_mode == "block"
        self._block_mode = block_mode
        # Build scan patterns from PII_RULES SSOT (not duplicated)
        self._patterns: list[tuple[str, str, str]] = [
            (rule.name, rule.pattern, rule.description or rule.name)
            for rule in PII_RULES if rule.enabled
        ]
        if not self._patterns:
            import logging
            _logger = logging.getLogger("ae.pii.guardrail")
            _logger.warning("PIIGuardrail: no enabled PII_RULES — detection capability limited")

    def check(
        self,
        stage: str = "",
        state: object = None,
        project_root: Path | None = None,
        files_changed: list[str] | None = None,
    ) -> GuardrailResult:
        root = project_root or self._project_root or Path.cwd()

        if files_changed is None:
            files_changed = getattr(state, "files_changed", []) or [] if state is not None else []

        findings: list[str] = []
        for fpath in files_changed:
            full_path = root / fpath
            try:
                content = full_path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for line_no, line in enumerate(content.splitlines(), start=1):
                for name, pattern, desc in self._patterns:
                    if re.search(pattern, line):
                        findings.append(f"{fpath}:{line_no}: {desc} ({name})")

        if findings:
            action = "block" if self._block_mode else "retry"
            return GuardrailResult(
                action=action,
                message=f"PII detected in {len(findings)} location(s): {'; '.join(findings[:5])}"
                        + (f" ... and {len(findings) - 5} more" if len(findings) > 5 else ""),
            )
        return GuardrailResult()
