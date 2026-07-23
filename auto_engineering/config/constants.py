"""Shared configuration constants.

P2-9: Extracted from action_builder.py and tick_orchestrator.py to eliminate
duplication and provide a single source of truth.

P0-4 (2026-07-21 audit): STAGE_TO_ROLE moved from standalone_driver.py to break
reverse dependency (tick_orchestrator → standalone_driver).
"""

from __future__ import annotations

# ── V7-2: STAGE_TO_ROLE mapping ──
# 10 个 stage → role (gap_review → None 表示无 LLM role, headless auto-Defer)
# SSOT — both tick_orchestrator and standalone_driver import from here.

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
    "architect": {
        "count": 1,
        "parallel": False,
        "instruction": (
            "Spawn an agent with the action's context (requirement + design_doc) "
            "and expected_format. It MUST produce structured batch_plan JSON — not "
            "just bullet points. Each batch ≤5 files, tasks independently testable."
        ),
    },
    "critic": {
        "count": 1,
        "parallel": False,
        "instruction": (
            "Spawn an agent. Feed it files_changed + test_results + "
            "gate_results from the action's context. It MUST produce structured "
            "findings (file:line + severity + issue + suggested_fix) and verdict "
            "(APPROVE if 0 P0 + ≤2 P1, otherwise MAJOR)."
        ),
    },
    "component_verifier": {
        "count": 1,
        "parallel": False,
        "instruction": (
            "Spawn an agent. Feed it the component design spec + "
            "implementation files from the action's context. Map each design item "
            "to IMPLEMENTED/MISSING/DIVERGED with file+line evidence."
        ),
    },
    "plate_deep_audit": {
        "count": 3,
        "parallel": True,
        "instruction": (
            "SPAWN 3 AGENTS IN PARALLEL. Each audits a different "
            "dimension of the plate's codebase (cross-component contracts, dataflow "
            "& error propagation, architecture degradation). Each agent has its own "
            "role_prompt in spawn.agents[]. Merge all findings and recount p0/p1/p2 "
            "counts. The expected_format requires findings array, p0/p1/p2 counts, "
            "cross_component_issues, and total_audited_files."
        ),
    },
    "system_verifier": {
        "count": 1,
        "parallel": False,
        "instruction": (
            "Spawn an agent. Feed it the full design doc + implementation. "
            "Map each design item to IMPLEMENTED/MISSING/DIVERGED with file+line evidence."
        ),
    },
    "system_deep_audit": {
        "count": 5,
        "parallel": True,
        "instruction": (
            "SPAWN 5 AGENTS IN PARALLEL. Each audits a different "
            "dimension: architecture, code quality, engineering, team-collab, "
            "dead-code/logic-virtualization. Each agent has its own "
            "role_prompt in spawn.agents[]. Merge all findings and recount "
            "p0/p1/p2 counts."
        ),
    },
}
