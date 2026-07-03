#!/bin/bash
# install.sh — auto-engineering 用户级一次性安装
#
# 跨系统敏感: 写 ~/.claude/ 和用户 PATH. 不在 Makefile 中 (那是项目级).
# 一次性, 不需要重复. 重复用 update.sh.
#
# 用法:
#   bash install.sh      # 安装
#   bash uninstall.sh    # 卸载
#
# 步骤:
#   1. git clone 到 ~/.claude/plugins/auto-engineering
#   2. uv tool install . 全局 (Engine 在 PATH)
#   3. 注册到 ~/.claude/plugins/installed_plugins.json (Claude Code 发现)
#   4. 重启 Claude Code → /dev-loop 等 7 个 slash command

set -e

REPO="git@github.com:qianminjian/Auto-engineering.git"
PLUGIN_DIR="$HOME/.claude/plugins/auto-engineering"

echo "=== Auto-Engineering v5.0 用户级安装 ==="
echo ""

# 1. git clone / pull
if [[ -d "$PLUGIN_DIR/.git" ]]; then
    echo "[1/3] 已存在, 执行 git pull..."
    cd "$PLUGIN_DIR" && git pull origin main
else
    echo "[1/3] git clone..."
    git clone "$REPO" "$PLUGIN_DIR"
fi

# 2. uv tool install 全局
echo ""
echo "[2/3] uv tool install . (Engine 全局)"
cd "$PLUGIN_DIR" && uv tool install --force .

# 3. 注册 plugin 到 installed_plugins.json
echo ""
echo "[3/3] 注册 plugin 到 ~/.claude/plugins/installed_plugins.json"
GIT_SHA=$(cd "$PLUGIN_DIR" && git rev-parse HEAD)
python3 - <<PYEOF
import json
from pathlib import Path
from datetime import datetime, timezone

path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
data = json.loads(path.read_text())
data["plugins"].pop("auto-engineering@local", None)

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
new_entry = {
    "scope": "user",
    "installPath": "$PLUGIN_DIR",
    "version": "5.0.0",
    "installedAt": now,
    "lastUpdated": now,
    "gitCommitSha": "$GIT_SHA",
}

# Insert alphabetically (before "claude-code-settings" or any key > "auto-engineering@local")
ordered = {}
inserted = False
for key, val in data["plugins"].items():
    if not inserted and key > "auto-engineering@local":
        ordered["auto-engineering@local"] = [new_entry]
        inserted = True
    ordered[key] = val
if not inserted:
    ordered["auto-engineering@local"] = [new_entry]

data["plugins"] = ordered
path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
print(f"  ✓ auto-engineering@local ({'$GIT_SHA'[:7]})")
PYEOF

# 4. 提示
echo ""
echo "=== 安装完成 ==="
echo ""
echo "  全局 ae: $(which ae 2>/dev/null || echo 'NOT IN PATH')"
echo "  Plugin: $PLUGIN_DIR"
echo ""
echo "⚠  **重启 Claude Code** 后所有项目可用 7 个 slash command:"
echo "   /dev-loop /status /checkpoint /project-tdd /project-worktree /project-agent /project-ci"
echo ""
echo "  卸载: bash uninstall.sh"
echo "  升级: bash update.sh"
