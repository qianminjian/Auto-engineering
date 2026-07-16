#!/bin/bash
# pre-tool.sh — PreToolUse sandbox 审计
# 触发: PreToolUse
# 用途: 拦截危险 Bash 命令和文件系统逃逸
#
# Hook 协议: 输出 JSON {"decision":"block"/"allow"} 到 stdout

INPUT="$1"

# 危险命令模式
DANGER_PATTERNS=(
  "rm -rf /"
  "mkfs"
  "dd if="
  "shutdown"
  "> /dev/sda"
  ":(){ :|:& };:"
)

for pattern in "${DANGER_PATTERNS[@]}"; do
  if echo "$INPUT" | grep -qF "$pattern"; then
    echo "{\"decision\":\"block\",\"reason\":\"危险命令: $pattern\"}"
    exit 0
  fi
done

echo '{"decision":"allow"}'
