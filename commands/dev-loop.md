---
name: dev-loop
description: Auto-Engineering dev-loop — v5.6 Tick-Based Discrete Invocation (architect → developer → critic → 5-layer verification), Python-controlled, Agent-executed
---

# /ae:dev-loop — v5.6 Tick-Based Discrete Invocation

Requirement-to-PR development loop. The **Python engine is a deterministic controller**
that never calls an LLM; the **Agent (you) is the LLM executor**. You drive the loop by
repeatedly calling `ae dev-loop --tick`, reading the returned `action` JSON, doing that
role's work, writing a result file, and ticking again — until `action == "done"`.

> Authority: BEACON 决策 #39 (Tick protocol, ✅) + #40/#41 (5-layer verification) +
> #46 (Internalization Constraint — no external agent spawns) + `design/v5.6-Design-Loop.md`
> §A.1 / §B13 / §C.3 (file-bridge) / §C.5 (tick).

## Core model (§A.1)

- **Each `ae dev-loop --tick` is a separate OS process.** It restores state from SQLite
  (`.ae-state/checkpoints.db`), advances exactly one tick, prints the next `action` JSON to
  **stdout**, and exits. Progress/logs go to **stderr**.
- **Python owns all control flow deterministically**: StageRouter (T1–T22), 5 Guardrails,
  7+1 Gates, ConvergenceJudge, BatchState cursor, Checkpoint. It computes *what to do next*.
- **You own all reasoning**: for each `action`, you act as the named role, produce the
  `expected_format` JSON, and write it to a result file. You never decide routing.

## Iron Law (Python is the gatekeeper)

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `ae dev-loop --tick` VALIDATION.
You may NOT edit code before Python outputs {"action":"developer"}.
You may NOT declare done before Python outputs {"action":"done"}.
Violating the letter of this rule is violating the spirit of this rule.
<!-- FRAGMENT:iron_law_gatekeeper END -->

## Usage

```
/ae:dev-loop "Implement OAuth2 login flow"
/ae:dev-loop "Implement payment module" --design-doc design/payment-spec.md
/ae:dev-loop --resume <checkpoint_id>
```

## CLI contract (§B13)

| Command | Behavior | Output | Exit |
|---------|----------|--------|:---:|
| `ae dev-loop --init "req" [--design-doc <path>]` | Initialize loop | first action JSON (stdout) | 0/1 |
| `ae dev-loop --tick --result <file>` | Process one tick | next action JSON (stdout) | 0/1 |
| `ae dev-loop --status` | Query current tick state | state summary JSON | 0 |
| `ae dev-loop --resume <id>` | Restore from checkpoint | action JSON | 0/1 |

`--design-doc` enables **Pre-flight Gap Analysis** (Phase 0). Without it, the loop starts in
fuzzy-requirement mode (architect infers the plan).

## The driving loop (your algorithm)

```
1. action = run: ae dev-loop --init "<requirement>" [--design-doc <path>]
2. while action.action != "done":
     if action.action == "error":
         report action.error_code + message to the user; STOP (do not silently downgrade)
     result = <do the work for action.action>          # see Action reference
     write result JSON to a temp file; result["stage"] MUST equal action.stage
     action = run: ae dev-loop --tick --result <temp file>
3. On "done": report action.verdict + verdict_reason. If GOAL_ACHIEVED/QUALITY → create PR.
```

Print progress before each tick: `[Tick N | stage <action.stage>] …`.

## Action reference

Each tick returns one `action`. Perform it, then write a result whose `stage` matches, with
the fields listed in the action's `expected_format`.

| `action` | Role (you act as) | What you do | Result you write |
|----------|-------------------|-------------|------------------|
| `gap_scan` | Gap scanner | Grade fuzzy design sections (architectural/component/module) | `{gaps, scanned_sections, has_blocking}` |
| `gap_review` | Facilitator | Per gap, `AskUserQuestion`: Fill / Research / Defer / Defer+Research. Blocking architectural gaps may NOT be deferred | `{decisions}` |
| `research` | Researcher | Tiered lookup (Tier0 CLAUDE.md refs → Tier1 ref code → Tier2 docs → Tier3 web). Ref-code uses 3-step method, **no bulk/parallel scans** (96GB incident) | `{findings, sources, source_tier, confidence, recommended_design}` |
| `architect` | Architect | Produce plan + task DAG. Each batch ≤5 files, tasks independently testable, deps form a DAG | `{plan, batch_plan, file_list, contracts}` |
| `developer` | Developer | For each task in the batch: **TDD Red→Green→Refactor** + one atomic commit per task | `{stage, files_changed, test_results, commit_hash}` |
| `critic` | Critic | **Diff-level** review only (not requirement acceptance). Verdict APPROVE/MAJOR + findings | `{stage, verdict, findings, critic_feedback}` |
| `component_verifier` | Component verifier (Haiku-tier) | Map component design spec → code; mark IMPLEMENTED/MISSING/DIVERGED | `{stage, coverage_map, missing_count, diverged_count}` |
| `plate_deep_audit` | Plate auditor (Sonnet-tier) | Cross-component contract + quality audit for the plate | `{stage, findings, p0_count, p1_count, p2_count, cross_component_issues, total_audited_files}` |
| `system_verifier` | System verifier (Haiku-tier) | Full design→code coverage map (exit gate, once) | `{stage, full_coverage_map, total_design_items, covered_count, missing_count, diverged_count}` |
| `system_deep_audit` | System auditor (Sonnet-tier) | Full 6-dimension code-quality audit (exit gate, once) | `{stage, findings, p0_count, p1_count, p2_count, total_audited_files, design_docs_stale, design_doc_suggestions}` |
| `done` | — | Loop terminated | (nothing — report to user) |
| `error` | — | Engine-side error (parse/validation/stage mismatch) | (nothing — report `error_code`) |

Verification depth auto-scales by design layer (#41): single component (LEAF) runs 5 layers,
single plate (PLATE) 6, multi-plate (FULL) all 7. Python picks the path; you just execute the
action you're handed.

## Roles are internal — no external agent spawns (#46 B14)

This loop has **zero runtime external dependencies**. Do **not**:

- ❌ spawn `subagent_type="Plan"` for architect — you act as architect directly, using the
  project's architect prompt (surfaced in the action `context` / `expected_format`).
- ❌ spawn `subagent_type="code-reviewer"` for critic — you act as critic directly.
- ❌ call `/code-review --fix --auto` or `gsd-code-fixer` — code review is covered by the
  built-in `critic` + 4 verification layers.
- ❌ call any `gsd-*` agent or MCP tool as part of the loop.

The severity/verdict rubric (P0 blocking / P1 important / P2 suggestion; APPROVE = 0 P0 + ≤2 P1;
MAJOR = ≥1 P0 or ≥3 P1) is enforced by Python via the result you submit — supply honest findings.

## Convergence & done verdicts

Python decides termination and emits `{"action":"done", "verdict":…, "verdict_reason":…}`:

| verdict | Meaning |
|---------|---------|
| `GOAL_ACHIEVED` | APPROVE + all gates pass + verification layers clean → create PR |
| `QUALITY` | Quality bar met at round limit |
| `STAGNANT` | No progress across rounds → report to user |
| `HARD_LIMIT` | `max_rounds` reached → report to user |
| `REFINE_LIMIT` | plan-refine loop cap (per-source ≤2 / global ≤4) hit → report to user |

## On `done` → PR (human gate, outside the loop)

When verdict is `GOAL_ACHIEVED`/`QUALITY`, push and open a PR for human review (the only human
gate; it lives outside the loop per #45). Use `gh` (or the PRBackend abstraction). Include
requirement, rounds, gate summary, and a reviewer checklist.

## Failure transparency (do not silently downgrade)

- If the CLI exits non-zero or a Bash block fails → **read the error and report it to the user**.
  Do not skip the step or fall back to hand-coding without telling them.
- If `action == "error"` → surface `error_code` + `message`; stop after 2 consecutive
  unrecoverable errors and ask the user to check installation (`ae doctor`).
- The user has the right to know whether the loop is really running — never fake a `done`.

<!-- FRAGMENT:red_flags START -->
## Red Flags — STOP，不要继续，向用户报告

- 我正准备在 Python 输出 {"action":"developer"} 前编辑代码
- 我正准备在 Python 输出 {"action":"done"} 前宣布完成
- Bash 块失败了，我正准备静默切换到手工模式继续
- Agent tool spawn 失败了，我正准备自己手工模拟这个 stage
- 我正准备跳过 --tick 自己推进到下一个 stage
- critic 返回 MAJOR，我正准备忽略 findings 直接进收敛

以上任何一条都意味着：停止。向用户报告失败原因 + 状态 + 选项。禁止静默降级。
<!-- FRAGMENT:red_flags END -->

## References

- `design/v5.6-Design-Loop.md` — §A.1 (process model) / §B13 (CLI) / §C.3 (file-bridge) / §C.5 (tick) / §B2,B4,B6 (verification layers)
- `design/BEACON.md` — 决策 #39/#40/#41/#46
- `docs/EARS-v5.0.md` — acceptance criteria (15 AC + 5 IL-AC)
