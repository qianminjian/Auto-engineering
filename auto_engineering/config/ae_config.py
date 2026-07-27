"""AeConfig — ae.toml project configuration reader (Phase 44).

Priority: os.environ > ae.toml > FeatureFlag.default_value

Usage::

    ae_config = AeConfig(project_root)  # reads ae.toml, merges os.environ
    val = ae_config.get("AE_PII_OUTBOUND")  # returns "redact" (default_value)
    val = ae_config.get("AE_OTLP_ENDPOINT")  # returns "" if not set

Injected into RuntimeConfig via cli/__init__.py → set_default_config().
"""

from __future__ import annotations

import logging
import os as _os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("ae.config")


# ae.toml [section] → {kebab-case key: AE_UPPER 环境变量名} 的唯一权威映射。
# 读取器 (_load_toml) 与生成器 (doctor._init_config) 共同派生于此常量，
# 保证模板产出的 key 与读取器识别的 key 永远一致（2026-07-26 真跑修复：
# 此前生成器输出 AE_UPPER key、读取器只认 kebab-case，模板不可用、开关假启用）。
SECTION_KEY_MAP: dict[str, dict[str, str]] = {
    "observability": {
        "audit-log": "AE_AUDIT_LOG",
        "metrics": "AE_METRICS",
        "otlp-endpoint": "AE_OTLP_ENDPOINT",
        "token-tracking": "AE_TOKEN_TRACKING",
        "audit-log-dir": "AE_AUDIT_LOG_DIR",
    },
    "debugging": {
        "debug": "AE_DEBUG",
        "log-level": "AE_LOG_LEVEL",
    },
    "safety": {
        "pii-enabled": "AE_PII_ENABLED",
        "pii-outbound": "AE_PII_OUTBOUND",
        "pii-inbound": "AE_PII_INBOUND",
        "pii-guardrail": "AE_PII_GUARDRAIL",
        "pii-guardrail-mode": "AE_PII_GUARDRAIL_MODE",
        "production": "AE_PRODUCTION",
        "strict-red": "AE_STRICT_RED",
    },
    "performance": {
        "max-tool-calls": "AE_MAX_TOOL_CALLS",
    },
    "threshold": {
        "gate-timeout": "AE_GATE_TIMEOUT",
    },
}


class AeConfig:
    """Project configuration reader.

    Reads ``<project_root>/ae.toml``, merges ``os.environ`` (higher priority),
    and falls back to ``FeatureFlag.default_value`` for any key not found.
    """

    def __init__(self, project_root: str | Path) -> None:
        self._project_root = Path(project_root)
        self._toml_data: dict[str, str] = {}
        self._load_toml()

    def _load_toml(self) -> None:
        """Load ae.toml, flatten [section] keys into AE_UPPER keys."""
        toml_path = self._project_root / "ae.toml"
        if not toml_path.exists():
            _logger.debug("ae.toml not found at %s, using env + defaults", toml_path)
            return

        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]  # 条件 import: tomllib/tomli 同名重绑定
            except ImportError:
                _logger.debug("tomllib/tomli not available, skipping ae.toml")
                return

        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            _logger.warning("ae.toml parse failed: %s", e)
            return

        # Flatten [section] → AE_UPPER key mapping
        # [observability] audit-log = true → AE_AUDIT_LOG=1
        # [safety] pii-outbound = "redact" → AE_PII_OUTBOUND=redact
        # 使用模块级 SECTION_KEY_MAP（与 doctor._init_config 生成器同源）
        for section, mapping in SECTION_KEY_MAP.items():
            if section in data and isinstance(data[section], dict):
                section_data = data[section]
                for toml_key, ae_key in mapping.items():
                    if toml_key in section_data:
                        val = section_data[toml_key]
                        if isinstance(val, bool):
                            val = "1" if val else "0"
                        elif isinstance(val, (int, float)):
                            val = str(val)
                        self._toml_data[ae_key] = str(val)

        _logger.debug("ae.toml loaded: %d keys from %s", len(self._toml_data), toml_path)

    def get(self, key: str) -> str:
        """Return value for *key* using priority: os.environ > ae.toml > default_value.

        Args:
            key: AE_* environment variable key (e.g. "AE_PII_OUTBOUND").

        Returns:
            String value (never None). Empty string if not set anywhere and no default_value.
        """
        # 1. os.environ (highest priority)
        env_val = _os.environ.get(key, "")
        if env_val:
            return env_val

        # 2. ae.toml
        toml_val = self._toml_data.get(key, "")
        if toml_val:
            return toml_val

        # 3. FeatureFlag.default_value (SSOT fallback)
        try:
            from auto_engineering.config.feature_flags import check_feature
            f = check_feature(key)
            return f.default_value
        except (KeyError, ImportError):
            return ""

    def toml_overlay(self) -> dict[str, str]:
        """Return ae.toml 提供的 {AE_KEY: value}（仅 ae.toml 值，不含默认）。

        用于 RuntimeConfig.from_project() 合并到 environ（BEACON #99）——
        os.environ 优先于本 overlay，本 overlay 优先于 FeatureFlag 默认值。
        """
        return dict(self._toml_data)
