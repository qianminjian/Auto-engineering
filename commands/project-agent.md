---
name: project-agent
description: Invoke a single Auto-Engineering agent role
---

# /ae:project-agent — Invoke Single Agent

## Description

Invoke a specific agent role (architect, developer, critic) without the full loop. Useful for one-off tasks like "design the API for X" or "review this PR".

## Usage

```
/ae:project-agent <role> <task> [--context PATH]
```

## Arguments

| Name | Required | Description |
|------|----------|-------------|
| `role` | Yes | One of: `architect`, `developer`, `critic` |
| `task` | Yes | Task description for the agent |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--context PATH` | None | File or directory to provide as context |
| `--model MODEL` | sonnet | Override model (haiku/sonnet/opus) |

## Execution

```bash
ROLE="$1"
TASK="$2"
shift 2

CONTEXT=""
MODEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context)
      CONTEXT="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$ROLE" ]] || [[ -z "$TASK" ]]; then
  echo '{"error":"role and task required"}'
  exit 2
fi

case "$ROLE" in
  architect|developer|critic) ;;
  *)
    echo '{"error":"role must be architect|developer|critic"}'
    exit 2
    ;;
esac

CMD="ae agent $ROLE --task \"$TASK\""
if [[ -n "$CONTEXT" ]]; then
  CMD="$CMD --context \"$CONTEXT\""
fi
if [[ -n "$MODEL" ]]; then
  CMD="$CMD --model \"$MODEL\""
fi
eval "$CMD"
```

## Output

Single agent response (role-dependent):

```json
{"role":"architect","plan":[{"id":"T1","description":"..."}]}
```

or

```json
{"role":"critic","verdict":"approve","gates_passed":5,"gates_failed":0}
```

## Examples

```
/ae:project-agent architect "design REST API for user management"
/ae:project-agent developer "implement retry logic" --context auto_engineering/api/client.py
/ae:project-agent critic "review the auth refactor PR"
```
