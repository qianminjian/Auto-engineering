# Auto-Engineering CLI 参考

> 创建：2026-06-26 | 阶段：v2.2 FINAL
> 位置：`docs/` = 永久资产
> 决策依据：`design/BEACON.md` 决策 11/12/19

## ae init — 项目脚手架

```bash
ae init <project> [options]
```

| Option | 说明 |
|--------|------|
| `<project>` | 项目名 / 目标路径（默认 cwd） |
| `--type` | 类型（app-service/library/cli-tool/skill/hook/mcp-server/spec-doc/monorepo） |
| `--defaults` | 非交互，全用默认值 |
| `--force` | 允许覆盖非空目录 |
| `--from-answers <file>` | 从 `.ae-answers.yml` 重放 |
| `--package-manager` | npm/pnpm/yarn/bun/uv/poetry |
| `--ci` | github/gitlab/none |
| `--test-runner` | 测试框架 |
| `--no-typescript` / `--no-lefthook` | 禁用 TS / Lefthook |
| `--pretend` / `--skip-tasks` / `--quiet` / `--incremental` | 见 `ae init --help` |

## ae dev-loop — 单需求开发循环

```bash
ae dev-loop "<requirement>" [options]
```

| Option | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `<requirement>` | arg | — | 需求文本 |
| `--max-steps` | int | 3 | v1.0 最大迭代步数 |
| `--max-rounds` | int | 3 | v2.0 最大 Round 数 |
| `--max-tokens` | int | 0 | Token 预算（0=无限） |
| `--max-cost` | float | 0.0 | 美元成本上限 |
| `--multi` | flag | F | 多 Agent 并行（未来） |
| `--dry-run` | flag | F | 只跑 architect（v1.0） |
| `--log-format` | str | text | text / json |
| `--llm-provider` | str | anthropic | anthropic/ollama/openai |
| `--project-root` | path | cwd | 项目根目录 |
| `--use-v1` / `--use-v2` | flag | F | 强制 v1.0 / v2.0（互斥） |

**路由**：默认 v2.0（需 `ANTHROPIC_API_KEY`）→ 无 key fallback v1.0；同时设置互斥 exit 2。

## ae status — 项目摘要

输出项目名/类型/包管理/测试/TS/Lefthook/CI/Git + v2.0 checkpoint 数。

## ae checkpoint — v1.1 / v2.0

```bash
ae checkpoint list / show <id> / resume <id>          # v1.1
ae checkpoint v2 list [--round N] / show <id> / delete <id>  # v2.0
```

resume 子命令为占位（实际恢复走 `ae dev-loop`）。

## 环境变量 / 退出码

| 变量 | 必需 | 说明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | v2.0 必需 | 无 key 时 dev-loop fallback v1.0 |

| Code | 类别 | 触发 |
|------|------|------|
| 0 | 成功 | — |
| 1 | 通用 | 未捕获异常 |
| 2 | USER | 配置/参数错 |
| 3 | API | LLM 失败 |
| 4 | NET | Checkpoint IO 失败 |
| 5 | BIZ | Guardrail / Stage 重试耗尽 |
| 6 | 未实装 | `--llm-provider=ollama/openai` |

## 引用

- `design/BEACON.md` 决策 11/12/19 · `auto_engineering/cli.py`
- `docs/production-deployment.md` · `docs/troubleshooting.md`
