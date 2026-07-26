#!/bin/bash
# post-edit.sh — Auto-Engineering post-edit notification
# Triggered: PostToolUse hook (after Edit/Write)
# Gate 由 dev-loop Tick 内部执行；独立 gate-check CLI 已在 Phase 40 删除。

set -u

echo '{"decision":"allow"}'
exit 0
