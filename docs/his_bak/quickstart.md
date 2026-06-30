# ae dev-loop Quickstart

5 分钟跑通第一个 dev-loop。

## 前置条件

- Python 3.10+
- `pip install auto-engineering`
- `export ANTHROPIC_API_KEY=sk-ant-...`

## Hello World

```bash
# 1. 初始化一个项目
ae init my-project --type cli-tool

# 2. 进入项目目录
cd my-project

# 3. 启动开发循环
ae dev-loop "实现一个 hello world 函数"
```

dev-loop 输出类似：
```
Starting dev-loop: 实现一个 hello world 函数
[v2.0] Stage 2/3: developer
  ✓ Stage 2 done in 3.2s (tokens: 1234)
[v2.0] Gate check: safety=pass, lint=pass
[orchestrator_done] rounds=2 verdict_level=3 should_stop=True
✓ dev-loop complete: status=done, steps=2, checkpoint=v2-r2
```

## 核心命令

| 命令 | 作用 |
|------|------|
| `ae init <dir>` | 初始化项目骨架 |
| `ae dev-loop "<需求>"` | 单需求自动开发循环 |
| `ae status` | 查看当前进度 |
| `ae checkpoint list` | 列出所有 checkpoint |
| `ae checkpoint show <id>` | 查看 checkpoint 详情 |

## 常见问题

- **无 API key**: 设置 `ANTHROPIC_API_KEY` 环境变量
- **no git repo**: `ae dev-loop` 需要在 git 仓库中运行
- **test failure**: 查看 `docs/troubleshooting.md`
