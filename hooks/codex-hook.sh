#!/bin/sh
# Codex lifecycle hook dispatcher: stdin JSON → HostEvent normalization.

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
VENV_PYTHON="$PLUGIN_DIR/.venv/bin/python"

if [ -x "$VENV_PYTHON" ]; then
    exec "$VENV_PYTHON" -m auto_engineering.host.codex_hooks
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$PLUGIN_DIR" python -m auto_engineering.host.codex_hooks
fi

printf '%s\n' \
    '{"systemMessage":"Auto-Engineering Hook 运行环境不可用，已安全跳过"}'
exit 0
