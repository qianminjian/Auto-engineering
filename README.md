# Auto-Engineering v5.0

Claude Code Plugin — Loop Engineering 调度脚手架

团队内部分发 (5-20 用户本地安装) — 不是 SaaS, 不是个人工具.

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
```

## 验证

```bash
ls ~/.claude/plugins/cache/auto-engineering/auto-engineering/5.0.0/    # 应存在
which ae                                                                  # /Users/minjianq/.local/bin/ae
ae doctor                                                                  # 7/7 PASS
```

## 重启 Claude Code 后

`/help` 看到 7 个 `/ae:*` slash command:
- `/dev-loop` — 3 Stage Agent 循环
- `/status` — 当前进度
- `/checkpoint` — SQLite checkpoint 管理
- `/project-tdd` — TDD 快速循环
- `/project-worktree` — git worktree 隔离
- `/project-agent` — 单 Agent 调用
- `/project-ci` — 跑全量 Gate

## 为什么这种方案 (与其他 plugin 一致)

`claude plugin marketplace add <path>` + `claude plugin install <plugin>@<marketplace>` 是 Claude Code 官方机制, 与 4 个已装 plugin 同样的安装方式:
- claude-code-settings (Anthropic 官方)
- claude-code-workflows (社区)
- agent-workshop (社区)
- qianminjian-tools (你之前的 marketplace, 包含 project-engineering-init)

## 核心特性

- 3 Stage Agent loop (architect → developer → critic)
- 7 Gate 质量门
- 5 Guardrail (pass / block / retry, drop deprecated)
- Init-Loop 接口契约
- SQLite checkpoint 恢复
- 1155+ tests, 7/7 smoke, 20/20 acceptance, 90% coverage
- Claude Code Plugin 标准 layout
