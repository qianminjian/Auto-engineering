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
- 版本：v2.0（v1.0 init/dev-loop 基线 + v1.1 修复 + v2.0 多 Agent 并发）
- 创建日期：2026-06-23

## 项目性质

本项目为 **Python 应用**，非 Claude Code Skill。使用 Claude API（Anthropic SDK）调用 LLM，Python 控制执行流。

核心依赖：`anthropic`、`click`、`pydantic`、`asyncio`

## 架构

```
v1.0 主路径 (engine + agents + tools)            v2.0 增量 (loop + gates)
┌──────────────────────────────┐     ┌──────────────────────────────────┐
│ engine/loop.py                │     │ loop/                             │
│   while True:                 │     │   orchestrator.py  (主循环)       │
│     tick()                    │     │   round.py         (asyncio.gather)│
│     agent.execute() ──────────┼────→│   plan.py          (Task DAG)     │
│     gates.check()             │     │   state.py         (Channel 系统) │
│     after_tick()              │     │   checkpoint.py    (SQLite 持久化)│
└──────────────────────────────┘     │   convergence.py   (4 级判定)     │
         │                            └──────────────┬───────────────────┘
         ▼                                            ▼
┌──────────────────────────────┐     ┌──────────────────────────────────┐
│ agents/                       │     │ gates/                            │
│   architect.py                │     │   base.py (Gate 基类)             │
│   developer.py                │     │   safety.py / lint.py / type_check│
│   critic.py                   │     │   test.py / coverage.py / build.py │
└──────────────────────────────┘     │   contract.py (占位, 单 Agent 跳过)│
         │                            └──────────────────────────────────┘
         ▼
┌──────────────────────────────┐
│ tools/ + runtime/             │
│   file/bash/git/test_tools   │
│   AgentRuntime + MockRuntime │
└──────────────────────────────┘
```

> **v2.0 关键变化**：在 v1.0 基础上**新增** loop/ + gates/ 子系统（不删除 engine/runtime/tools）— 多 Agent asyncio.gather 并发 + 7 道质量门 + Channel 状态系统 + SQLite Checkpoint 持久化 + 4 级收敛判定。详见 `design/v2.0-Design-Loop.md`。

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
| `design/BEACON.md` | 设计基线（目标/范围/决策/当前状态） | 任何设计讨论时先读 |
| `design/INDEX.md` | 文档索引（含合并日志/归档清单） | 检索文档时 |
| `design/v1.0-Design-Shared.md` | 共享架构、CLI 设计、共享契约 | v1.0/v1.1 设计讨论时 |
| `design/v1.0-Design-Init.md` | init 子系统完整设计 + 实现偏差审计（§1.7） | 开发 `ae init` 时 |
| `design/v1.0-Design-Loop.md` | dev-loop v1.0 设计（v3.0 优化版，~1700 行） | 开发 v1.0 主路径时 |
| `design/v1.0-Design-Templates.md` | 43 个模板文件 + 8 个 ae-template.yml | 实现 `init/templates/` 时 |
| `design/v1.1-Audit-Report.md` | 架构审计报告（P0-P2 + 3 附录） | 审计/回归时 |
| `design/v1.1-Plan-Dev.md` | 整合开发计划（问题清单 + Phase 0-5） | v1.1 计划追溯时 |
| `design/v2.0-Analysis-Loop.md` | v2.0 多 Agent 并发架构分析（**§八 删除项已取消**） | v2.0 设计推理时 |
| `design/v2.0-Design-Loop.md` | v2.0 dev-loop 设计基线（基于 v2.0 实际落地） | 开发 v2.0 loop/ + gates/ 时 |

## 核心命令

```bash
# v1.0 主路径（保留）
ae init <project> --type <type>           # 项目环境初始化
ae dev-loop <requirement>                 # 单需求开发循环（v1.0 engine）
ae status                                 # 当前进度（v2.0 增强显示 LoopState）

# v2.0 增量
ae checkpoint v2 list [--round <n>]       # 列 v2 SQLite checkpoints
ae checkpoint v2 show <id>                # 看 v2 checkpoint 详情
ae checkpoint v2 delete <id>              # 删 v2 checkpoint
ae checkpoint v2 resume <id>              # 从 v2 checkpoint 恢复

# v1.0 checkpoint（旧路径兼容）
ae checkpoint list|show|delete|resume     # 旧 JSON 文件 checkpoint
```

## atdo 开发过程基本要求（2026-06-30 用户确立）

**核心约束**：atdo 自动化开发过程中，所有进展必须反馈到前台（Claude Code 会话），不得静默在后台开发。每次会话、每次 atdo 启动都生效。

**Why**：用户期望开发过程透明可见，避免长时间无反馈导致的"卡死焦虑"与"信任流失"。

**强制要求**：

- ✅ **Progress Display**：每 Phase / Step 开始前输出 `[Auto-Phase] Phase N/M: <name> | Step X/Y: <description]`（atdo 协议默认行为，不可省略）
- ✅ **Heartbeat 协议**：agent spawn 后每 5/10/15 分钟输出心跳（atdo agent-spawn-timeout.md 默认行为）
- ✅ **关键决策显式化**：阶段切换 / gate 通过 / 失败 / manual gate 触发 / 用户介入点必须显式输出
- ✅ **失败升级前台**：失败时不静默重试，立即告诉用户"已失败 + 当前状态 + 选项"
- ✅ **ALERT.md 写入路径**：`.phase-execution/ALERT.md` 必须前台摘要（不只是写文件）
- ✅ **CronCreate 唤醒后**：下次会话第一行输出 `atdo auto-resume for phase X/M` 让用户知道是续跑

**禁止**：

- ❌ 禁止用 Bash `run_in_background: true` 跑 atdo 相关命令（应前台执行，每步可见）
- ❌ 禁止 agent 输出超 10 分钟无 ProgressDisplay（违反 agent-spawn-timeout.md 心跳协议）
- ❌ 禁止 Step 间静默跳过（即使相同 Phase 必须显示状态变化）
- ❌ 禁止 push / force push / reset --hard / rm 等破坏性操作无前台确认

**B 级 hybrid gate 特殊规则**：

- ✅ **B 级 hybrid gate auto-pass**: atdo 推进遇到 B 级 hybrid gate（Phase 04/09/11 等）直接 auto-pass，不调 AskUserQuestion 等用户签字。跨会话规则已持久化至 memory `feedback-atdo-b-gate-auto-pass.md`。

**How to apply**：

- 任何 `/atdo` 命令启动时，先在响应中显示 `[Auto-Phase] Phase N/M: ...` 进度条，再执行协议
- CronCreate 唤醒后第一时间输出 `atdo auto-resume for Phase N/M`，避免用户疑惑"这是新 run 还是续跑"
- Manual gate / AskUserQuestion 时显式标注"需要用户介入"
- 失败时不绕路，立即升级 ALERT 并给用户选项

---

## 管理约束

- tests/ 下测试，覆盖率 ≥ 80%
- 测试运行遵守 `@.claude/rules/pytest-memory-management.md`（16G 内存约束）
- **Agent tool spawn 遵守 `@.claude/rules/agent-spawn-timeout.md`（3 层超时防护）**
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- 模板从 project-engineering-init 迁移，保持模板变量兼容
