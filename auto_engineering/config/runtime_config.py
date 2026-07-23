"""RuntimeConfig — centralized env var access (P0-6).

Replaces scattered ``os.environ.get()`` calls with a single injectable config object.
Construct once at CLI entry, pass to all components via ``__init__``.

Usage::

    config = RuntimeConfig()                    # reads os.environ
    config = RuntimeConfig(environ=test_env)    # test injection
    config.is_active("AE_METRICS")              # feature flag check
    config.get("AE_PII_OUTBOUND", "redact")     # raw env access
    config.pii_enabled                          # typed shortcut
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration wrapping environment variables.

    Construct once at CLI entry point, inject into TickOrchestrator,
    StandaloneDriver, tools, gates, and guardrails via __init__.
    """

    environ: dict[str, str] = field(
        default_factory=lambda: dict(_os.environ), repr=False)

    # ── convenience accessors for frequently-checked flags ──

    @property
    def pii_enabled(self) -> bool:
        """AE_PII_ENABLED — master PII protection switch. Default True."""
        return self.get("AE_PII_ENABLED", "1").strip() != "0"

    @property
    def pii_outbound(self) -> str:
        """AE_PII_OUTBOUND mode: off / warn / block / redact. Default redact."""
        return self.get("AE_PII_OUTBOUND", "redact")

    @property
    def pii_inbound(self) -> str:
        """AE_PII_INBOUND mode: off / warn / block / redact. Default warn."""
        return self.get("AE_PII_INBOUND", "warn")

    @property
    def pii_guardrail(self) -> bool:
        """AE_PII_GUARDRAIL — PII file content scanning. Default True."""
        return self.get("AE_PII_GUARDRAIL", "1").strip() != "0"

    @property
    def pii_guardrail_mode(self) -> str:
        """AE_PII_GUARDRAIL_MODE: warn / block. Default warn."""
        return self.get("AE_PII_GUARDRAIL_MODE", "warn")

    @property
    def production_enabled(self) -> bool:
        """AE_PRODUCTION — production safety mode (strict RED + gate hardening)."""
        return self.get("AE_PRODUCTION", "").strip() == "1"

    @property
    def metrics_enabled(self) -> bool:
        """AE_METRICS — metrics collection active."""
        return self.get("AE_METRICS", "").strip() == "1"

    @property
    def token_tracking_enabled(self) -> bool:
        """AE_TOKEN_TRACKING — per-tick token JSONL collection."""
        return self.get("AE_TOKEN_TRACKING", "").strip() == "1"

    @property
    def token_source(self) -> str:
        """AE_TOKEN_SOURCE — provider or transcript."""
        return self.get("AE_TOKEN_SOURCE", "provider")

    @property
    def strict_red(self) -> bool:
        """AE_STRICT_RED — strict TDD REDGuardrail test-first enforcement."""
        return self.get("AE_STRICT_RED", "").strip() == "1"

    @property
    def production_mode(self) -> bool:
        """AE_PRODUCTION — strict REDGuardrail + block gate degradation."""
        return self.get("AE_PRODUCTION", "").strip() == "1"

    @property
    def debug_enabled(self) -> bool:
        """AE_DEBUG — debug tracing + detailed logging."""
        return self.get("AE_DEBUG", "").strip() == "1"

    @property
    def audit_log_enabled(self) -> bool:
        """AE_AUDIT_LOG — LLM call audit logging."""
        return self.get("AE_AUDIT_LOG", "").strip() == "1"

    @property
    def audit_log_dir(self) -> str | None:
        """AE_AUDIT_LOG_DIR — override audit log output directory."""
        val = self.get("AE_AUDIT_LOG_DIR", "").strip()
        return val if val else None

    @property
    def cache_control_enabled(self) -> bool:
        """AE_CACHE_CONTROL — Anthropic prompt caching. Default True."""
        return self.get("AE_CACHE_CONTROL", "").strip() != "0"

    @property
    def gate_timeout(self) -> int | None:
        """AE_GATE_TIMEOUT — gate execution timeout in seconds."""
        val = self.get("AE_GATE_TIMEOUT", "").strip()
        return int(val) if val else None

    @property
    def log_level(self) -> str:
        """AE_LOG_LEVEL — logging level. Default INFO."""
        return self.get("AE_LOG_LEVEL", "INFO").strip().upper()

    @property
    def otlp_endpoint(self) -> str | None:
        """AE_OTLP_ENDPOINT — OTLP tracing collector endpoint."""
        val = self.get("AE_OTLP_ENDPOINT", "").strip()
        return val if val else None

    @property
    def llm_provider(self) -> str:
        """AE_LLM_PROVIDER — default LLM provider."""
        return self.get("AE_LLM_PROVIDER", "")

    @property
    def max_tool_calls(self) -> int | None:
        """AE_MAX_TOOL_CALLS — max tool calls per agent."""
        val = self.get("AE_MAX_TOOL_CALLS", "").strip()
        return int(val) if val else None

    # ── provider credentials (NOT feature flags — secrets) ──

    @property
    def anthropic_api_key(self) -> str:
        return self.get("ANTHROPIC_API_KEY", "").strip()

    @property
    def anthropic_auth_token(self) -> str:
        return self.get("ANTHROPIC_AUTH_TOKEN", "").strip()

    @property
    def openai_api_key(self) -> str:
        return self.get("OPENAI_API_KEY", "").strip()

    @property
    def dashscope_api_key(self) -> str:
        return self.get("DASHSCOPE_API_KEY", "").strip()

    @property
    def zhipu_api_key(self) -> str:
        return self.get("ZHIPUAI_API_KEY", "").strip()

    @property
    def ollama_host(self) -> str | None:
        val = self.get("OLLAMA_HOST", "").strip()
        return val if val else None

    # ── runtime detection ──

    @property
    def is_claude_code(self) -> bool:
        return bool(
            self.get("CLAUDE_CODE")
            or self.get("CLAUDE_CODE_ENTRYPOINT")
        )

    @property
    def is_plugin_mode(self) -> bool:
        return self.is_claude_code or bool(self.anthropic_auth_token)

    @property
    def anthropic_cli(self) -> str:
        return self.get("ANTHROPIC_CLI", "").lower()

    @property
    def allow_no_sandbox(self) -> bool:
        return self.get("ALLOW_NO_SANDBOX", "").lower() == "true"

    # ── generic access (replaces os.environ.get()) ──

    def get(self, key: str, default: str = "") -> str:
        """Return env var value or default. Replaces ``os.environ.get(key, default)``."""
        return self.environ.get(key, default)

    def is_active(self, key: str) -> bool:
        """Check if a registered feature flag is active.

        Uses the FeatureManifest activation rules (including PII sub-flag
        suppression when AE_PII_ENABLED=0).
        """
        from auto_engineering.config.feature_flags import get_feature_status
        status = get_feature_status(self.environ)
        return status.get(key, {}).get("active", False)

    # ── factory ──

    @classmethod
    def from_environ(cls, environ: dict[str, str] | None = None) -> RuntimeConfig:
        """Create RuntimeConfig from an environ dict (defaults to os.environ)."""
        return cls(environ=dict(environ if environ is not None else _os.environ))


# Module-level sentinel — only for use at CLI entry points where injection hasn't
# been wired yet.  All library code should receive RuntimeConfig via __init__.
# This sentinel exists to avoid breaking the import graph during migration.
#
# Lifecycle:
#   1. CLI entry (ae <subcommand>) calls set_default_config(RuntimeConfig()) once
#   2. Library code calls get_default_config() — returns sentinel if set, else
#      creates a fresh RuntimeConfig from os.environ (test-compatible)
#   3. conftest.py autouse fixture resets _SENTINEL to None between tests
#
# Thread safety: each tick is a fresh process — no concurrent access. In tests,
# monkeypatch.setenv() + autouse reset ensures isolation without locking.
_SENTINEL: RuntimeConfig | None = None


def set_default_config(config: RuntimeConfig) -> None:
    """Set the process-wide default RuntimeConfig (CLI entry points only)."""
    global _SENTINEL
    _SENTINEL = config


def get_default_config() -> RuntimeConfig:
    """Return the process-wide RuntimeConfig.

    If set_default_config() was called (CLI entry), returns that instance.
    Otherwise creates a fresh RuntimeConfig from current os.environ — this
    preserves test compatibility with monkeypatch.setenv().
    """
    global _SENTINEL
    if _SENTINEL is not None:
        return _SENTINEL
    return RuntimeConfig()
