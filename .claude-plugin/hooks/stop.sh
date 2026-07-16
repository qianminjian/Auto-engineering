#!/bin/bash
# stop.sh — 会话结束时 checkpoint 状态检查
# 触发: Stop
# 用途: 检查 checkpoint 状态；若 running → 标记为 interrupted
#
# Hook 协议: 输出 JSON {"decision":"block"/"allow"} 到 stdout

INPUT="$1"

# 检查是否有活跃的 tick loop
if [ -f ".ae-state/checkpoints.db" ]; then
  STATUS=$(uv run ae dev-loop --status --format json 2>/dev/null || echo '{"current_stage":""}')
  CURRENT_STAGE=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('current_stage',''))" 2>/dev/null || echo "")
  if [ -n "$CURRENT_STAGE" ] && [ "$CURRENT_STAGE" != "done" ]; then
    echo "{\"decision\":\"allow\",\"reason\":\"活跃 loop 仍在进行中 (stage=$CURRENT_STAGE)\"}"
    exit 0
  fi
fi

echo '{"decision":"allow"}'
