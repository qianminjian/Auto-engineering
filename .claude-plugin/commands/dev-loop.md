---
name: dev-loop
description: Run the Auto-Engineering multi-agent dev-loop on a requirement
---

# /ae:dev-loop — Run Auto-Engineering Dev-Loop

## Description

Launch a full v5.0 multi-agent development loop (Architect → Developer → Critic) on a free-text requirement. The loop runs iteratively through Plan → Execute → Gate → Checkpoint until convergence (max 50 rounds) or user interrupt.

## Usage

```
/ae:dev-loop <requirement> [--max-rounds N] [--checkpoint-id ID] [--resume]
```

## Arguments

| Name | Required | Description |
|------|----------|-------------|
| `requirement` | Yes | Free-text requirement description (quoted if contains spaces) |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-rounds N` | 50 | Maximum loop rounds before forced stop |
| `--checkpoint-id ID` | None | Resume from a specific v2 SQLite checkpoint |
| `--resume` | False | Resume from the latest interrupted checkpoint |

## Execution

The command invokes the Engine via Bash and streams structured JSON output to the conversation.

```bash
# Parse args (bash 3 compatible)
REQUIREMENT=""
MAX_ROUNDS=50
CHECKPOINT_ID=""
RESUME=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-rounds)
      MAX_ROUNDS="$2"
      shift 2
      ;;
    --checkpoint-id)
      CHECKPOINT_ID="$2"
      shift 2
      ;;
    --resume)
      RESUME=true
      shift
      ;;
    *)
      REQUIREMENT="$1"
      shift
      ;;
  esac
done

# Validate
if [[ -z "$REQUIREMENT" ]] && [[ "$RESUME" != "true" ]] && [[ -z "$CHECKPOINT_ID" ]]; then
  echo '{"error":"requirement required (or use --resume / --checkpoint-id)"}'
  exit 2
fi

# Build command
CMD=".venv/bin/ae dev-loop"
if [[ -n "$REQUIREMENT" ]]; then
  CMD="$CMD \"$REQUIREMENT\""
fi
CMD="$CMD --max-rounds $MAX_ROUNDS --json"
if [[ -n "$CHECKPOINT_ID" ]]; then
  CMD="$CMD --checkpoint-id $CHECKPOINT_ID"
fi
if [[ "$RESUME" == "true" ]]; then
  CMD="$CMD --resume"
fi

# Execute
eval "$CMD"
```

## Output

Streamed JSON events, one per line:

```jsonl
{"event":"stage","stage":"architect","round":1}
{"event":"plan","tasks":3}
{"event":"execute","task_id":"T1","status":"ok"}
{"event":"gate","gate":"lint","status":"pass"}
{"event":"checkpoint","id":"ckpt-001","status":"running"}
{"event":"round","n":1,"status":"continue"}
```

On convergence:

```json
{"event":"converged","reason":"all_gates_pass","rounds":3}
```

## Examples

```
/ae:dev-loop "Add user login with OAuth2"
/ae:dev-loop "Refactor auth module" --max-rounds 10
/ae:dev-loop --resume
/ae:dev-loop --checkpoint-id ckpt-001
```

## Notes

- Requires `.venv` provisioned (`uv sync` first time)
- Interruptible via Ctrl-C — saves interrupted checkpoint automatically
- Use `ae status` to inspect live loop state
