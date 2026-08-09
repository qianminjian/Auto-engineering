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
from collections.abc import Mapping
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
        "config-policy": "AE_CONFIG_POLICY",
    },
    "performance": {
        "max-tool-calls": "AE_MAX_TOOL_CALLS",
    },
    "threshold": {
        "gate-timeout": "AE_GATE_TIMEOUT",
        "session-max-ticks": "AE_SESSION_MAX_TICKS",
        "session-max-seconds": "AE_SESSION_MAX_SECONDS",
        "context-soft-input": "AE_CONTEXT_SOFT_INPUT",
        "context-hard-input": "AE_CONTEXT_HARD_INPUT",
        "max-prompt-bytes": "AE_MAX_PROMPT_BYTES",
        "max-repair-cycles": "AE_MAX_REPAIR_CYCLES",
        "max-workers-per-stage": "AE_MAX_WORKERS_PER_STAGE",
        "max-workers-per-thread": "AE_MAX_WORKERS_PER_THREAD",
        "max-plate-audits": "AE_MAX_PLATE_AUDITS",
        "max-system-audits": "AE_MAX_SYSTEM_AUDITS",
        "max-worker-receipt-bytes": "AE_MAX_WORKER_RECEIPT_BYTES",
        "max-receipt-summary-bytes": "AE_MAX_RECEIPT_SUMMARY_BYTES",
    },
}

# 首次启动的宿主无关标准 Profile。未列出的项目沿用 FeatureManifest 默认值。
# 这里仅表达治理层推荐值，不改变内置 fallback；环境变量仍保持最高优先级。
STANDARD_PROFILE_OVERRIDES: dict[str, str] = {
    "AE_AUDIT_LOG": "1",
    "AE_METRICS": "1",
    "AE_TOKEN_TRACKING": "1",
    "AE_PRODUCTION": "1",
}

_DEPRECATED_PROFILE_KEYS = frozenset({
    "AE_SESSION_MAX_TICKS",
    "AE_SESSION_MAX_SECONDS",
    "AE_CONTEXT_SOFT_INPUT",
    "AE_CONTEXT_HARD_INPUT",
})


def standard_profile_values() -> dict[str, str]:
    """返回覆盖全部 FeatureManifest 项的标准 Profile。"""
    from auto_engineering.config.feature_flags import FEATURE_MANIFEST

    return {
        flag.key: STANDARD_PROFILE_OVERRIDES.get(flag.key, flag.default_value)
        for flag in FEATURE_MANIFEST
    }


def render_ae_toml(
    values: Mapping[str, str],
    *,
    generated_by: str,
) -> str:
    """按 SECTION_KEY_MAP 渲染可被 AeConfig 无损读取的 TOML。"""
    import json

    from auto_engineering.config.feature_flags import FEATURE_MANIFEST

    descriptions = {flag.key: flag.description for flag in FEATURE_MANIFEST}
    lines = [
        "# Auto-Engineering 项目配置",
        f"# 生成: {generated_by}",
        "# 优先级: 环境变量 > ae.toml > 内置默认值",
        "# key 使用 kebab-case；括号内为可覆盖它的环境变量名",
        "",
    ]
    for section, mapping in SECTION_KEY_MAP.items():
        lines.append(f"[{section}]")
        for toml_key, ae_key in mapping.items():
            if ae_key in _DEPRECATED_PROFILE_KEYS:
                continue
            value = values.get(ae_key, "")
            description = descriptions.get(ae_key, "")
            if value == "":
                lines.append(
                    f"# {toml_key} = \"\"  # {description} ({ae_key})，按需配置"
                )
            else:
                lines.append(
                    f"{toml_key} = {json.dumps(str(value), ensure_ascii=False)}"
                    f"  # {description} ({ae_key})"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


class AeConfig:
    """Project configuration reader.

    Reads ``<project_root>/ae.toml``, merges ``os.environ`` (higher priority),
    and falls back to ``FeatureFlag.default_value`` for any key not found.
    """

    def __init__(self, project_root: str | Path) -> None:
        self._project_root = Path(project_root)
        self._toml_data: dict[str, str] = {}
        self._load_error: str | None = None
        self._migration_warnings: list[str] = []
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
            self._load_error = str(e)
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
                        if ae_key in _DEPRECATED_PROFILE_KEYS:
                            self._migration_warnings.append(
                                f"{section}.{toml_key} 已弃用且不再控制正常续跑，"
                                "请删除该配置；会话连续性由宿主压缩与持久状态自动管理"
                            )
                        if isinstance(val, bool):
                            val = "1" if val else "0"
                        elif isinstance(val, (int, float)):
                            val = str(val)
                        self._toml_data[ae_key] = str(val)

        _logger.debug("ae.toml loaded: %d keys from %s", len(self._toml_data), toml_path)

    @property
    def load_error(self) -> str | None:
        """返回解析错误；成功或文件不存在时为 None。"""
        return self._load_error

    @property
    def migration_warnings(self) -> tuple[str, ...]:
        """返回需要向用户显式展示的旧配置迁移提示。"""
        return tuple(self._migration_warnings)

    @property
    def is_configured(self) -> bool:
        """文件存在、可解析且至少包含一个受支持的显式配置项。"""
        return (
            (self._project_root / "ae.toml").is_file()
            and self._load_error is None
            and bool(self._toml_data)
        )

    def source_for(self, key: str) -> str:
        """返回最终配置来源，不暴露配置值。"""
        if key in _os.environ:
            return "env"
        if key in self._toml_data:
            return "file"
        return "default"

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
