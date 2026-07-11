---
name: progress
description: Show hierarchical Auto-Engineering progress board (system → plate → component)
---

# /ae:progress — Show Progress Board

## Description

Display the hierarchical progress board for the current Auto-Engineering loop: system → plate → component completion, verifier status, and deep-audit findings. Read from the persisted `progress_tree_json` in the latest checkpoint.

Complements `/ae:status` (machine-view routing state, 7 fields) — `progress` is the **human-view** board (B9 ProgressTree) and never participates in routing.

## Usage

```
/ae:progress [--format text|json] [--plate <name>] [--all]
```

## Arguments

None.

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--format` | `text` | Output format: `text` (tree) or `json` (summary: completion_pct/total_tasks/done_tasks/node_count) |
| `--plate` | (all) | Show only the named plate |
| `--all` | False | Show completed plates too (default collapses 100%+pass plates) |
| `--project-root` | cwd | Project root directory |

## Execution

```bash
CMD="ae progress"
[[ "$*" == *"--format json"* ]] && CMD="$CMD --format json"
for arg in "$@"; do
  case "$arg" in
    --plate=*) CMD="$CMD --plate ${arg#--plate=}" ;;
    --all)     CMD="$CMD --all" ;;
  esac
done
eval "$CMD"
```

## Output

Human-readable format:

```
SYSTEM  62%  (18/29 tasks)
Plate Auth — 100% ✓ (3 components)  [collapsed]
── Plate Payment — 40% ──
  ChargeService  50%  v:pending
  RefundService  30%  v:failed
```

Or with `--format json`:

```json
{
  "completion_pct": 62.0,
  "total_tasks": 29,
  "done_tasks": 18,
  "node_count": 12
}
```

When no checkpoint exists yet (loop not started), prints `暂无进度数据` (text) or a zeroed summary (json), exit 0.

## Examples

```
/ae:progress
/ae:progress --format json
/ae:progress --plate Payment --all
```
