#!/bin/sh
# Codex lifecycle hook dispatcher: stdin JSON → HostEvent normalization.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
RUNTIME_PYTHON="$PLUGIN_DIR/.ae-runtime/bin/python"

if [ -x "$RUNTIME_PYTHON" ]; then
    exec "$RUNTIME_PYTHON" -m auto_engineering.host.codex_hooks
fi

if command -v uv >/dev/null 2>&1; then
    UV_PROJECT_ENVIRONMENT="$PLUGIN_DIR/.ae-runtime" \
        exec uv run --frozen --project "$PLUGIN_DIR" python -m auto_engineering.host.codex_hooks
fi

printf '%s\n' \
    '{"systemMessage":"Auto-Engineering Hook 运行环境不可用，已安全跳过"}'
exit 0
