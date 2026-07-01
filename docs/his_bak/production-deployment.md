# Auto-Engineering 生产部署清单

> 创建：2026-06-26 | 阶段：v2.2 FINAL
> 位置：`docs/` = 永久资产，不 gitignore
> 决策依据：`design/BEACON.md` 决策 19/27 (v2.5 P0-FINAL, v1.0 退役)

## 环境要求

| 项 | 最低 | 推荐 |
|----|------|------|
| Python | 3.12+ | 3.12 |
| 内存 | 8 GB | 16 GB+ |
| 必需 | `ANTHROPIC_API_KEY` 环境变量 | 同左 |
| Git | 2.30+ | 最新 |

Python 3.12 依赖 PEP 695 内联 `Generic[T]` 语法（决策 G.3 + ruff UP046）。
低于 3.12 无法 import `auto_engineering.loop.types`。

## 安装

### 方式 A — pip

```bash
git clone <repo> && cd Auto-engineering
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e . && ae --version
```

### 方式 B — uv（推荐）

```bash
uv sync && uv run ae --version
```

## CLI 命令速查

| 命令 | 用途 |
|------|------|
| `ae init <project>` | 项目脚手架（43 模板 + 8 项目类型） |
| `ae dev-loop "<req>"` | 单需求开发循环（v2.5 起仅 v2.0 Orchestrator） |
| `ae dev-loop --max-rounds N "<req>"` | 控制 round 数 |
| `ae status` | 项目环境摘要 + checkpoint 数量 |
| `ae checkpoint list/show/resume` | v1.1 checkpoint 管理 |
| `ae checkpoint v2 list/show/delete` | v2.0 SQLite checkpoint 管理 |

完整参数见 `docs/api-reference.md`。

## 监控

- `.ae-checkpoints/` — SQLite 数据库（v1.1 + v2.0 共享）
- stdout/stderr — Stage 进度 + Gate 验证
- `ae status` — 实时项目摘要

`--log-format text` (默认) / `json`（输出到 stderr）。

## 升级路径

```bash
git pull && pip install -e .   # 或 uv sync
ae --version && ae --help       # 验证
```

**无 state migration**：v2.2 升级无需数据迁移。v1.1 / v2.0 schema 向后兼容，
新字段为可选（决策 13a/17）。不兼容时 `store.load()` 抛
`CheckpointSchemaMismatch` 并提示手动迁移。

## 已知限制（v2.2）

| 限制 | 影响 | 后续 |
|------|------|------|
| `--llm-provider` 仅 `anthropic` | ollama/openai 报错 exit 6 | T10 后续 |
| `--multi` 标记未实装 | 仅打印提示 | 未来 |
| Checkpoint resume 需走 `ae dev-loop` | resume 子命令仅占位 | 后续 |
| `--incremental` 增量模式 | v1.1+ P3 | 未来 |

## 引用

- `design/BEACON.md` 决策 19/27 — v2.2 闭环 + v2.5 P0-FINAL v1.0 退役
- `docs/api-reference.md` · `docs/troubleshooting.md` · `docs/e2e-real-run.md`
