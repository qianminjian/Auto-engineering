# CLAUDE.md

## ⚠️ 硬禁令（2026-06-24 96GB 内存爆炸事故后确立）

**核心风险**：96GB 内存爆炸事故 — 3 个 subagent 并行扫描 `references/` 全量建立 file tree index，触发 macOS `vm-compressor-space-shortage` → 系统强制重启。

**参考源码已迁出项目根**（路径：`~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/`，下文 `$AE_REFS_DIR/`）。

**禁止：批量 / 并行加载（事故根因）：**

- ❌ 禁止并行启动多个 subagent 同时扫描 `$AE_REFS_DIR/`
- ❌ 禁止一次性 Read 整个框架（如 Read `$AE_REFS_DIR/langgraph/` 全部文件）
- ❌ 禁止 `ls -R $AE_REFS_DIR/` 递归列出全部文件（等同批量索引）
- ❌ 禁止 `find $AE_REFS_DIR/` 不带过滤列出所有文件
- ❌ 禁止 `grep -r $AE_REFS_DIR/` 后批量 Read 多个匹配文件

**允许的探索方式（单次 / 小批量 — 不触发内存爆炸）：**

- ✅ `ls $AE_REFS_DIR/` 顶层（只 6 个子目录名，轻量）
- ✅ `find $AE_REFS_DIR/ -name "目标.py" -type f`（定位单个文件）
- ✅ `grep -n "符号" $AE_REFS_DIR/特定路径`（只输出匹配行）
- ✅ Read 单个文件 50-200 行片段（用 `offset`/`limit`，绝不整文件 Read）
- ✅ 一次只探索一个组件（如只探索 `langgraph/pregel/_loop.py`）
- ✅ 探索后立即总结要点 + 丢弃 context，不缓存

**纪律：**

- 探索 ≠ 批量：可以探索，但限制单次 / 并行量级
- 优先 Grep 定位 → 50-200 行 Read → 立即丢弃（三步法，见 `memory/loop-dev-code-reference-rule`）
- 不并行触发多 subagent 全量扫描 `$AE_REFS_DIR/`（事故根因）

**已迁出项目根**（`.gitignore` 保留防御行 + `pyrightconfig.json` 已移除 exclude）。

**Why：** 2026-06-24 16:10 atdo Phase 02 spawn 3 个 subagent，每个 claude code 进程启动时扫描项目根建立 file tree index（含 references/），3 个进程叠加吃掉 96 GB 物理内存，触发 macOS `vm-compressor-space-shortage` → 系统强制重启。

**How to apply：** 任何需要参考实现的场景，必须先 Grep 定位 50-200 行片段，绝不批量 Read。

---

## 项目信息

- 名称：Auto-Engineering
- 类型：Python CLI 应用 — 团队级 Loop 工程 + 多 Agent 协作
- 版本：1.0.0（设计阶段）
- 创建日期：2026-06-23

## 项目性质

本项目为 **Python 应用**，非 Claude Code Skill。使用 Claude API（Anthropic SDK）调用 LLM，Python 控制执行流。

核心依赖：`anthropic`、`click`、`pydantic`、`asyncio`

## 架构

```
Python 控制流（确定性）        LLM 调用（智能）
┌──────────────────────┐     ┌──────────────────┐
│ engine/loop.py        │     │ agents/           │
│   while True:         │────→│   architect.py   │
│     tick()            │     │   developer.py   │
│     agent.execute()   │     │   critic.py      │
│     gates.check()     │←────│                  │
│     after_tick()      │     └──────────────────┘
└──────────────────────┘
```

## 参考源码

参考源码已迁出项目根。完整路径：`~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/`（下文 `$AE_REFS_DIR/` 即此路径）。

| 框架 | 路径 | 核心文件 | 用途 |
|------|------|---------|------|
| LangGraph | `$AE_REFS_DIR/langgraph/` | `pregel/_loop.py`, `pregel/_algo.py`, `graph/state.py` | Loop 引擎参考 |
| AutoGen | `$AE_REFS_DIR/autogen/` | `_single_threaded_agent_runtime.py` | Agent 运行时参考 |
| CrewAI | `$AE_REFS_DIR/crewai/` | `crew.py`, `task.py` | 任务编排参考 |
| Copier | `$AE_REFS_DIR/copier/` | `_main.py`(Worker), `_user_data.py`(Question/AnswersMap) | init 脚手架参考 |
| Cookiecutter | `$AE_REFS_DIR/cookiecutter/` | `generate.py`, `prompt.py`, `main.py` | init 模板渲染参考 |
| Yeoman | `$AE_REFS_DIR/yeoman/` | `lib/routes/` | init 组合模式参考 |

## 设计文档

| 文档 | 内容 | 读取条件 |
|------|------|---------|
| `design/v1.0-SHARED.md` | 共享架构、CLI 设计、共享契约、关键决策 | 任何设计讨论时先读 |
| `design/v1.0-INIT.md` | init 子系统完整设计（~1800 行） | 开发 `ae init` 时 |
| `design/v1.0-LOOP.md` | dev-loop 子系统完整设计（~550 行） | 开发 `ae dev-loop` 时 |
| `design/v1.0-TEMPLATES.md` | 43 个模板文件 + 8 个 ae-template.yml | 实现 `init/templates/` 时 |

## 核心命令（设计目标）

## 管理约束

- tests/ 下测试，覆盖率 ≥ 80%
- 测试运行遵守 `@.claude/rules/pytest-memory-management.md`（16G 内存约束）
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- 模板从 project-engineering-init 迁移，保持模板变量兼容
