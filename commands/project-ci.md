---
name: project-ci
description: Run CI pipeline (all gates) on current branch
---

# /ae:project-ci — Run Full CI

## Description

Run the full CI pipeline (all Gate checks) on the current branch without invoking the dev-loop. This is the equivalent of a CI server run.

## Usage

```
/ae:project-ci [--quick] [--fix]
```

## Arguments

None.

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--quick` | False | Run only fast gates (lint + type_check + test) |
| `--fix` | False | Auto-fix what can be auto-fixed (lint via ruff/black) |

## Execution

```bash
QUICK=false
FIX=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      QUICK=true
      shift
      ;;
    --fix)
      FIX=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

CMD="ae gate-check"
if [[ "$QUICK" == "true" ]]; then
  CMD="$CMD --quick"
else
  CMD="$CMD --all"
fi
if [[ "$FIX" == "true" ]]; then
  CMD="$CMD --fix"
fi
eval "$CMD"
```

## Output

Gate results streamed:

```jsonl
{"gate":"lint","status":"pass","duration_ms":1234}
{"gate":"type_check","status":"pass","duration_ms":5678}
{"gate":"test","status":"pass","duration_ms":12000,"passed":150,"failed":0}
{"gate":"coverage","status":"warn","coverage_pct":78.5}
```

Final summary:

```json
{"summary":"3 passed, 1 warn, 0 failed","total_duration_ms":19456}
```

## Examples

```
/ae:project-ci
/ae:project-ci --quick
/ae:project-ci --fix
/ae:project-ci --quick --fix
```
