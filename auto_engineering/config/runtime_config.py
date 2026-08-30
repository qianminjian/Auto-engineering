"""RuntimeConfig — centralized env var access (P0-6).

Phase 44: 所有 property 默认值从 FeatureFlag.default_value 读取（SSOT）。
不再在 RuntimeConfig 中硬编码默认值。

Usage::

    config = RuntimeConfig()                    # reads os.environ + FeatureFlag defaults
    config = RuntimeConfig(environ=test_env)    # test injection
    config.pii_enabled                          # typed shortcut
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from auto_engineering.host import HostPlatform, detect_host

if TYPE_CHECKING:
    from auto_engineering.loop.context_budget import ContextBudgetPolicy
    from auto_engineering.loop.loop_budget import LoopBudgetPolicy


def _default(key: str) -> str:
    """Return FeatureFlag.default_value for *key* (Phase 44 SSOT)."""
    from auto_engineering.config.feature_flags import check_feature
    return check_feature(key).default_value


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration wrapping environment variables.

    Construct once at CLI entry point, inject into TickOrchestrator,
    tools, gates, and guardrails via __init__.
    """

    environ: dict[str, str] = field(
        default_factory=lambda: dict(_os.environ), repr=False)

    # ── convenience accessors for frequently-checked flags ──

    @property
    def pii_enabled(self) -> bool:
        return self.get("AE_PII_ENABLED", _default("AE_PII_ENABLED")).strip() != "0"

    @property
    def pii_outbound(self) -> str:
        return self.get("AE_PII_OUTBOUND", _default("AE_PII_OUTBOUND"))

    @property
    def pii_inbound(self) -> str:
        return self.get("AE_PII_INBOUND", _default("AE_PII_INBOUND"))

    @property
    def pii_guardrail(self) -> bool:
        return self.get("AE_PII_GUARDRAIL", _default("AE_PII_GUARDRAIL")).strip() != "0"

    @property
    def pii_guardrail_mode(self) -> str:
        return self.get("AE_PII_GUARDRAIL_MODE", _default("AE_PII_GUARDRAIL_MODE"))

    @property
    def production_enabled(self) -> bool:
        return self.get("AE_PRODUCTION", _default("AE_PRODUCTION")).strip() == "1"

    @property
    def metrics_enabled(self) -> bool:
        return self.get("AE_METRICS", _default("AE_METRICS")).strip() == "1"

    @property
    def token_tracking_enabled(self) -> bool:
        return self.get("AE_TOKEN_TRACKING", _default("AE_TOKEN_TRACKING")).strip() == "1"

    @property
    def strict_red(self) -> bool:
        return self.get("AE_STRICT_RED", _default("AE_STRICT_RED")).strip() == "1"

    @property
    def config_policy(self) -> str:
        return self.get("AE_CONFIG_POLICY", _default("AE_CONFIG_POLICY")).strip()

    @property
    def production_mode(self) -> bool:
        """Phase 44: AE_PRODUCTION duplicate. Alias for production_enabled."""
        return self.production_enabled

    @property
    def debug_enabled(self) -> bool:
        return self.get("AE_DEBUG", _default("AE_DEBUG")).strip() == "1"

    @property
    def audit_log_enabled(self) -> bool:
        return self.get("AE_AUDIT_LOG", _default("AE_AUDIT_LOG")).strip() == "1"

    @property
    def audit_log_dir(self) -> str | None:
        val = self.get("AE_AUDIT_LOG_DIR", _default("AE_AUDIT_LOG_DIR")).strip()
        return val if val else None

    @property
    def gate_timeout(self) -> int | None:
        val = self.get("AE_GATE_TIMEOUT", _default("AE_GATE_TIMEOUT")).strip()
        return int(val) if val else None

    @property
    def log_level(self) -> str:
        return self.get("AE_LOG_LEVEL", _default("AE_LOG_LEVEL")).strip().upper()

    @property
    def otlp_endpoint(self) -> str | None:
        val = self.get("AE_OTLP_ENDPOINT", _default("AE_OTLP_ENDPOINT")).strip()
        return val if val else None

    @property
    def max_tool_calls(self) -> int | None:
        val = self.get("AE_MAX_TOOL_CALLS", _default("AE_MAX_TOOL_CALLS")).strip()
        return int(val) if val else None

    @property
    def session_max_ticks(self) -> int:
        return int(self.get("AE_SESSION_MAX_TICKS", _default("AE_SESSION_MAX_TICKS")).strip())

    @property
    def session_max_seconds(self) -> int:
        return int(self.get("AE_SESSION_MAX_SECONDS", _default("AE_SESSION_MAX_SECONDS")).strip())

    @property
    def host_budget_enforcement(self) -> str:
        """宿主预算模式；默认 soft，只有显式 hard 才允许停机。"""

        value = self.get("AE_HOST_BUDGET_ENFORCEMENT",
                         _default("AE_HOST_BUDGET_ENFORCEMENT")).strip().lower()
        if value not in {"soft", "hard"}:
            raise ValueError("AE_HOST_BUDGET_ENFORCEMENT 必须为 soft 或 hard")
        return value

    @property
    def context_soft_input(self) -> int:
        return int(self.get("AE_CONTEXT_SOFT_INPUT", _default("AE_CONTEXT_SOFT_INPUT")).strip())

    @property
    def context_hard_input(self) -> int:
        return int(self.get("AE_CONTEXT_HARD_INPUT", _default("AE_CONTEXT_HARD_INPUT")).strip())

    @property
    def max_prompt_bytes(self) -> int:
        return int(self.get("AE_MAX_PROMPT_BYTES", _default("AE_MAX_PROMPT_BYTES")).strip())

    @property
    def context_budget_policy(self) -> ContextBudgetPolicy:
        """构建 Action 大小策略；旧会话阈值只保留兼容观测，不参与决策。"""
        from auto_engineering.loop.context_budget import ContextBudgetPolicy

        return ContextBudgetPolicy(
            policy_id="context-budget-v2",
            max_session_ticks=int(_default("AE_SESSION_MAX_TICKS")),
            max_session_wall_seconds=int(_default("AE_SESSION_MAX_SECONDS")),
            soft_input_units=int(_default("AE_CONTEXT_SOFT_INPUT")),
            hard_input_units=int(_default("AE_CONTEXT_HARD_INPUT")),
            max_prompt_bytes=self.max_prompt_bytes,
        )

    @property
    def max_worker_receipt_bytes(self) -> int:
        return int(self.get("AE_MAX_WORKER_RECEIPT_BYTES", _default("AE_MAX_WORKER_RECEIPT_BYTES")).strip())

    @property
    def max_receipt_summary_bytes(self) -> int:
        return int(self.get("AE_MAX_RECEIPT_SUMMARY_BYTES", _default("AE_MAX_RECEIPT_SUMMARY_BYTES")).strip())

    @property
    def host_max_elapsed_seconds(self) -> float | None:
        value = self.get("AE_HOST_MAX_ELAPSED_SECONDS", _default("AE_HOST_MAX_ELAPSED_SECONDS"))
        return float(value.strip()) if value.strip() else None

    @property
    def host_max_cost_usd(self) -> float | None:
        value = self.get("AE_HOST_MAX_COST_USD", _default("AE_HOST_MAX_COST_USD")).strip()
        return float(value) if value else None

    @property
    def host_max_output_tokens(self) -> int | None:
        value = self.get("AE_HOST_MAX_OUTPUT_TOKENS", _default("AE_HOST_MAX_OUTPUT_TOKENS")).strip()
        return int(value) if value else None

    @property
    def max_repair_cycles(self) -> int:
        return int(self.get("AE_MAX_REPAIR_CYCLES", _default("AE_MAX_REPAIR_CYCLES")))

    @property
    def max_workers_per_stage(self) -> int:
        return int(self.get("AE_MAX_WORKERS_PER_STAGE", _default("AE_MAX_WORKERS_PER_STAGE")))

    @property
    def max_workers_per_thread(self) -> int:
        return int(self.get("AE_MAX_WORKERS_PER_THREAD", _default("AE_MAX_WORKERS_PER_THREAD")))

    @property
    def max_plate_audits(self) -> int:
        return int(self.get("AE_MAX_PLATE_AUDITS", _default("AE_MAX_PLATE_AUDITS")))

    @property
    def max_system_audits(self) -> int:
        return int(self.get("AE_MAX_SYSTEM_AUDITS", _default("AE_MAX_SYSTEM_AUDITS")))

    @property
    def loop_budget_policy(self) -> LoopBudgetPolicy:
        from auto_engineering.loop.loop_budget import LoopBudgetPolicy

        return LoopBudgetPolicy(
            policy_id="loop-budget-v1",
            max_repair_cycles=self.max_repair_cycles,
            max_workers_per_stage=self.max_workers_per_stage,
            max_workers_per_thread=self.max_workers_per_thread,
            max_plate_audits=self.max_plate_audits,
            max_system_audits=self.max_system_audits,
        )

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
    def host_platform(self) -> HostPlatform:
        return detect_host(self.environ).platform

    @property
    def is_claude_code(self) -> bool:
        return self.host_platform is HostPlatform.CLAUDE_CODE

    @property
    def is_plugin_mode(self) -> bool:
        return (
            self.host_platform is not HostPlatform.UNKNOWN
            or bool(self.anthropic_auth_token)
        )

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

    @classmethod
    def from_project(cls, project_root: str | Path) -> RuntimeConfig:
        """Build RuntimeConfig merging ae.toml under os.environ (BEACON #99).

        Priority: os.environ > ae.toml > FeatureFlag.default_value。
        ae.toml 值 overlay 进 environ dict，使所有 property / is_active /
        setup_tracing 都 honoring 项目配置；os.environ 仍按 SSOT 优先级覆盖。
        ae.toml 缺失时 overlay 为空 → 等价于 RuntimeConfig()（行为不变）。

        2026-07-26 真跑修复: 此前 CLI 入口用 RuntimeConfig()（仅 os.environ），
        ae.toml 从未注入 → 项目配置的开关在引擎运行时全部静默失效。
        """
        from auto_engineering.config.ae_config import AeConfig
        overlay = AeConfig(project_root).toml_overlay()
        merged = {**overlay, **dict(_os.environ)}
        return cls(environ=merged)


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
