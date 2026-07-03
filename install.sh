#!/bin/bash
# install.sh — auto-engineering 用户级一次性安装
#
# 参考 superpowers 安装模式 (你机器上 ~/.claude/plugins/superpowers):
#   git clone 完整仓库 → ~/.claude/plugins/<name>/
#   Claude Code 通过 .claude-plugin/plugin.json 识别
#
# 推荐方式 (更简单, 不需要这个脚本):
#   git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
#   cd ~/.claude/plugins/auto-engineering && uv tool install --force .
#   # 编辑 ~/.claude/plugins/installed_plugins.json 加 auto-engineering@local 条目
#   # 重启 Claude Code
#
# 用法: bash install.sh

set -e

REPO="https://github.com/qianminjian/Auto-engineering.git"
PLUGIN_DIR="$HOME/.claude/plugins/auto-engineering"

echo "=== Auto-Engineering v5.0 安装 ==="
echo ""

# 1. git clone / pull
if [[ -d "$PLUGIN_DIR/.git" ]]; then
    echo "[1/4] $PLUGIN_DIR 已存在, git pull..."
    cd "$PLUGIN_DIR" && git pull origin main
else
    echo "[1/4] git clone $REPO 到 $PLUGIN_DIR ..."
    git clone "$REPO" "$PLUGIN_DIR"
fi

# 2. uv tool install 全局 (Engine 在 PATH)
echo ""
echo "[2/4] uv tool install --force . (Engine 全局)"
cd "$PLUGIN_DIR" && uv tool install --force .

# 3. 注册 plugin 到 installed_plugins.json (Claude Code 必需)
echo ""
echo "[3/4] 注册 plugin 到 ~/.claude/plugins/installed_plugins.json"
GIT_SHA=$(cd "$PLUGIN_DIR" && git rev-parse HEAD)
python3 - "$PLUGIN_DIR" "$GIT_SHA" << 'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime, timezone

plugin_dir = sys.argv[1]
git_sha = sys.argv[2]
path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
data = json.loads(path.read_text())
data["plugins"].pop("auto-engineering@local", None)

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
new_entry = {
    "scope": "user",
    "installPath": plugin_dir,
    "version": "5.0.0",
    "installedAt": now,
    "lastUpdated": now,
    "gitCommitSha": git_sha,
}

# Insert alphabetically (before any key > "auto-engineering@local")
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
print(f"  ✓ auto-engineering@local ({git_sha[:7]})")
PYEOF

# 4. 验证
echo ""
echo "[4/4] 验证"
which ae && echo "  ✓ 全局 ae: $(which ae)"
test -f "$PLUGIN_DIR/.claude-plugin/plugin.json" && echo "  ✓ plugin.json 存在"
echo ""
echo "=== 安装完成 ==="
echo ""
echo "⚠  **重启 Claude Code** 后所有项目可用 7 个 slash command:"
echo "   /dev-loop /status /checkpoint /project-tdd /project-worktree /project-agent /project-ci"
echo ""
echo "  卸载: bash uninstall.sh"
echo "  升级: cd $PLUGIN_DIR && git pull && bash install.sh"
echo ""
echo "  替代方式 (更简单, 不需要这个脚本):"
echo "    git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering"
echo "    cd ~/.claude/plugins/auto-engineering && uv tool install --force ."
echo "    # 编辑 installed_plugins.json 加 auto-engineering@local 条目"
echo "    # 重启 Claude Code"
echo ""
echo "  Claude Code 内 marketplace 方式:"
echo "    /plugin marketplace add qianminjian/Auto-engineering"
echo "    /plugin install auto-engineering@auto-engineering"
