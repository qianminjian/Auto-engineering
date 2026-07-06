---
name: dev-loop
description: Multi-agent dev-loop — Architect (Plan) → Developer (TDD) → Critic (code-reviewer) → Auto-fix → PR
---

# /ae:dev-loop — v5.1 Agent Tool Direct Execution

Five-stage automated development pipeline. The Agent executes all stages directly
(not via `ae dev-loop` subprocess), using real Plan agent and code-reviewer agent.

> **Production path**: Agent Tool `/ae:dev-loop` is the production execution mode
> (BEACON 决策 47). CLI `ae dev-loop` is the **Python Engine debug path** — for
> testing Orchestrator logic locally without spawning Claude Code agents.

## Usage

```
/ae:dev-loop "Implement OAuth2 login flow"
/ae:dev-loop "Refactor auth module" --max-rounds 3
/ae:dev-loop --resume
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-rounds` | 3 | Max Self-Refine rounds (MAJOR → fix → re-review) |
| `--no-deep-review` | false | Skip Stage 4 deep review + auto-fix |
| `--no-pr` | false | Skip Stage 5 PR creation |

---

## Stage 1 — Architect (Plan Agent)

**Objective**: Produce a structured implementation plan.

**Execution**:
Spawn a Plan agent via `Agent` tool with `subagent_type="Plan"`.

```
Agent(
  subagent_type="Plan",
  description="Architect: design implementation plan",
  prompt="
    Analyze the following requirement and produce a structured implementation plan:
    
    REQUIREMENT: {requirement}
    
    Output must be valid JSON with these fields:
    - plan: string — architecture overview and approach
    - file_list: list[string] — files to create/modify (ordered)
    - batch_plan: list[object] — task breakdown. Each task has:
        id, title, description, expected_output, role (always 'developer'),
        target_files (list), depends_on (list, may be empty)
    - contracts: object — cross-module interfaces if any (may be empty)
    
    Constraints:
    - Each batch ≤ 5 files
    - Each task independently testable
    - Dependencies form a DAG (no cycles)
    - Use read_file / search_code / list_dir to understand existing code first
  "
)
```

**Gate check**: Plan agent must output structured JSON with all required fields.
If output is only 2-3 lines of text without JSON structure → **re-spawn Plan agent** (do not proceed).

**Output**: `batch_plan`, `file_list`, `plan`, `contracts`

---

## Stage 2 — Developer (Agent Self, TDD)

**Objective**: Implement each task in `batch_plan` following strict TDD.

**Execution**:
For each task in `batch_plan` (in dependency order, same-level tasks can be parallel):

### TDD Cycle per Task

```
RED:   Write a failing test for the task's expected_output
       → run_tests → confirm FAIL (if it passes, the test is wrong)
GREEN: Write minimal implementation to pass the test
       → run_tests → confirm PASS
       → NO extra features, NO "future-proofing"
REFACTOR: Clean up code while tests stay green
       → run_tests → confirm still PASS
       → git_commit with message: "feat({scope}): {task.title}"
```

### Constraints

- Each commit = one task (atomic)
- Never skip RED phase (no implementing before test exists)
- Never mark tests as skip/xfail to bypass failures
- After ALL tasks complete: run full test suite to verify no regressions

### Gate Check (after all tasks)

Run all gates in parallel:
```
safety → lint → type_check → test → tdd → build
```

Record: `files_changed`, `commit_hash` (of last commit), `test_results`

---

## Stage 3 — Critic (code-reviewer Agent)

**Objective**: Deep code review of developer's output. This is the gate check before proceeding.

**Execution**:
Spawn a code-reviewer agent via `Agent` tool with `subagent_type="code-reviewer"`.

```
Agent(
  subagent_type="code-reviewer",
  description="Critic: review developer output",
  prompt="
    Review the developer's code changes against the original requirement and plan.
    
    CONTEXT:
    - Requirement: {requirement}
    - Plan: {plan_summary}
    - Files changed: {files_changed}
    - Test results: {test_results}
    - Gate results: {gate_results}
    - Commits: {commit_list}
    
    Use read_file to examine the actual code changes.
    Use run_tests to verify tests pass.
    Use git_diff to review the diff.
    
    Output structured findings as JSON:
    {
      \"verdict\": \"APPROVE\" | \"MAJOR\",
      \"findings\": [
        {
          \"file\": \"path/to/file\",
          \"line\": 123,
          \"severity\": \"P0\" | \"P1\" | \"P2\",
          \"dimension\": \"architecture\" | \"code_quality\" | \"engineering\" | \"team_collab\" | \"logic_fidelity\" | \"tdd\",
          \"issue\": \"specific description\",
          \"suggested_fix\": \"concrete fix suggestion\"
        }
      ],
      \"critic_feedback\": \"overall assessment\"
    }
    
    Severity:
    - P0: blocking — logic error, security issue, test failure, unimplemented requirement
    - P1: important — missing error handling, unclear naming, insufficient tests
    - P2: suggestion — style improvement, optional refactor
    
    Verdict:
    - APPROVE: 0 P0 + ≤2 P1
    - MAJOR: ≥1 P0 or ≥3 P1
  "
)
```

**If MAJOR**:
1. Log findings prominently
2. Agent fixes P0 first, then P1 (up to 3 per batch)
3. Each fix: edit → run_tests → git_commit
4. Re-spawn code-reviewer agent to re-review
5. Max 3 Self-Refine rounds (consecutive_majors ≥ 3 → HARD_LIMIT, report to user)

**If APPROVE**: Proceed to Stage 4.

---

## Stage 4 — Deep Review + Auto-fix

**Objective**: Final deep review using the `/code-review` skill, with automatic fix of remaining P1/P2 issues.

**Prerequisite**: Stage 3 returned APPROVE.

**Execution**:
Run the built-in `/code-review` command with `--fix` flag:

```
/code-review --fix --auto
```

This spawns a code-reviewer agent that:
1. Reads all changed source files
2. Produces REVIEW.md with severity-classified findings
3. Auto-fixes P1 and P2 issues (gsd-code-fixer)
4. Commits each fix atomically
5. Re-reviews to confirm fixes (--auto loop, capped at 3 iterations)

**Skip with**: `--no-deep-review` flag.

---

## Stage 5 — PR + Merge

**Objective**: Push changes and create PR for human review.

**Execution**:

```bash
# Push
BRANCH=$(git branch --show-current)
git push -u origin "$BRANCH"

# Create PR
gh pr create \
  --title "{descriptive title from requirement}" \
  --base main \
  --head "$BRANCH" \
  --body "## AI Dev-Loop Summary

**Requirement**: {requirement}
**Rounds**: {rounds}
**Status**: APPROVED by Critic + Deep Review passed

### Gate Results
{gate_results_summary}

### Changes
$(git diff origin/main...HEAD --stat)

### Human Review Checklist
- [ ] Core logic matches the requirement
- [ ] No security issues
- [ ] Test coverage is adequate
- [ ] Architecture is consistent

---
:robot: Auto-Engineering v5.1 | Critic + code-reviewer approved"
```

**Skip with**: `--no-pr` flag.

---

## Convergence Rules

| Condition | Action |
|-----------|--------|
| max_rounds reached | HARD_LIMIT — report to user |
| consecutive_majors ≥ 3 | HARD_LIMIT — report findings, ask user |
| APPROVE + all gates pass + deep review pass | SUCCESS → PR created |

---

## Key Principles

- Stage 1 MUST spawn Plan agent (not just 3 bullet points)
- Stage 3 MUST spawn code-reviewer agent (not just quick glance)
- Each TDD cycle MUST follow RED → GREEN → REFACTOR order
- Gates MUST run in parallel after all tasks complete
- Self-Refine: MAJOR → fix → re-review (not skip)
- Stage 4 is automated, Stage 5 is automated (no user prompts unless HARD_LIMIT)
- Every agent spawn must display progress: `[Stage N/5] Running <stage>...`
- If Plan agent or code-reviewer agent is unavailable, REPORT to user, do not silently downgrade

## References

- CLAUDE.md § /ae:dev-loop Agent Tool 执行模式 — this protocol
- design/discussion/v5.1-code-review-integration-gap.md — architecture analysis
- design/v5.0-Design-Loop.md — complete Loop design
- atdo Step 7.5 Gate Code Review — required code review gate
