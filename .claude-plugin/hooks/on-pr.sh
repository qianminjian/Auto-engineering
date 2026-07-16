#!/bin/bash
# on-pr.sh — PR 创建时收集 Gate 结果
# 触发: PR 创建事件
# 用途: 收集本轮 Gate 结果附加到 PR body
#
# Hook 协议: 输出 JSON {"decision":"block"/"allow"} 到 stdout

INPUT="$1"

echo '{"decision":"allow"}'
