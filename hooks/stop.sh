#!/bin/sh
# Claude Code Stop Hook：只执行 Host Runtime 租约门禁，不直接修改 Core 状态。

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
RUNTIME_ROOT=$("$PLUGIN_DIR/scripts/ae-run" --print-runtime-root 2>/dev/null) || RUNTIME_ROOT=
if [ -z "$RUNTIME_ROOT" ]; then
    printf '%s\n' '{"decision":"block","reason_code":"AE_PROJECT_RUNTIME_UNAVAILABLE","systemMessage":"Auto-Engineering 项目运行时路径不可用，已阻止不安全停止"}'
    exit 0
fi
RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"

if [ -x "$RUNTIME_PYTHON" ]; then
    PYTHONDONTWRITEBYTECODE=1
    export PYTHONDONTWRITEBYTECODE
    exec "$RUNTIME_PYTHON" -m auto_engineering.host.claude_hooks
fi

if command -v uv >/dev/null 2>&1; then
    exec "$PLUGIN_DIR/scripts/ae-run" --run-module auto_engineering.host.claude_hooks
fi

printf '%s\n' \
    '{"decision":"block","reason_code":"AE_HOST_RUNTIME_UNAVAILABLE","systemMessage":"Auto-Engineering Hook 运行环境不可用，已阻止不安全停止"}'
exit 0
