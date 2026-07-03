#!/bin/bash
# uninstall.sh — 移除 auto-engineering 用户级安装
# 清理: Plugin 目录, 全局 ae, installed_plugins.json 条目

set -e

PLUGIN_DIR="$HOME/.claude/plugins/auto-engineering"

echo "=== Auto-Engineering v5.0 卸载 ==="
echo ""

# 1. 移除 plugin 条目
if [[ -f "$HOME/.claude/plugins/installed_plugins.json" ]]; then
    echo "[1/3] 从 installed_plugins.json 移除条目..."
    python3 - <<PYEOF
import json
from pathlib import Path
path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
data = json.loads(path.read_text())
data["plugins"].pop("auto-engineering@local", None)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print("  ✓ auto-engineering@local 移除")
PYEOF
else
    echo "[1/3] installed_plugins.json 不存在, 跳过"
fi

# 2. 卸载全局 ae
echo ""
echo "[2/3] uv tool uninstall auto-engineering..."
uv tool uninstall auto-engineering 2>&1 | head -1 || echo "  (ae 不在 uv tool 中, 跳过)"

# 3. 删 Plugin 目录
echo ""
echo "[3/3] 删除 $PLUGIN_DIR"
rm -rf "$PLUGIN_DIR"
echo "  ✓ 完成"

echo ""
echo "卸载完成. 重启 Claude Code 即可生效."
