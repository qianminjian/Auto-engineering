---
name: checkpoint
description: Manage Auto-Engineering checkpoints (list/show/resume/delete)
---

# /ae:checkpoint — Manage Checkpoints

## Description

Inspect and manage v2 SQLite checkpoints. Supports listing, showing details, resuming from a specific checkpoint, and deleting old checkpoints.

## Usage

```
/ae:checkpoint <action> [args]
```

## Arguments

| Name | Required | Description |
|------|----------|-------------|
| `action` | Yes | One of: `list`, `show`, `resume`, `delete` |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--round N` | None | Filter list by round number |
| `--id ID` | Action-dependent | Checkpoint ID (required for show/resume/delete) |

## Execution

```bash
ACTION="$1"
shift

ID=""
ROUND=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --id)
      ID="$2"
      shift 2
      ;;
    --round)
      ROUND="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

case "$ACTION" in
  list)
    if [[ -n "$ROUND" ]]; then
      .venv/bin/ae checkpoint v2 list --round "$ROUND"
    else
      .venv/bin/ae checkpoint v2 list
    fi
    ;;
  show)
    [[ -z "$ID" ]] && { echo '{"error":"--id required"}'; exit 2; }
    .venv/bin/ae checkpoint v2 show "$ID"
    ;;
  resume)
    [[ -z "$ID" ]] && { echo '{"error":"--id required"}'; exit 2; }
    .venv/bin/ae checkpoint v2 resume "$ID"
    ;;
  delete)
    [[ -z "$ID" ]] && { echo '{"error":"--id required"}'; exit 2; }
    .venv/bin/ae checkpoint v2 delete "$ID"
    ;;
  *)
    echo '{"error":"action must be list|show|resume|delete"}'
    exit 2
    ;;
esac
```

## Output

For `list`:

```
ckpt-001  round=1  stage=architect  status=completed  2026-07-01T10:00:00Z
ckpt-002  round=2  stage=developer  status=interrupted  2026-07-01T10:05:00Z
```

For `show`:

```json
{"id":"ckpt-001","round":1,"stage":"architect","state":{...},"commits":["abc123"]}
```

## Examples

```
/ae:checkpoint list
/ae:checkpoint list --round 3
/ae:checkpoint show --id ckpt-001
/ae:checkpoint resume --id ckpt-002
/ae:checkpoint delete --id ckpt-001
```
