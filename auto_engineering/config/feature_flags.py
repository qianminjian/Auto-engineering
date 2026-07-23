"""FeatureManifest SSOT — 所有功能开关的集中定义 (T114).

新增任何 ``AE_*`` 环境变量必须先在此注册 FeatureFlag,
否则 ``test_feature_manifest_coverage`` 会阻断 CI。

约束:
    - ae doctor 自动从此清单渲染「可选功能」面板
    - --init stderr 一行功能状态来自此清单
    - action JSON ``feature_status`` 字段来自此清单

与 RuntimeConfig 的分层关系 (T135f):
    - **FeatureManifest** (本文件): What features exist — 声明层。定义所有 AE_* 开关的
      元数据 (key/description/category/agent_mode/default_active)。只描述"有什么"，
      不直接消费 env var。
    - **RuntimeConfig** (runtime_config.py): How to access — 访问层。提供 typed
      properties (e.g. ``metrics_enabled``→``self.get("AE_METRICS")``) 供业务代码调用。
      进程级 sentinel 模式: CLI 入口 ``set_default_config()`` 一次, 业务代码
      ``get_default_config()`` 随处取。
    - **迁移规则**: 新增 AE_* 环境变量 → 先在 FEATURE_MANIFEST 注册 FeatureFlag →
      然后在 RuntimeConfig 添加 typed property → 业务代码通过 property 读取。
      check_feature() guard 函数在 CI 中验证此规则。

Lifecycle: FEATURE_MANIFEST 是模块级常量列表 — 导入时初始化, 进程存活期不变.
get_feature_status() 在每次调用时从 os.environ 读取实时值, 无缓存.
feature_warnings() 在 --init 时调用, 向用户提示默认关闭的生产相关功能.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AgentMode = Literal["both", "standalone_only", "agent_only"]
Category = Literal[
    "observability", "performance", "debugging",
    "provider", "safety", "threshold",
]


@dataclass
class FeatureFlag:
    """单个功能开关的元数据."""

    key: str
    description: str
    category: Category
    agent_mode: AgentMode = "both"
    activation: str = ""
    default_active: bool = False

    def __post_init__(self) -> None:
        if not self.activation:
            self.activation = f"{self.key}=1"


FEATURE_MANIFEST: list[FeatureFlag] = [
    # ── observability ──
    FeatureFlag("AE_AUDIT_LOG", "LLM 调用审计日志 (JSONL)",
                "observability", "both", "AE_AUDIT_LOG=1"),
    FeatureFlag("AE_METRICS", "AI Coding 度量与自进化体系",
                "observability", "both", "AE_METRICS=1"),
    FeatureFlag("AE_OTLP_ENDPOINT", "OTLP 分布式追踪导出",
                "observability", "both", "export AE_OTLP_ENDPOINT=http://localhost:4317"),
    FeatureFlag("AE_TOKEN_TRACKING", "逐 Tick Token JSONL 采集 (M5)",
                "observability", "both", "AE_TOKEN_TRACKING=1"),
    FeatureFlag("AE_TOKEN_SOURCE", "Token 数据源选择 (provider/transcript)",
                "observability", "both", "AE_TOKEN_SOURCE=transcript"),

    # ── debugging ──
    FeatureFlag("AE_DEBUG", "调试模式 — DebugTracer 诊断轨迹 + 详细日志",
                "debugging", "both", "AE_DEBUG=1 或 --debug"),
    FeatureFlag("AE_LOG_LEVEL", "日志级别 (DEBUG/INFO/WARNING/ERROR)",
                "debugging", "both", "export AE_LOG_LEVEL=DEBUG"),

    # ── performance ──
    FeatureFlag("AE_CACHE_CONTROL", "Anthropic Prompt Caching (缓存命中降延迟)",
                "performance", "standalone_only", "AE_CACHE_CONTROL=1",
                default_active=True),
    FeatureFlag("AE_MAX_TOOL_CALLS", "单 Agent 最大工具调用次数",
                "performance", "both", "AE_MAX_TOOL_CALLS=20"),

    # ── provider ──
    FeatureFlag("AE_LLM_PROVIDER", "默认 LLM Provider (anthropic/deepseek/glm)",
                "provider", "both", "AE_LLM_PROVIDER=anthropic"),
    FeatureFlag("AE_MODEL_ROLE", "按 role 覆盖默认模型 (格式: AE_MODEL_<ROLE>_UPPER)",
                "provider", "standalone_only",
                "AE_MODEL_ARCHITECT=claude-sonnet-4-6"),
    FeatureFlag("AE_PROVIDER_ROLE", "按 role 覆盖 Provider (格式: AE_PROVIDER_<ROLE>_UPPER)",
                "provider", "standalone_only",
                "AE_PROVIDER_CRITIC=deepseek"),

    # ── safety ──
    FeatureFlag("AE_PII_ENABLED", "PII 四层文件桥接防护总开关 (L1-L4)",
                "safety", "both", "AE_PII_ENABLED=1", default_active=True),
    FeatureFlag("AE_PII_GUARDRAIL", "G11 PII Guardrail — 文件内容扫描 (L4)",
                "safety", "both", "AE_PII_GUARDRAIL=1 (需 AE_PII_ENABLED=1)"),
    FeatureFlag("AE_PII_GUARDRAIL_MODE", "G11 PII Guardrail 模式 (warn/block)",
                "safety", "both", "AE_PII_GUARDRAIL_MODE=warn (需 AE_PII_GUARDRAIL=1)"),
    FeatureFlag("AE_PII_INBOUND", "L3 — inbound result JSON PII 扫描模式 (off/warn/block/redact)",
                "safety", "both", "AE_PII_INBOUND=warn (需 AE_PII_ENABLED=1)"),
    FeatureFlag("AE_PII_OUTBOUND", "L2 — outbound action JSON PII 脱敏模式 (off/warn/block/redact)",
                "safety", "both", "AE_PII_OUTBOUND=redact (需 AE_PII_ENABLED=1)"),
    FeatureFlag("AE_PRODUCTION", "生产安全模式 — 严格 REDGuardrail + 阻断 Gate 降级",
                "safety", "both", "AE_PRODUCTION=1"),
    FeatureFlag("AE_AUDIT_LOG_DIR", "审计日志输出目录 (JSONL)",
                "observability", "both", "AE_AUDIT_LOG_DIR=/path/to/logs"),
    FeatureFlag("AE_STRICT_RED", "严格 TDD REDGuardrail — test-first 强制 (仅 Plugin 模式)",
                "safety", "agent_only", "AE_STRICT_RED=1"),

    # ── threshold ──
    FeatureFlag("AE_GATE_TIMEOUT", "Gate 执行超时秒数 (safety/lint/type_check 等)",
                "threshold", "both", "AE_GATE_TIMEOUT=120"),
]

# PII sub-flags — disabled when AE_PII_ENABLED=0
_PII_SUB_FLAGS = frozenset({
    "AE_PII_GUARDRAIL", "AE_PII_GUARDRAIL_MODE",
    "AE_PII_INBOUND", "AE_PII_OUTBOUND",
})

# Flags considered "active" when their env var has a non-empty value
# (not just "1").  OTLP endpoint needs a URL, not a boolean.
_ENDPOINT_STYLE_FLAGS = frozenset({"AE_OTLP_ENDPOINT"})


def check_feature(key: str) -> FeatureFlag:
    """Look up a FeatureFlag by env var key.

    Raises KeyError if *key* is not registered in FEATURE_MANIFEST.
    """
    for f in FEATURE_MANIFEST:
        if f.key == key:
            return f
    raise KeyError(f"Feature flag '{key}' not in FEATURE_MANIFEST. "
                   f"Register it in auto_engineering/config/feature_flags.py")


def get_feature_status(environ: dict | None = None) -> dict[str, dict]:
    """Return activation status for every registered feature flag.

    Args:
        environ: os.environ-like dict (defaults to os.environ).

    Returns:
        {key: {"active": bool, "category": ..., "agent_mode": ..., "description": ...}}
    """
    import os as _os
    env = environ if environ is not None else _os.environ

    pii_enabled = _is_active("AE_PII_ENABLED", env)

    result: dict[str, dict] = {}
    for f in FEATURE_MANIFEST:
        active = _is_active(f.key, env, f.default_active)

        # AE_PII_ENABLED=0 disables all PII sub-flags
        if f.key in _PII_SUB_FLAGS and not pii_enabled:
            active = False

        result[f.key] = {
            "active": active,
            "category": f.category,
            "agent_mode": f.agent_mode,
            "description": f.description,
            "activation": f.activation,
        }
    return result


def list_categories() -> list[str]:
    """Return sorted list of unique categories used in the manifest."""
    return sorted({f.category for f in FEATURE_MANIFEST})


def feature_status_oneline(environ: dict | None = None) -> str:
    """Return a one-line feature status summary for stderr (T114 5.3).

    Example: ``[Features] OTLP:✗ Audit:✗ Metrics:✗ Debug:✗ PII:✓ Cache:✓(Standalone)``
    """
    status = get_feature_status(environ)
    short_names = {
        "AE_AUDIT_LOG": "Audit", "AE_METRICS": "Metrics",
        "AE_OTLP_ENDPOINT": "OTLP",
        "AE_DEBUG": "Debug", "AE_CACHE_CONTROL": "Cache",
        "AE_PII_ENABLED": "PII", "AE_TOKEN_TRACKING": "Token",
    }
    parts: list[str] = []
    for key, name in short_names.items():
        s = status.get(key, {})
        active = s.get("active", False)
        mark = "✓" if active else "✗"
        mode = s.get("agent_mode", "both")
        suffix = f"({mode.replace('standalone_only', 'Standalone').replace('agent_only', 'Agent')})" if mode != "both" and active else ""
        parts.append(f"{name}:{mark}{suffix}")
    return "[Features] " + " ".join(parts)


def feature_warnings(environ: dict | None = None) -> list[str]:
    """Return warnings for important production features that are currently disabled.

    Used by --init stderr output to inform users about features they may want to enable.
    """
    status = get_feature_status(environ)
    warnings: list[str] = []
    # Production safety features
    if not status.get("AE_PII_ENABLED", {}).get("active"):
        warnings.append("PII 脱敏未启用 (AE_PII_ENABLED=1)")
    if not status.get("AE_METRICS", {}).get("active"):
        warnings.append("度量采集未启用 (AE_METRICS=1) — 无 AI Coding 信号数据")
    if not status.get("AE_AUDIT_LOG", {}).get("active"):
        warnings.append("审计日志未启用 (AE_AUDIT_LOG=1)")
    if not status.get("AE_OTLP_ENDPOINT", {}).get("active"):
        warnings.append("无 observability 后端 (设置 AE_OTLP_ENDPOINT)")
    return warnings


def feature_status_for_action(environ: dict | None = None) -> dict[str, bool]:
    """Return a compact {key: active} dict for action JSON ``feature_status`` (T114 5.4)."""
    status = get_feature_status(environ)
    return {key: s["active"] for key, s in status.items()}


def _is_active(key: str, env: dict, default: bool = False) -> bool:
    """Determine if a feature flag is active from the environment."""
    val = env.get(key, "").strip()
    if not val:
        return default
    if key in _ENDPOINT_STYLE_FLAGS:
        return True  # any non-empty value activates
    if key == "AE_PII_ENABLED":
        return val != "0"
    # Boolean-style: "1" or "true" activates
    return val == "1" or val.lower() == "true"
