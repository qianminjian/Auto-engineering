#!/bin/sh
# Codex lifecycle hook dispatcher: stdin JSON → HostEvent normalization.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
RUNTIME_ROOT=$("$PLUGIN_DIR/scripts/ae-run" --print-runtime-root 2>/dev/null) || RUNTIME_ROOT=
if [ -z "$RUNTIME_ROOT" ]; then
    printf '%s\n' '{"systemMessage":"Auto-Engineering 项目运行时路径不可用，已安全跳过"}'
    exit 0
fi
RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"

if [ -x "$RUNTIME_PYTHON" ]; then
    exec "$RUNTIME_PYTHON" -m auto_engineering.host.codex_hooks
fi

if command -v uv >/dev/null 2>&1; then
    exec "$PLUGIN_DIR/scripts/ae-run" --run-module auto_engineering.host.codex_hooks
fi

printf '%s\n' \
    '{"systemMessage":"Auto-Engineering Hook 运行环境不可用，已安全跳过"}'
exit 0
