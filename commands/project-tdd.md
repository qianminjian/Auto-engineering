---
name: project-tdd
description: Run TDD (Red-Green-Refactor) on a specific task
---

# /ae:project-tdd — Run TDD Cycle

## Description

Execute a strict TDD cycle (Red → Green → Refactor) for a specific task. Useful when you want to add a test-driven feature without running the full dev-loop.

## Usage

```
/ae:project-tdd <task-description> [--module PATH]
```

## Arguments

| Name | Required | Description |
|------|----------|-------------|
| `task-description` | Yes | What to implement (e.g., "validate email format") |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--module PATH` | auto-detect | Target module path (e.g., `auto_engineering/validators`) |

## Execution

```bash
TASK="$1"
shift

MODULE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --module)
      MODULE="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$TASK" ]]; then
  echo '{"error":"task description required"}'
  exit 2
fi

CMD="ae agent developer --task \"$TASK\" --tdd"
if [[ -n "$MODULE" ]]; then
  CMD="$CMD --module \"$MODULE\""
fi
eval "$CMD"
```

## Output

Streams TDD progression:

```jsonl
{"step":"red","test":"test_validate_email_format","status":"fail","reason":"function not defined"}
{"step":"green","impl":"added validate_email","tests":"1 passed"}
{"step":"refactor","changes":["extract regex constant"],"tests":"1 passed"}
```

## Examples

```
/ae:project-tdd "validate email format"
/ae:project-tdd "add retry logic to API client" --module auto_engineering/api
```
