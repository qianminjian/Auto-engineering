# Auto-Engineering v5.0

Claude Code Plugin — Loop Engineering 调度脚手架

团队内部分发 (5-20 用户本地安装) — 不是 SaaS, 不是个人工具.

## 安装 (参照 superpowers 模式)

### 推荐方式: git clone

```bash
git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
cd ~/.claude/plugins/auto-engineering
uv tool install --force .
```

然后在 `~/.claude/plugins/installed_plugins.json` 加条目 (Claude Code 才能发现 plugin):

```json
"auto-engineering@local": [{
  "scope": "user",
  "installPath": "/Users/minjianq/.claude/plugins/auto-engineering",
  "version": "5.0.0",
  ...
}]
```

### Claude Code 内 marketplace 方式

```bash
/plugin marketplace add qianminjian/Auto-engineering
/plugin install auto-engineering@auto-engineering
```

## 验证

```bash
which ae          # /Users/minjianq/.local/bin/ae
ae doctor          # 7/7 通过
```

## 重启 Claude Code

安装完成后**重启 Claude Code**, `/help` 看到 7 个 slash command:
- `/dev-loop` — 3 Stage Agent 循环
- `/status` — 当前进度
- `/checkpoint` — SQLite checkpoint 管理
- `/project-tdd` — TDD 快速循环
- `/project-worktree` — git worktree 隔离
- `/project-agent` — 单 Agent 调用
- `/project-ci` — 跑全量 Gate

## 升级

```bash
cd ~/.claude/plugins/auto-engineering && git pull
uv tool install --force .
```

## 卸载

```bash
uv tool uninstall auto-engineering
rm -rf ~/.claude/plugins/auto-engineering
# 手动从 ~/.claude/plugins/installed_plugins.json 移除 auto-engineering@local
```

## 核心特性

- 3 Stage Agent loop (architect → developer → critic)
- 7 Gate 质量门 (safety / lint / type_check / contract / test / coverage / build)
- 5 Guardrail (pass / block / retry, drop deprecated)
- Init-Loop 接口契约
- SQLite checkpoint 恢复
- 1155+ tests, 7/7 smoke, 20/20 acceptance, 90% coverage
- Claude Code Plugin 标准 layout (commands / hooks / skills / .claude-plugin/)
</content>