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

_SPAWN_CONFIG: dict[str, dict] = {
    "architect": {
        "subagent_type": "Plan",
        "count": 1,
        "parallel": False,
        "model": "Sonnet",
        "instruction": (
            "Spawn a Plan agent with the action's context (requirement + design_doc) "
            "and expected_format. It MUST produce structured batch_plan JSON — not "
            "just bullet points. Each batch ≤5 files, tasks independently testable."
        ),
    },
    "critic": {
        "subagent_type": "code-reviewer",
        "count": 1,
        "parallel": False,
        "model": "Sonnet",
        "instruction": (
            "Spawn a code-reviewer agent. Feed it files_changed + test_results + "
            "gate_results from the action's context. It MUST produce structured "
            "findings (file:line + severity + issue + suggested_fix) and verdict "
            "(APPROVE if 0 P0 + ≤2 P1, otherwise MAJOR)."
        ),
    },
    "component_verifier": {
        "subagent_type": "general-purpose",
        "count": 1,
        "parallel": False,
        "model": "Haiku",
        "instruction": (
            "Spawn a general-purpose agent (Haiku model). Feed it the component "
            "design spec + implementation files from the action's context. Map "
            "each design item to IMPLEMENTED/MISSING/DIVERGED with file+line evidence."
        ),
    },
    "plate_deep_audit": {
        "subagent_type": "code-reviewer",
        "count": 3,
        "parallel": True,
        "model": "Sonnet",
        "instruction": (
            "SPAWN 3 CODE-REVIEWER SUBAGENTS IN PARALLEL. Each audits different "
            "dimensions of the plate's codebase (cross-component contracts, code "
            "quality, design compliance). Merge all findings and recount p0/p1/p2 "
            "counts. The expected_format requires findings array, p0/p1/p2 counts, "
            "cross_component_issues, and total_audited_files."
        ),
    },
    "system_verifier": {
        "subagent_type": "general-purpose",
        "count": 1,
        "parallel": False,
        "model": "Haiku",
        "instruction": (
            "Spawn a general-purpose agent (Haiku model). Feed it the full design "
            "doc + implementation. Map each design item to IMPLEMENTED/MISSING/DIVERGED "
            "with file+line evidence."
        ),
    },
    "system_deep_audit": {
        "subagent_type": "code-reviewer",
        "count": 5,
        "parallel": True,
        "model": "Sonnet",
        "instruction": (
            "SPAWN 5 CODE-REVIEWER AGENTS IN PARALLEL. Each audits a different "
            "dimension: architecture, code quality, engineering, team-collab, "
            "dead-code/logic-virtualization. Merge all findings and recount "
            "p0/p1/p2 counts."
        ),
    },
}
