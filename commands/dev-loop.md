---
name: dev-loop
description: Run the Auto-Engineering multi-agent dev-loop on a requirement
---

# /ae:dev-loop — v5.1 Multi-Agent Development Loop

## Agent Tool Mode (2026-07-04)

v5.1 起 `/ae:dev-loop` **直接在 Claude Code agent 内执行**，使用 Agent 工具
(spawn Plan agent + code-reviewer agent) 替代 Python 子进程外部调用。

**为什么不用子进程**：Claude Code agent 的 ANTHROPIC_AUTH_TOKEN 无法传到
子进程，导致 architect/critic LLM 调用永远失败。Agent tool 模式直接复用
agent 的 LLM 连接，用户**零配置**。

## Three-Stage Workflow

### Stage 1: Architect（Plan Agent）

**Spawn**: Plan agent via Agent tool.

**Role**: Analyze the requirement, produce a structured plan.

**Tools** (Read-only): read_file, search_code, list_dir, git_diff

**Output** (MUST be produced, not skipped):

```
{
  "plan": "markdown text describing the implementation strategy",
  "file_list": ["path/to/create_or_modify.py", "..."],
  "batch_plan": [
    {
      "id": "T1",
      "title": "Task short title",
      "description": "What needs to be done",
      "expected_output": "output1.json",
      "file_targets": ["path/to/file1.py"],
      "depends_on": [],
      "estimated_minutes": 20
    }
  ],
  "contracts": {
    "ModuleName": {
      "method": "get_name",
      "path": "path/to/module.py",
      "input": {"param": "type"},
      "output": {"result": "type"},
      "status_codes": [200]
    }
  }
}
```

**Constraints**:

- `batch_plan` entries ≤ 5 files each
- `file_list` = all files to create or modify
- `contracts` only for cross-module interface changes
- temperature 0.3, max_tokens 4096

### Stage 2: Developer（Claude Code Agent）

**Role**: Execute the batch_plan produced by Stage 1.

**Tools** (Full): read_file, write_file, edit_file, search_code, list_dir,
run_bash, git_commit, git_diff, run_tests, git_status

**Process** (TDD Red→Green→Refactor per TaskCreate):

1. **RED** — write failing test first
2. **GREEN** — write minimal implementation
3. **REFACTOR** — clean up, tests stay green

**After ALL TaskCreate in the batch_plan**:

- Run all gates in parallel:
  - `safety`: secret scan (gitleaks or regex)
  - `lint`: lint check (ruff/eslint/etc.)
  - `type_check`: type check (mypy/pyright/tsc)
  - `test`: pytest/vitest with full pass
  - `build`: verify build succeeds (skip if no build step)
- Record: files_changed, commit_hash, test_results
- Git commit after each TaskCreate with descriptive message

### Stage 3: Critic（code-reviewer Agent）

**Spawn**: code-reviewer agent via Agent tool.

**Role**: Review the Stage 2 output objectively (code + tests + diff).

**Tools** (Read-only + verification): read_file, search_code, git_diff, run_tests

**Output** (structured, file:line level):

```
{
  "verdict": "APPROVE" | "MAJOR",
  "findings": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "severity": "P0" | "P1" | "P2",
      "issue": "function lacks null guard",
      "suggested_fix": "+ if x is None: raise ValueError('x cannot be None')"
    }
  ],
  "critic_feedback": "overall assessment text"
}
```

**MAJOR criteria**:
- ≥ 1 P0 finding OR
- ≥ 3 P1 findings

**If MAJOR**: Agent returns to Stage 2 (Developer) to fix all P0 and
P1 findings in the critic_feedback + suggested_fix fields.
**If APPROVE**: Loop converges (exit).

## Convergence While Loop

```python
max_rounds = 3  # Self-Refine 3 rounds optimal (Madaan et al. 2023)
consecutive_majors = 0
round = 0

while round < max_rounds:
    round += 1
    # Stage 1: Architect (Plan agent)
    batch_plan, file_list, contracts = spawn_plan_agent(requirement)

    # Stage 2: Developer (Claude Code agent)
    for task in batch_plan:
        write_failing_test(task.file_targets, task.expected_output)
        implement_minimal(task.file_targets)
        refactor_while_tests_pass(task.file_targets)
        git_commit(task)

    # Gates: parallel execution
    gate_results = asyncio.gather(
        run_safety_gate(),
        run_lint_gate(),
        run_type_check_gate(),
        run_test_gate(),
        run_build_gate(skip_if_no_build_step)
    )

    # Stage 3: Critic (code-reviewer agent)
    verdict, findings, suggested_fix = spawn_code_reviewer_agent(
        files_changed, test_results, gate_results
    )

    if verdict == "APPROVE" and gate_results.all_passed():
        break  # success — loop exited

    if verdict == "MAJOR":
        consecutive_majors += 1
        if consecutive_majors >= 3:
            # HARD_LIMIT: stop, report final state
            break

        # developer fixes findings, continue loop
        fix_critic_findings(findings, suggested_fix)
```

## Quality Gate (CLAUDE.md §4.5, MUST pass before entering Stage 2)

Before starting Stage 2, verify:

1. Design doc / protocol steps align with batch_plan? → MUST check
2. Task list is itemized with acceptance criteria per task? → MUST list
3. Previous stage (architect) outputs are produced? → MUST confirm
4. Authorization status is clear ("auto-execute" ≠ "can skip")? → MUST confirm

## Guardrail System (5 Guardrails, MUST check in each round)

| # | Guardrail | Timing | Stage | Action |
|---|-----------|--------|-------|--------|
| G1 | RequirementValid | pre | architect | requirement non-empty (1-4096 chars) → block if fail |
| G2 | PlanExists | post | architect | plan non-empty + file_list ≥ 1 item → retry ≤ 3 |
| G3 | GitDiffExists | post | developer | git diff has changes → retry ≤ 3 |
| G4 | TestsPass | post | developer | test_results.failed == 0 → retry ≤ 3 |
| G5 | GitClean | post | developer | git status clean → block if fail |

## Gate System (7 Gates, MUST run in parallel in Stage 2)

| # | Gate | Applies to Stages | Check | Timeout |
|---|------|-------------------|-------|---------|
| G0 | safety | all | secret/credential scanning (regex + gitleaks) | 30s |
| G1 | lint | all | run linter (ruff/eslint/etc.) | 120s |
| G2 | type_check | all | run type checker (mypy/pyright/tsc) | 120s |
| G3 | contract | developer + critic | static match architect contracts vs code | 30s |
| G4 | test | developer + critic | run test suite (pytest/vitest) | 180s |
| G5 | coverage | developer | check coverage ≥ baseline (skip if not installed) | skip |
| G6 | build | developer | build verification | 120s |

## Self-Refine Integration (2026-07-04)

At Stage 2 redo (MAJOR feedback), inject into every TaskCreate description:

1. **critic_feedback** — overall assessment from Stage 3
2. **findings** — file:line + severity specific items
3. **suggested_fix** — unified diff patch (directly applicable, "git apply"-ready)
4. **gate_results** — non-LLM signals (lint/test/type_check failures)

Principle: Do NOT rely on LLM self-assessment. Gate results are **real execution
output**, not LLM-generated estimates.

## Usage

```
/ae:dev-loop "Implement OAuth2 login flow"
/ae:dev-loop "Refactor auth module" --max-rounds 10
/ae:dev-loop --resume
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-rounds N` | 3 (Self-Refine optimal) | Max loop rounds |
| `--resume` | false | Resume from interrupted checkpoint |
| `--gates-skip A,B` | "" | comma-separated gate list to skip |

## Prerequisites

- Claude Code agent with full tool access (write_file, git, run_bash, etc.)
- project initialized (`.ae-state/init-manifest.json` from Init Engineering)
- **Zero configuration needed** — agent's ANTHROPIC_AUTH_TOKEN is reused

## Agent Compliance Rules (MUST follow)

**This is NOT a suggestion. The three-stage workflow below is mandatory.**

1. **Prohibition**: The agent MUST NOT silently skip the Architect and Critic stages and
   fall back to manual Read→Write→Edit→Commit coding. If you cannot spawn Plan agent
   or code-reviewer agent, **report the failure to the user immediately** and ask
   whether to proceed in manual mode or abort.

2. **Stage 1 (Architect) is mandatory**: Spawn a Plan agent via Agent tool. If Plan
   agent is unavailable, tell the user: "Plan agent unavailable. /ae:dev-loop requires
   Plan agent for architect stage. Install auto-engineering or proceed manually?"

3. **Stage 3 (Critic) is mandatory**: Spawn a code-reviewer agent via Agent tool.
   If code-reviewer agent is unavailable, tell the user and offer manual review
   alternative.

4. **Transparency**: At the start of each stage, output a progress line:
   `[Stage N/M] Running <stage_name>...`. This lets the user know the agent is
   following the dev-loop workflow, not doing ad-hoc coding.

5. **Failure visibility**: If any Bash block or Agent tool spawn fails, the error
   MUST be shown to the user. The agent MUST NOT silently absorb the failure and
   continue with manual work. The user has the right to know that dev-loop is
   not running as designed.

## References

- design/v5.0-Design-Loop.md — complete 12-stage design spec
- design/BEACON.md — architecture decisions 1-32
- docs/EARS-v5.0.md — acceptance criteria (15 AC + 5 IL-AC)
- _scratch/reports/2026-07-04-dev-loop-execution-analysis.md — production usage analysis