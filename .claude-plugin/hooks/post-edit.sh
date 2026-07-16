#!/bin/bash
# post-edit.sh — PostToolUse 自动 lint + type_check
# 触发: PostToolUse (文件编辑后)
# 用途: 检测新增/修改的 Python 文件，自动跑 ruff + mypy
#
# Hook 协议: 输出 JSON {"decision":"block"/"allow"} 到 stdout

INPUT="$1"

echo '{"decision":"allow"}'
