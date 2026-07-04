---
name: dev-loop
description: Run the Auto-Engineering multi-agent dev-loop on a requirement
---

# /ae:dev-loop — v5.1 Multi-Agent Development Loop

Three-stage workflow enforced by Python orchestrator:
Architect (JSONL) -> Developer (agent TDD) -> Critic (JSONL)

## Usage

```
/ae:dev-loop "Implement OAuth2 login flow"
/ae:dev-loop "Refactor auth module" --max-rounds 10
/ae:dev-loop --resume
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `requirement` | Yes | Requirement description (quoted string) |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-rounds N` | 3 | Max loop rounds |
| `--resume` | false | Resume from checkpoint |

## Execution

```bash
AE_JSONL_MODE=1 ae dev-loop "$ARGUMENTS"
```

The Python orchestrator enforces: 5 Guardrails, 7 Gates, StageRouter T1-T6,
ConvergenceJudge 4-level, Self-Refine 3-round limit, SQLite checkpoint.

## References

- design/v5.0-Design-Loop.md — complete design spec
- design/BEACON.md — architecture decisions
- docs/EARS-v5.0.md — acceptance criteria (15 AC + 5 IL-AC)
