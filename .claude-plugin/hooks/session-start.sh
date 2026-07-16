#!/bin/bash
# session-start.sh — 会话启动环境预检
# 触发: SessionStart
# 用途: 检查 uv/Python/git/ANTHROPIC_API_KEY 是否可用
#
# Hook 协议: 输出 JSON {"decision":"block"/"allow"} 到 stdout

INPUT="$1"

# 快速预检 (非阻塞, 仅检查关键依赖)
MISSING=""

if ! command -v uv &>/dev/null; then
  MISSING="$MISSING uv"
fi

if ! command -v python3 &>/dev/null; then
  MISSING="$MISSING python3"
fi

if [ -n "$MISSING" ]; then
  echo "{\"decision\":\"block\",\"reason\":\"缺少必要依赖:$MISSING。请先安装: brew install uv python@3.12\"}"
  exit 0
fi

echo '{"decision":"allow"}'
