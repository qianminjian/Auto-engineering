#!/bin/bash
# stop.sh — Auto-Engineering session-stop checkpoint save (v5.0 §PE.3)
# Triggered: Stop hook (user interrupt or completion)
# Behavior: if latest checkpoint is "running", mark as "interrupted"

set -u

# Skip if ae CLI not available
[[ ! -x "ae" ]] && exit 0

# Check for checkpoints.db
DB_PATH="${AE_DB_PATH:-.ae-state/checkpoints.db}"
[[ ! -f "$DB_PATH" ]] && exit 0

# Query latest checkpoint status
LATEST_STATUS=$(sqlite3 "$DB_PATH" "SELECT status FROM checkpoints ORDER BY id DESC LIMIT 1;" 2>/dev/null || echo "")

if [[ "$LATEST_STATUS" == "running" ]]; then
  # Mark as interrupted
  sqlite3 "$DB_PATH" "UPDATE checkpoints SET status='interrupted', interrupted_at=CURRENT_TIMESTAMP WHERE status='running';" 2>/dev/null || true
  echo '{"decision":"allow","info":"marked running checkpoint as interrupted"}'
else
  echo '{"decision":"allow"}'
fi
exit 0
