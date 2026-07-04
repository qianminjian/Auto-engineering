# Auto-Engineering v5.0

Claude Code Plugin — Loop Engineering 调度脚手架

团队内部分发 (5-20 用户本地安装) — 不是 SaaS, 不是个人工具.

## 环境要求

- Python >= 3.12
- uv >= 0.5.0 ([安装指南](https://docs.astral.sh/uv/getting-started/installation/))
- git >= 2.40
- sqlite3 >= 3.42

## 安装 (一条命令)

```bash
# 1. git clone
git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering

# 2. 安装依赖
cd ~/.claude/plugins/auto-engineering && uv sync

# 3. 重启 Claude Code → /ae:dev-loop 等 7 个 slash command 可用
```

全局 `ae` 命令（可选，CLI 调试用）：

```bash
cd ~/.claude/plugins/auto-engineering
uv tool install . --force
ae --version   # 5.0.0
ae doctor      # 环境预检
```

## 使用

### Agent Tool 模式 (推荐，零配置)

```
/ae:dev-loop "实现用户登录功能，支持 JWT 认证"
```

直接在 Claude Code agent 内执行三阶段循环（architect → developer → critic），复用 agent 的 LLM 连接，**零配置**。

### CLI 模式 (需要 `uv tool install .`)

```bash
ae dev-loop "实现登录功能" --max-rounds 10 --log-format json
ae doctor        # 环境预检 (7 项)
ae status        # 查看 loop 进度
ae checkpoint list  # checkpoint 管理
```

## 其他命令

| 命令 | 说明 |
|------|------|
| `/ae:dev-loop` | 开发循环 |
| `/ae:status` | 查看状态 |
| `/ae:checkpoint` | Checkpoint 管理 |
| `/ae:project-tdd` | TDD 执行 |
| `/ae:project-worktree` | 创建 worktree |
| `/ae:project-agent` | 单 Agent 调用 |
| `/ae:project-ci` | 跑全量 CI gate |

## 设计文档

- `design/v5.0-Design-Loop.md` — v5.0 完整设计 (3099 行)
- `design/BEACON.md` — 架构决策 33 条
- `docs/EARS-v5.0.md` — 15 AC + 5 IL-AC

## 测试

```bash
.venv/bin/pytest tests/ -q --timeout=30
# 1337 passed + 1 skipped + 0 failed
```

## 架构

```
Claude Code Agent (宿主)
  /ae:dev-loop ──→ commands/dev-loop.md ──→ JSONL 协议
    Plan agent (architect) → agent 自己 (developer) → code-reviewer agent (critic)
  Python 控制流: while 循环 / Gate 并行 / 收敛判定 / Checkpoint 持久化
```

## 许可

MIT
