#!/bin/sh
# Claude PostToolUse：自动固化 Agent 原生返回到当前 Action 的 native_result_path。

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
RUNTIME_ROOT=$("$PLUGIN_DIR/scripts/ae-run" --print-runtime-root 2>/dev/null) || RUNTIME_ROOT=
if [ -z "$RUNTIME_ROOT" ]; then
    printf '%s\n' '{"systemMessage":"Auto-Engineering Hook 运行环境不可用，未固化原生证据"}'
    exit 0
fi
RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"
if [ -x "$RUNTIME_PYTHON" ]; then
    exec "$RUNTIME_PYTHON" -m auto_engineering.host.claude_hooks
fi
exec "$PLUGIN_DIR/scripts/ae-run" --run-module auto_engineering.host.claude_hooks
