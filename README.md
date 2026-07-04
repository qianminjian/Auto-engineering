# Auto-Engineering v5.0

Claude Code Plugin — Loop Engineering 调度脚手架

团队内部分发 (5-20 用户本地安装) — 不是 SaaS, 不是个人工具.

<<<<<<< HEAD
## 安装 (Claude Code 官方 marketplace 机制, 与 superpowers 等其他 plugin 一致)

### 首次安装

```bash
# 1. git clone 完整仓库
git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/auto-engineering

# 2. 注册为本地 marketplace (Claude Code 官方机制)
claude plugin marketplace add /Users/minjianq/.claude/auto-engineering

# 3. 安装 plugin
claude plugin install auto-engineering@auto-engineering

# 4. 重启 Claude Code → /dev-loop 等 7 个 slash command 可用
```

### 升级

```bash
cd ~/.claude/auto-engineering && git pull
claude plugin marketplace update auto-engineering
claude plugin install auto-engineering@auto-engineering
```

### 卸载

```bash
claude plugin uninstall auto-engineering@auto-engineering
claude plugin marketplace remove auto-engineering
rm -rf ~/.claude/auto-engineering
=======
## 安装 (参照 superpowers 模式)

```bash
# 1. git clone 完整仓库到 ~/.claude/ (不是 plugins/)
git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/auto-engineering

# 2. symlink 到 plugins 目录
mkdir -p ~/.claude/plugins
ln -sfn ~/.claude/auto-engineering ~/.claude/plugins/auto-engineering

# 3. uv tool install 全局 (Engine 在 PATH)
cd ~/.claude/auto-engineering
uv tool install --force .

# 4. 编辑 ~/.claude/plugins/installed_plugins.json 加 auto-engineering@local 条目
# (Claude Code 通过这个发现 plugin)

# 5. 重启 Claude Code → /dev-loop 等 7 个 slash command 可用
```

## Claude Code 内 marketplace 方式

```bash
/plugin marketplace add qianminjian/Auto-engineering
/plugin install auto-engineering@auto-engineering
>>>>>>> 8f95426a614139462d235628b8ffdbf263ec807b
```

## 验证

```bash
<<<<<<< HEAD
ls ~/.claude/plugins/cache/auto-engineering/auto-engineering/5.0.0/    # 应存在
which ae                                                                  # /Users/minjianq/.local/bin/ae
ae doctor                                                                  # 7/7 PASS
```

## 重启 Claude Code 后

`/help` 看到 7 个 `/ae:*` slash command:
=======
which ae          # /Users/minjianq/.local/bin/ae
ae doctor          # 7/7 通过
```

## 重启 Claude Code

安装完成后**重启 Claude Code**, `/help` 看到 7 个 slash command:
>>>>>>> 8f95426a614139462d235628b8ffdbf263ec807b
- `/dev-loop` — 3 Stage Agent 循环
- `/status` — 当前进度
- `/checkpoint` — SQLite checkpoint 管理
- `/project-tdd` — TDD 快速循环
- `/project-worktree` — git worktree 隔离
- `/project-agent` — 单 Agent 调用
- `/project-ci` — 跑全量 Gate

<<<<<<< HEAD
## 为什么这种方案 (与其他 plugin 一致)

`claude plugin marketplace add <path>` + `claude plugin install <plugin>@<marketplace>` 是 Claude Code 官方机制, 与 4 个已装 plugin 同样的安装方式:
- claude-code-settings (Anthropic 官方)
- claude-code-workflows (社区)
- agent-workshop (社区)
- qianminjian-tools (你之前的 marketplace, 包含 project-engineering-init)
=======
## 升级

```bash
cd ~/.claude/auto-engineering && git pull
uv tool install --force .
```

## 卸载

```bash
uv tool uninstall auto-engineering
unlink ~/.claude/plugins/auto-engineering
rm -rf ~/.claude/auto-engineering
# 手动从 ~/.claude/plugins/installed_plugins.json 移除 auto-engineering@local
```

## 为什么这样安装 (参照 superpowers)

| 步骤 | 为什么 |
|------|--------|
| `git clone 到 ~/.claude/auto-engineering` | 完整仓库在 `~/.claude/`, 多个 plugin 可共享同一仓库路径 |
| `symlink 到 plugins 目录` | Claude Code 扫描 `~/.claude/plugins/<name>/` 发现 plugin |
| `uv tool install .` | Engine 在用户 PATH 全局可用 (其他 plugin 也可调) |
| 编辑 `installed_plugins.json` | Claude Code 通过这条目加载 plugin (注册表机制, 不是目录扫描) |
>>>>>>> 8f95426a614139462d235628b8ffdbf263ec807b

## 核心特性

- 3 Stage Agent loop (architect → developer → critic)
<<<<<<< HEAD
- 7 Gate 质量门
=======
- 7 Gate 质量门 (safety / lint / type_check / contract / test / coverage / build)
>>>>>>> 8f95426a614139462d235628b8ffdbf263ec807b
- 5 Guardrail (pass / block / retry, drop deprecated)
- Init-Loop 接口契约
- SQLite checkpoint 恢复
- 1155+ tests, 7/7 smoke, 20/20 acceptance, 90% coverage
<<<<<<< HEAD
- Claude Code Plugin 标准 layout
=======
- Claude Code Plugin 标准 layout (commands / hooks / skills / .claude-plugin/)
>>>>>>> 8f95426a614139462d235628b8ffdbf263ec807b
