# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ 硬禁令（2026-06-24 96GB 内存爆炸事故后确立）

**核心风险**：96GB 内存爆炸事故 — 3 个 subagent 并行扫描 `references/` 全量建立 file tree index，触发 macOS `vm-compressor-space-shortage` → 系统强制重启。

**参考源码已迁出项目根**（路径：`~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/`，下文 `$AE_REFS_DIR/`）。

**禁止：批量 / 并行加载（事故根因）：**

- ❌ 禁止并行启动多个 subagent 同时扫描 `$AE_REFS_DIR/`
- ❌ 禁止一次性 Read 整个框架
- ❌ 禁止 `ls -R $AE_REFS_DIR/` 递归列出全部文件
- ❌ 禁止 `find $AE_REFS_DIR/` 不带过滤列出所有文件
- ❌ 禁止 `grep -r $AE_REFS_DIR/` 后批量 Read 多个匹配文件

**允许的探索方式：**

- ✅ `ls $AE_REFS_DIR/` 顶层（只 6 个子目录名）
- ✅ `find $AE_REFS_DIR/ -name "目标.py" -type f`（定位单个文件）
- ✅ `grep -n "符号" $AE_REFS_DIR/特定路径`（只输出匹配行）
- ✅ Read 单个文件 50-200 行片段（用 `offset`/`limit`）
- ✅ 一次只探索一个组件
- ✅ 探索后立即总结要点 + 丢弃 context

**三步法**：Grep 定位 → 50-200 行 Read → 立即丢弃。

**Why：** 2026-06-24 atdo Phase 02 spawn 3 个 subagent，每个 claude code 进程扫描 project root 建立 file tree index，3 个进程叠加吃掉 96 GB 物理内存 → macOS 强制重启。

---

## 项目信息

- 名称：Auto-Engineering
- 类型：Python CLI 应用 + Claude Code Plugin（`/dev-loop` slash command 形态）
- 版本：v5.0（Plugin + Loop Engineering + Init-Loop 接口契约）
- 创建日期：2026-06-23

## 项目性质

**Loop Engineering 调度脚手架**——提供 Claude Code Plugin 形态的 Stage-sequenced Agent loop。用户在 Claude Code 会话中输入 `/dev-loop "实现登录功能"`，Plugin 调度 Python Loop Engine 在子进程中运行 architect → developer → critic 三阶段 Agent 循环。

**两层架构**：
- **Plugin 层**（`.claude-plugin/`）：Bash 委托 `uv run ae <subcommand>`，控制流在 Python
- **Engine 层**（`auto_engineering/`）：Python 控制流（12 步主循环 + StageRouter + Guardrail + 7 Gates + Checkpoint）

**Init Engineering 是独立项目**——本项目通过 Init-Loop 接口契约消费 Init 产出的 `.ae-state/init-manifest.json`。Init 项目不在本仓库范围。

**核心依赖**：`anthropic`、`click`、`pydantic`、`asyncio`

## 架构

```
Plugin 层 (.claude-plugin/)
  commands/*.md  ──→  Bash 委托 uv run ae <subcommand>
  hooks/*.sh     ──→  事件响应 (pre-tool/post-edit/stop/session-start/on-pr)
  skills/SKILL.md ──→  告诉 Agent 何时使用 ae 命令

Engine 层 (auto_engineering/)
  loop/
    orchestrator.py    — 12 步主循环 (v5.0 §B7.1)
    stage_router.py    — T1-T6 转换表 + MAJOR 计数
    guardrail.py       — 5 Guardrail (3 态: pass/block/retry)
    round.py           — DAG 拓扑分层 + asyncio.gather
    plan.py            — Task DAG + get_tasks_by_stage
    task_factory.py    — _apply_outcome_to_state + _tasks_from_batch_plan
    convergence.py     — 4 级收敛判定 (hard/quality/stagnant/semantic)
    init_contract.py   — Init-Loop 接口契约 (IL-AC-01~05)
  agents/
    base.py            — BaseAgent + tool_use loop + double-layer parse
    authz.py           — AUTHZ_MATRIX 9×3 (role-based tool authorization)
    prompts.py         — v5.0 system prompts (architect/developer/critic)
  gates/
    base.py            — Gate ABC + GateVerdict + DEFAULT_GATES (7 道)
    safety/lint/type_check/contract/test/coverage/build.py
  cli/
    doctor.py          — 环境预检 (Python/uv/git/sqlite3/API_KEY/.ae-state/init-manifest)
    gate_check.py      — --all (5 道) / --quick (3 道)
    agent.py           — 单 Agent 调用 (architect/developer/critic)
    dev_loop.py        — 入口, 构造 Orchestrator + AgentRuntime
    status.py          — JSON 输出 loop 进度 (7 字段 + recent_history × 5)
    checkpoint.py      — SQLite checkpoint list/show/delete/resume
  engine/
    state.py           — EngineState dataclass (16 字段, v5.0 §B1.1)
  tools/               — file/bash/git/test tools + sandbox
  runtime/             — AgentRuntime + CancellationToken + TaskContext
```

**参考框架：**

| 框架 | 路径 | 核心文件 | 借鉴内容 |
|------|------|---------|---------|
| LangGraph | `$AE_REFS_DIR/langgraph/` | `pregel/_loop.py`, `pregel/_algo.py` | tick/after_tick 控制流 + apply_writes packet |
| AutoGen | `$AE_REFS_DIR/autogen/` | `_single_threaded_agent_runtime.py` | AgentRuntime 懒实例化 + role 路由 |
| CrewAI | `$AE_REFS_DIR/crewai/` | `guardrail.py` | Guardrail 2 态 + pre/post 时机 |

## 设计文档

| 文档 | 内容 | 读取条件 |
|------|------|---------|
| `design/BEACON.md` | 设计基线（目标/范围/决策/当前状态） | 任何设计讨论时先读 |
| `design/INDEX.md` | 文档索引（含合并日志/归档清单） | 检索文档时 |
| `design/v5.0-Design-Loop.md` | v5.0 Plugin + Loop Engine 完整设计（2934 行，自包含） | 开发 loop/gates/agents/cli 时 |
| `docs/EARS-v5.0.md` | v5.0 验收 15 AC + 5 IL-AC | 验收/审计时 |
| `docs/api-reference.md` | v5.0 API 接口文档 + 5 代码示例 | 查阅 API 时 |
| `docs/production-deployment.md` | 生产部署流程 + 环境变量 + 降级 | 部署时 |
| `docs/e2e-real-run.md` | 端到端验证流程 + 性能基准 | 真跑验证时 |
| `docs/PLUGIN-USAGE.md` | Plugin 安装 + 使用 + 故障排查 | 用户安装时 |

## 核心命令

```bash
# 测试（16G 内存约束 + 虚拟环境）
.venv/bin/pytest tests/test_xxx.py -v --no-cov --timeout=60   # 单文件
.venv/bin/pytest tests/ --no-cov --timeout=120 -q              # 全量
.venv/bin/pytest tests/ --cov=auto_engineering --cov-report=term-missing --timeout=300 -q  # 覆盖率

# CLI
uv run ae doctor                    # 环境预检 (7 项)
uv run ae gate-check --quick        # 快速 Gate (safety+lint+type_check)
uv run ae gate-check --all          # 全量 Gate
uv run ae status --format json      # 当前进度
uv run ae agent architect "需求"    # 单 Agent 调用
uv run ae dev-loop "需求"           # 完整 3 Stage 循环

# Plugin
bash ae-plugin-acceptance-test.sh   # Plugin 验收 (20 场景)
python3 scripts/atdo_smoke.py       # Runtime smoke (7 维度)
```

## atdo 开发过程基本要求（2026-06-30 用户确立）

**核心约束**：atdo 自动化开发过程中，所有进展必须反馈到前台，不得静默在后台开发。每次会话、每次 atdo 启动都生效。

**强制要求**：

- ✅ Progress Display：每 Phase / Step 开始前输出 `[Auto-Phase] Phase N/M: <name> | Step X/Y: <description>`
- ✅ Heartbeat 协议：agent spawn 后每 5/10/15 分钟输出心跳
- ✅ 关键决策显式化：gate 通过 / 失败 / manual gate 触发 / 用户介入点必须显式输出
- ✅ 失败升级前台：不静默重试，立即告诉用户"已失败 + 当前状态 + 选项"

**禁止**：

- ❌ 禁止用 Bash `run_in_background: true` 跑 atdo 相关命令
- ❌ 禁止 agent 输出超 10 分钟无 ProgressDisplay
- ❌ 禁止 Step 间静默跳过
- ❌ 禁止 push / force push / reset --hard / rm 等破坏性操作无前台确认

**B 级 hybrid gate 规则**：

- ✅ auto-pass 仅跳过用户签字（AskUserQuestion），**不跳过自动 code review**（atdo Step 7.5, atdo-GCR-01）
- ✅ Gate Code Review 强制：每个 gate phase 完成后必须执行 /code review

**How to apply**：任何 `/atdo` 启动先显示 ProgressDisplay。CronCreate 唤醒后第一行输出 `atdo auto-resume for Phase N/M`。Manual gate 时显式标注"需要用户介入"。

---

## 管理约束

- tests/ 下测试，覆盖率 ≥ 90%（用户硬指标）
- 测试运行遵守 `@.claude/rules/pytest-memory-management.md`（16G 内存约束）
- **Agent tool spawn 遵守 `@.claude/rules/agent-spawn-timeout.md`（3 层超时防护）**
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- Init Engineering 是独立项目——本项目通过 Init-Loop 接口契约（IL.1-IL.6）消费 Init 产物，不包含 Init 实现