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

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# 2026-07-26 删除进程内独立驱动路径后，"standalone_only" 模式值移除
# （0 个活跃 flag 使用），仅余 both / agent_only。
AgentMode = Literal["both", "agent_only"]
Category = Literal[
    "observability", "performance", "debugging",
    "safety", "threshold",
]


@dataclass
class FeatureFlag:
    """单个功能开关的元数据.

    Phase 44: default_value 是全项目唯一默认值来源。
    优先级: os.environ > ae.toml > default_value.
    """

    key: str
    description: str
    category: Category
    default_value: str = ""     # Phase 44: SSOT 默认值（未设置环境变量/ae.toml 时使用）
    agent_mode: AgentMode = "both"
    activation: str = ""
    default_active: bool = False  # doctor 面板显示用（与 default_value 解耦）

    def __post_init__(self) -> None:
        if not self.activation:
            self.activation = f"{self.key}=1"


FEATURE_MANIFEST: list[FeatureFlag] = [
    # ── observability ──
    FeatureFlag("AE_AUDIT_LOG", "LLM 调用审计日志 (JSONL)",
                "observability", default_value="0", activation="AE_AUDIT_LOG=1"),
    FeatureFlag("AE_METRICS", "AI Coding 度量与自进化体系",
                "observability", default_value="0", activation="AE_METRICS=1"),
    FeatureFlag("AE_OTLP_ENDPOINT", "OTLP 分布式追踪导出",
                "observability", default_value="", activation="export AE_OTLP_ENDPOINT=http://localhost:4317"),
    FeatureFlag("AE_TOKEN_TRACKING", "逐 Tick Token JSONL 采集 (M5)",
                "observability", default_value="0", activation="AE_TOKEN_TRACKING=1"),

    # ── debugging ──
    FeatureFlag("AE_DEBUG", "调试模式 — DebugTracer 诊断轨迹 + 详细日志",
                "debugging", default_value="0", activation="AE_DEBUG=1 或 --debug"),
    FeatureFlag("AE_LOG_LEVEL", "日志级别 (DEBUG/INFO/WARNING/ERROR)",
                "debugging", default_value="INFO", activation="export AE_LOG_LEVEL=DEBUG"),

    # ── performance ──
    # Phase 42: AE_CACHE_CONTROL 已随进程内独立驱动路径删除
    FeatureFlag("AE_MAX_TOOL_CALLS", "单 Agent 最大工具调用次数",
                "performance", default_value="20", activation="AE_MAX_TOOL_CALLS=20"),

    # ── safety ──
    FeatureFlag("AE_PII_ENABLED", "PII 四层文件桥接防护总开关 (L1-L4)",
                "safety", default_value="1", default_active=True,
                activation="AE_PII_ENABLED=1"),
    FeatureFlag("AE_PII_GUARDRAIL", "G11 PII Guardrail — 文件内容扫描 (L4)",
                "safety", default_value="1", activation="AE_PII_GUARDRAIL=1"),
    FeatureFlag("AE_PII_GUARDRAIL_MODE", "G11 PII Guardrail 模式 (warn/block)",
                "safety", default_value="warn", activation="AE_PII_GUARDRAIL_MODE=warn"),
    FeatureFlag("AE_PII_INBOUND", "L3 — inbound result JSON PII 扫描",
                "safety", default_value="warn", activation="AE_PII_INBOUND=warn"),
    FeatureFlag("AE_PII_OUTBOUND", "L2 — outbound action JSON PII 脱敏",
                "safety", default_value="redact", activation="AE_PII_OUTBOUND=redact"),
    FeatureFlag("AE_PRODUCTION", "生产安全模式",
                "safety", default_value="0", activation="AE_PRODUCTION=1"),
    FeatureFlag("AE_AUDIT_LOG_DIR", "审计日志输出目录 (JSONL)",
                "observability", default_value="", activation="AE_AUDIT_LOG_DIR=/path/to/logs"),
    FeatureFlag("AE_STRICT_RED", "严格 TDD REDGuardrail — test-first 强制",
                "safety", default_value="0", agent_mode="agent_only",
                activation="AE_STRICT_RED=1"),
    FeatureFlag("AE_CONFIG_POLICY", "非交互首次配置策略",
                "safety", default_value="",
                activation="AE_CONFIG_POLICY=require|defaults|create"),

    # ── threshold ──
    FeatureFlag("AE_GATE_TIMEOUT", "Gate 执行超时秒数",
                "threshold", default_value="", activation="AE_GATE_TIMEOUT=120"),
    FeatureFlag("AE_SESSION_MAX_TICKS", "单宿主会话最大 Tick 数",
                "threshold", default_value="50", activation="AE_SESSION_MAX_TICKS=50"),
    FeatureFlag("AE_SESSION_MAX_SECONDS", "单宿主会话最大持续秒数",
                "threshold", default_value="3600", activation="AE_SESSION_MAX_SECONDS=3600"),
    FeatureFlag("AE_CONTEXT_SOFT_INPUT", "会话输入用量软上限",
                "threshold", default_value="600000", activation="AE_CONTEXT_SOFT_INPUT=600000"),
    FeatureFlag("AE_CONTEXT_HARD_INPUT", "会话输入用量硬上限",
                "threshold", default_value="700000", activation="AE_CONTEXT_HARD_INPUT=700000"),
    FeatureFlag("AE_MAX_PROMPT_BYTES", "单个 Action Prompt 最大字节数",
                "threshold", default_value="200000", activation="AE_MAX_PROMPT_BYTES=200000"),
    FeatureFlag("AE_MAX_REPAIR_CYCLES", "单线程最大修复循环数",
                "threshold", default_value="6", activation="AE_MAX_REPAIR_CYCLES=6"),
    FeatureFlag("AE_MAX_WORKERS_PER_STAGE", "单 Stage 最大 Worker 数",
                "threshold", default_value="5", activation="AE_MAX_WORKERS_PER_STAGE=5"),
    FeatureFlag("AE_MAX_WORKERS_PER_THREAD", "单线程最大累计 Worker 数",
                "threshold", default_value="50", activation="AE_MAX_WORKERS_PER_THREAD=50"),
    FeatureFlag("AE_MAX_PLATE_AUDITS", "单线程最大 Plate Audit 次数",
                "threshold", default_value="3", activation="AE_MAX_PLATE_AUDITS=3"),
    FeatureFlag("AE_MAX_SYSTEM_AUDITS", "单线程最大 System Audit 次数",
                "threshold", default_value="3", activation="AE_MAX_SYSTEM_AUDITS=3"),
    FeatureFlag("AE_MAX_WORKER_RECEIPT_BYTES", "Worker Receipt 最大字节数",
                "threshold", default_value="4096", activation="AE_MAX_WORKER_RECEIPT_BYTES=4096"),
    FeatureFlag("AE_MAX_RECEIPT_SUMMARY_BYTES", "Worker Receipt 摘要最大字节数",
                "threshold", default_value="2048", activation="AE_MAX_RECEIPT_SUMMARY_BYTES=2048"),
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

    Example: ``[功能] OTLP:✗ 审计:✗ 度量:✗ 调试:✗ PII:✓ Token:✗``
    """
    status = get_feature_status(environ)
    # 2026-07-26 审计修复 (P2-2): 用户可见短名中文化 (OTLP/PII/Token 技术术语保留英文)
    short_names = {
        "AE_AUDIT_LOG": "审计", "AE_METRICS": "度量",
        "AE_OTLP_ENDPOINT": "OTLP",
        "AE_DEBUG": "调试",
        "AE_PII_ENABLED": "PII", "AE_TOKEN_TRACKING": "Token",
    }
    parts: list[str] = []
    for key, name in short_names.items():
        s = status.get(key, {})
        active = s.get("active", False)
        mark = "✓" if active else "✗"
        mode = s.get("agent_mode", "both")
        suffix = ""
        if mode != "both" and active:
            suffix = f"({mode.replace('agent_only', '仅 Agent')})"
        parts.append(f"{name}:{mark}{suffix}")
    return "[功能] " + " ".join(parts)


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
    else:
        # AD3: 需求计数可见性 — 告知用户距离阈值学习激活还差多少
        req_count = _count_requirements()
        if req_count is not None and req_count < 30:
            remaining = 30 - req_count
            warnings.append(
                f"度量需求计数: {req_count}/30 — "
                f"还差 {remaining} 个需求激活贝叶斯阈值学习 (ThresholdLearner)"
            )
    if not status.get("AE_AUDIT_LOG", {}).get("active"):
        warnings.append("审计日志未启用 (AE_AUDIT_LOG=1)")
    if not status.get("AE_OTLP_ENDPOINT", {}).get("active"):
        warnings.append("OTLP 分布式追踪未启用 (export AE_OTLP_ENDPOINT=http://localhost:4317)")
    return warnings


def _count_requirements(project_root: Path | None = None) -> int | None:
    """Count completed requirements in the metrics directory.

    Returns the number of requirement subdirectories in
    ``<project_root>/.ae-state/metrics/requirements/``.
    Returns None if the metrics directory does not exist.
    """
    from pathlib import Path as _Path
    try:
        root = project_root or _Path.cwd()
        reqs_dir = root / ".ae-state" / "metrics" / "requirements"
        if not reqs_dir.is_dir():
            return None
        return sum(
            1 for p in reqs_dir.iterdir()
            if p.is_dir() and (p / "summary.json").exists()
        )
    except (OSError, PermissionError):
        return None


def feature_status_for_action(environ: dict | None = None) -> dict[str, bool]:
    """Return a compact {key: active} dict for action JSON ``feature_status`` (T114 5.4).

    DS-14 (T163, 2026-07-23): 仅输出已激活项 (active=True)，减少 action JSON 体积。
    全量 feature flag 状态用 ``ae doctor`` 查看。
    """
    status = get_feature_status(environ)
    return {key: s["active"] for key, s in status.items() if s["active"]}


def _is_active(key: str, env: dict | Mapping[str, str], default: bool = False) -> bool:
    """Determine if a feature flag is active from the environment.

    Phase 44: 默认值从 FeatureFlag.default_value 读取（不再硬编码）。
    """
    val = env.get(key, "").strip()
    if not val:
        return default
    if key in _ENDPOINT_STYLE_FLAGS:
        return True  # any non-empty value activates
    if key == "AE_PII_ENABLED":
        return val != "0"
    return val == "1" or val.lower() == "true"
