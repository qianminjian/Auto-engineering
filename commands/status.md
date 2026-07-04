---
name: status
description: Show current Auto-Engineering loop state and progress
---

# /ae:status — Show Loop State

## Description

Display the current state of the Auto-Engineering loop: current stage, round number, last checkpoint, gate status, and any blocking issues.

## Usage

```
/ae:status [--json] [--verbose]
```

## Arguments

None.

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | False | Output machine-readable JSON only |
| `--verbose` | False | Include full state dump (all 17 LoopState fields) |

## Execution

```bash
CMD="ae status"
if [[ "$1" == "--json" ]]; then
  CMD="$CMD --json"
fi
if [[ "$1" == "--verbose" ]]; then
  CMD="$CMD --verbose"
fi
eval "$CMD"
```

## Output

Human-readable format:

```
Stage: developer (round 3/50)
Last gate: lint PASS
Last checkpoint: ckpt-003 (running)
Blocked: no
```

Or with `--json`:

```json
{"stage":"developer","round":3,"max_rounds":50,"last_gate":"lint","gate_status":"pass","checkpoint_id":"ckpt-003","checkpoint_status":"running","blocked":false}
```

## Examples

```
/ae:status
/ae:status --json
/ae:status --verbose
```
