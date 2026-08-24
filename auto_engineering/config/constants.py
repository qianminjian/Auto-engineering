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

# ── Subagent spawn requirements per stage (T108a) ──
# Single source of truth — previously duplicated between action_builder.py and
# tick_orchestrator.py with diverging system_deep_audit count (3 vs 5).

# T136a: subagent_type removed — Agent Tool 不传该参数即用平台默认 agent,
# 消除 code-reviewer 等特定 agent 类型工具不兼容的依赖.
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
