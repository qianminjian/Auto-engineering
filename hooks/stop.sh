#!/bin/sh
# Claude Code Stop Hook：只执行 Host Runtime 租约门禁，不直接修改 Core 状态。

set -u

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd -P)
PLUGIN_DIR=${PLUGIN_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)}
RUNTIME_PYTHON="$PLUGIN_DIR/.ae-runtime/bin/python"

if [ -x "$RUNTIME_PYTHON" ]; then
    PYTHONDONTWRITEBYTECODE=1
    export PYTHONDONTWRITEBYTECODE
    exec "$RUNTIME_PYTHON" -m auto_engineering.host.claude_hooks
fi

if command -v uv >/dev/null 2>&1; then
    UV_PROJECT_ENVIRONMENT="$PLUGIN_DIR/.ae-runtime"
    PYTHONDONTWRITEBYTECODE=1
    export UV_PROJECT_ENVIRONMENT PYTHONDONTWRITEBYTECODE
    exec uv run --frozen --project "$PLUGIN_DIR" python -m auto_engineering.host.claude_hooks
fi

printf '%s\n' \
    '{"decision":"block","reason_code":"AE_HOST_RUNTIME_UNAVAILABLE","systemMessage":"Auto-Engineering Hook 运行环境不可用，已阻止不安全停止"}'
exit 0
