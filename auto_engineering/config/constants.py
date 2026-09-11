"""Shared configuration constants.

P2-9: Extracted from action_builder.py and tick_orchestrator.py to eliminate
duplication and provide a single source of truth.

P0-4 (2026-07-21 audit): STAGE_TO_ROLE 原在 standalone_driver.py（已于 Phase 40 删除），
移出以消除反向依赖（tick_orchestrator → standalone_driver）。
"""

from __future__ import annotations

# ── V7-2: STAGE_TO_ROLE mapping ──
# 10 个 stage → role (gap_review → None 表示无 LLM role, headless auto-Defer)
# SSOT — tick_orchestrator imports from here (standalone_driver deleted Phase 40)

STAGE_TO_ROLE: dict[str, str | None] = {
    "gap_scan": "gap_scan",
    "gap_review": None,
    "research": "research",
    "architect": "architect",
    "developer": "developer",
    "critic": "critic",
    "component_verifier": "component_verifier",
    "plate_deep_audit": "plate_deep_audit",
    "system_verifier": "system_verifier",
    "system_deep_audit": "system_deep_audit",
}

# ── Deep Audit thresholds ──

DEFAULT_P1_THRESHOLD = 6  # P1 count threshold for deep audit pass/fail decisions. Clamped to [2, 8].

# Setup 失败是可修复的宿主环境问题，但不能让宿主无限重建项目或消耗 token。
# 达到阈值后 Core 进入 WAIT_RESOURCE；项目修复并通过验证后由 Core 清零。
PROJECT_SETUP_MAX_FAILURE_STREAK = 3
# 一个 Setup Action 允许一次就地修复重试；之后必须把失败交回 Core。
PROJECT_SETUP_MAX_IN_ACTION_RETRIES = 1
PROJECT_SETUP_FAILURE_SUMMARY_MAX_LENGTH = 512
PROJECT_SETUP_FAILURE_CODES = frozenset({
    "PROJECT_SETUP_COMMAND_FAILED",
    "PROJECT_SETUP_BUILD_FAILED",
    "PROJECT_SETUP_GATE_FAILED",
    "PROJECT_SETUP_SCOPE_VIOLATION",
    "PROJECT_SETUP_TOOLCHAIN_FAILED",
    "PROJECT_SETUP_UNKNOWN_FAILURE",
})

# ── Subagent spawn requirements per stage (T108a) ──
# Single source of truth — previously duplicated between action_builder.py and
# tick_orchestrator.py with diverging system_deep_audit count (3 vs 5).

# T136a: 不传宿主专属的 Agent 类型参数，由平台自行选择执行器，
# 消除对特定 agent 类型工具的依赖。
# model 不指定 — 不同 Agent 平台模型名不同，由平台自行选择.
_SPAWN_CONFIG: dict[str, dict] = {
    # DS-15: instruction moved to _SPAWN_INSTRUCTION template in action_builder.py.
    # effort maps to Claude Code Agent tool effort parameter:
    #   xhigh — deep reasoning (architect, system-level auditors)
    #   high  — thorough review (critic, plate auditors)
    #   low   — mechanical verification (verifiers)
    "architect":          {"count": 1, "parallel": False, "effort": "xhigh"},
    "developer":          {"count": 1, "parallel": False, "effort": "high"},
    "critic":             {"count": 1, "parallel": False, "effort": "high"},
    "component_verifier": {"count": 1, "parallel": False, "effort": "high"},
    "plate_deep_audit":   {"count": 3, "parallel": True,  "effort": "xhigh"},
    "system_verifier":    {"count": 1, "parallel": False, "effort": "xhigh"},
    "system_deep_audit":  {"count": 5, "parallel": True,  "effort": "xhigh"},
}
