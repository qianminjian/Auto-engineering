# CLAUDE.md

## ⚠️ 硬禁令（违反即停 — 2026-06-24 96GB 内存爆炸事故后确立）

**`references/` 严禁加载到内存：**
- ❌ 禁止 Read/Bash/Glob 任一文件到 context
- ❌ 禁止 `cat references/**` / `find references/` / `ls -R references/` / `wc -l references/**`
- ❌ 禁止把 references/ 内容粘贴到 prompt / commit message / 设计文档
- ✅ 需要参考时按 `memory/loop-dev-code-reference-rule`：Grep 定位关键符号 → Read 50-200 行片段 → 立即丢弃
- ✅ 已加入 `.gitignore`，claude code / pyright / serena 均不扫描

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

`references/` 目录包含六个业界框架/工具的完整源码：

| 框架 | 路径 | 核心文件 | 用途 |
|------|------|---------|------|
| LangGraph | `references/langgraph/` | `pregel/_loop.py`, `pregel/_algo.py`, `graph/state.py` | Loop 引擎参考 |
| AutoGen | `references/autogen/` | `_single_threaded_agent_runtime.py` | Agent 运行时参考 |
| CrewAI | `references/crewai/` | `crew.py`, `task.py` | 任务编排参考 |
| Copier | `references/copier/` | `_main.py`(Worker), `_user_data.py`(Question/AnswersMap) | init 脚手架参考 |
| Cookiecutter | `references/cookiecutter/` | `generate.py`, `prompt.py`, `main.py` | init 模板渲染参考 |
| Yeoman | `references/yeoman/` | `lib/routes/` | init 组合模式参考 |

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
- 参考源码（references/）为只读，不修改
- 模板从 project-engineering-init 迁移，保持模板变量兼容
