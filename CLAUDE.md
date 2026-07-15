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
- 版本：v5.6（Tick-Based Discrete Invocation + 5 层验证 + Pre-flight Gap Analysis）+ v7.0 双驱动远期架构
- 创建日期：2026-06-23 | 更新：2026-07-15
- 里程碑：Phase 1-10 = 102/102 全完成；v7.0 主体搁置待后续里程碑

## 项目性质

**Loop Engineering 调度脚手架**——提供 Claude Code Plugin 形态的 Stage-sequenced Agent loop。用户在 Claude Code 会话中输入 `/dev-loop "实现登录功能"`，Plugin 调度 Python Loop Engine 在子进程中运行 architect → developer → critic 三阶段 Agent 循环。

**两层架构 + 双引擎共存**：
- **Plugin 层**（`.claude-plugin/`）：Bash 委托 `ae <subcommand>`，控制流在 Python
- **Engine 层**（`auto_engineering/`）：
  - **v5.6 TickOrchestrator**（主引擎）：Tick-Based Discrete Invocation（`ae dev-loop --init → --tick → --result` 文件桥接协议），Python 每次 tick 独立进程（读 SQLite → 验证 → Guardrail → Gate → ConvergenceJudge → Checkpoint → 输出 action JSON → 退出），Agent 通过反复调用 `--tick` 驱动循环。Python 循环引擎永不调 LLM
  - **v5.5 Orchestrator**（共存）：`ae dev-loop "需求"` 裸参数路径，连续 while 循环直调 LLM（legacy，保留共存不复用）
- **v7.0 双驱动远期架构**：单引擎(TickOrchestrator)+双驱动(Agent/Standalone) ports&adapters，当前仅做接缝预留（T33a/T33b）

**Init Engineering 是独立项目**——本项目通过 Init-Loop 接口契约消费 Init 产出的 `.ae-state/init-manifest.json`。Init 项目不在本仓库范围。

**核心依赖**：`anthropic`、`click`、`pydantic`、`asyncio`

## 架构

```
Plugin 层 (.claude-plugin/)
  commands/*.md  ──→  Bash 委托 ae <subcommand>
  hooks/*.sh     ──→  事件响应 (pre-tool/post-edit/stop/session-start/on-pr)
  skills/SKILL.md ──→  告诉 Agent 何时使用 ae 命令

Engine 层 (auto_engineering/)
  loop/
    tick_orchestrator.py — v5.6 Tick 主引擎 (1017 行, 4 after-handler + _build_action + _apply_result_to_state)
    orchestrator.py      — v5.5 连续 while 循环 (1208 行, 共存)
    stage_router.py      — T1-T22 转换表 + MAJOR 计数 + refine_allowed
    guardrail.py         — 9 Guardrail (3 态: pass/block/retry, 含 REDGuard/FreshGate/RegressionGate)
    convergence.py       — 4 级收敛判定 (hard/quality/stagnant/semantic) + done verdict
    plan.py              — Task DAG + get_tasks_by_stage
    task_factory.py      — _apply_outcome_to_state + _tasks_from_batch_plan
    init_contract.py     — Init-Loop 接口契约 (IL-AC-01~08)
    refine.py            — plan_refine 回路 (B6.10 归一)
    checkpoint/          — SQLite checkpoint 持久化
  agents/
    base.py              — BaseAgent + tool_use loop + double-layer parse
    authz.py             — AUTHZ_MATRIX 10×3 (role-based tool authorization)
    prompts.py           — v5.0 system prompts (architect/developer/critic, legacy)
  prompts/
    registry.py          — PromptRegistry (B12 中央提示词管理, sha256 版本锁)
    roles/               — 9 角色 prompt (architect/developer/critic/verifier/audit/...)
    fragments/           — 8 共享片段
  gates/
    base.py              — Gate ABC + GateVerdict + DEFAULT_GATES (7 道)
    safety/lint/type_check/audit/contract/test/build.py
    commit_msg_gate.py   — Angular 格式校验 (可选)
    deep_audit.py        — 3-agent 编排 deep audit
  cli/
    doctor.py            — 环境预检 (Python/uv/git/sqlite3/API_KEY/.ae-state/init-manifest)
    gate_check.py        — --all (5 道) / --quick (3 道)
    agent.py             — 单 Agent 调用 (architect/developer/critic)
    dev_loop.py          — Tick CLI 入口 (--init/--tick/--result/--status/--resume/--design-doc) + v5.5 裸参数路径
    status.py            — JSON 输出 loop 进度
    checkpoint.py        — SQLite checkpoint list/show/delete/resume
    progress.py          — 读 progress_tree_json → display/summary
  engine/
    state.py             — EngineState dataclass (36 字段, v5.6 扩展)
    batch_state.py       — BatchState 跨 tick 进度管理
    design_doc.py        — 设计文档解析 (markdown-it-py)
    progress_tree.py     — ProgressTree 构建/同步/聚合
    gap_analysis.py      — Pre-flight gap scan (B10.2)
  tools/                 — file/bash/git/test tools + sandbox + pr_backend.py
  runtime/               — AgentRuntime + CancellationToken + TaskContext
  prismscan/             — V5.1 代码库反向工程 (discover → extract → analyze)
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
| `design/v5.6-Design-Loop.md` | v5.6 Tick-Based Discrete Invocation 完整设计 (1728 行，自包含) | 开发 loop/gates/agents/cli/commands 时 |
| `docs/EARS-v5.0.md` | v5.0 验收 15 AC + 5 IL-AC | 验收/审计时 |
| `docs/api-reference.md` | v5.0 API 接口文档 + 5 代码示例 | 查阅 API 时 |
| `docs/production-deployment.md` | 生产部署流程 + 环境变量 + 降级 | 部署时 |
| `docs/e2e-real-run.md` | 端到端验证流程 + 性能基准 | 真跑验证时 |
| `docs/PLUGIN-USAGE.md` | Plugin 安装 + 使用 + 故障排查 | 用户安装时 |
| `design/IMPLEMENTATION-TRACKER.md` | v5.6 实施跟踪表 (Phase 1-10, 102/102 任务) | 任何开发/进度汇报时 |
| `design/v7.0-Plan-DualDriver.md` | v7.0 双驱动远期架构路线图 (V7-1~V7-8) | v7.0 相关讨论时 |

## 核心命令

```bash
# PrismScan V5.1 (代码库反向工程)
ae prismscan discover-extract     # discover + extract → action JSON
ae prismscan check-result <file>  # 校验 AnalysisResult JSON
/prismscan                        # Plugin 命令入口 (完整 Phase 1 闭环)

# v5.6 Tick 循环 (离散调用, Python 每次 tick 独立进程)
ae dev-loop --init                           # 初始化 tick 循环
ae dev-loop --tick --result <result.json>    # 提交本轮 result, 推进 tick
ae dev-loop --status --format json           # 当前进度
ae dev-loop --resume                         # 从 checkpoint 恢复
ae dev-loop "需求"                           # v5.5 裸参数路径 (legacy, 连续 while 循环)

# 测试（16G 内存约束 + 虚拟环境）
# 全量: ~2132 tests, ~50s
uv run pytest tests/test_xxx.py -v --no-cov --timeout=60   # 单文件
uv run pytest tests/ --no-cov --timeout=120 -q              # 全量
uv run pytest tests/ --cov=auto_engineering --cov-report=term-missing --timeout=300 -q  # 覆盖率

# CLI
ae doctor                    # 环境预检 (7 项)
ae gate-check --quick        # 快速 Gate (safety+lint+type_check)
ae gate-check --all          # 全量 Gate
ae agent architect "需求"    # 单 Agent 调用
ae progress                  # 显示 tick 循环进度

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

## /ae:dev-loop Agent Tool 执行模式（v5.1, 2026-07-04 生产反馈修正）

**关键修正**：2026-07-04 生产使用报告（`prismscan/_scratch/reports/2026-07-04-dev-loop-execution-analysis.md`）显示 dev-loop 原有的 Python 子进程 (`ae dev-loop "..."`) 模式在 Claude Code agent 内**完全失效**——子进程无法获取 agent 的 ANTHROPIC_AUTH_TOKEN，导致 architect/critic LLM 调用永远失败。

**v5.1 起 `ae dev-loop` CLI 子进程废弃**，改为 **Agent tool 直接执行模式**：

### 执行协议（Agents 必须遵守）

当用户调用 `/ae:dev-loop <requirement>` 时：

1. **Stage 1 — Architect (Plan Agent)**
   - **Spawn a Plan agent** via Agent tool（给定 `requirement` + `commands/dev-loop.md` 完整 spec 作为 prompt）
   - Architect 回 output: `batch_plan` (TaskCreate list, ≤5 files/batch), `file_list`, `contracts`
   - **禁止跳过**：Plan agent 必须产出结构化 JSON，不能只写 3 句标题

2. **Stage 2 — Developer (Claude Code Agent 自己）**
   - **逐个 TaskCreate 执行 TDD（Red→Green→Refactor）**
   - 每个 unit: RED (write failing test) → GREEN (minimal impl) → REFACTOR (clean > still green) → git commit
   - **完成所有 TaskCreate 后**：跑全部 7 Gate **并行** (`safety` + `lint` + `type_check` + `audit` + `contract` + `test` + `build`)
   - 记录：files_changed, commit_hash, test_results

3. **Stage 3 — Critic (code-reviewer Agent）**
   - **Spawn a code-reviewer agent** via Agent tool（给定 `files_changed` + `test_results` + `gate_results`）
   - Critic 回 output: `verdict` (APPROVE/MAJOR), `findings` (file:line + severity + issue + suggested_fix)
   - **MAJOR criteria**: ≥1 P0 或 ≥3 P1
   - **if MAJOR**: agent 回到 Stage 2，根据 `findings` + `suggested_fix` 修复问题

4. **Stage 4 — Design Doc Sync（Critic APPROVE 后、收敛判定前，强制执行）**
   - **对照 `design/` 文档检查本轮所有改动**：Agent 已知道本轮改了哪些文件、做了什么决策
   - **代码与设计文档不一致** → 更新设计文档（`design/v5.6-Design-Loop.md` 或 `design/BEACON.md`）
   - **新增了设计文档未覆盖的决策** → 补充到 `design/BEACON.md` 决策表
   - **不接受"延后同步"**：文档未同步视为 Stage 4 未完成，不得进入收敛判定
   - **判断标准**：下一轮 dev-loop 的 Agent 能从设计文档中准确理解当前代码的真实架构

5. **Convergence while loop**（参考 `commands/dev-loop.md` 完整 spec）
   - max_rounds = 3 (Self-Refine 最优)
   - consecutive_majors ≥ 3 → HARD_LIMIT stop
   - APPROVE + 所有 gate PASSED → 成功退出

### 关键原则

- ❌ 禁止只用串行 Read→Write→Edit→Commit 替代三阶段（这是 Interact 模式，不是 dev-loop）
- ✅ 必须 spawn Plan agent 产出完整 batch_plan（不是"3 行 TaskCreate 标题"）
- ✅ 必须 spawn code-reviewer agent 产出 structured findings（file:line + severity）
- ✅ 每个 TDD 循环遵守 Red→Green→Refactor 顺序
- ✅ Gate 必须并行跑（用 `asyncio.gather` 或至少跑 safety/lint/test 3 个）
- ✅ MAJOR 反馈链（critic → developer → redo）是 Self-Refine 核心，不能被 skip
- ✅ Stage 4 Design Doc Sync 是强制步骤：文档未同步不得进入收敛判定，不接受"延后同步"
- ❌ **静默降级禁令**：当 Command/Skill 的 Bash 块或 Agent tool spawn 失败时，
  Agent **不得**静默接管并手工模拟三阶段。必须向用户报告失败原因 + 提供替代方案。
- ❌ **失败不可见禁令**：用户有权知道 dev-loop 是否真的在运行。任何 Bash 块失败、
  Agent tool 不可用、plan/critic agent spawn 失败——必须**显式告知用户**，
  不得在后台无声降级为手工编码模式。

### Agent 行为规则（2026-07-04 生产反馈修正）

1. **Bash 块失败处理**：当 `commands/*.md` 中的 Bash 块返回非零退出码时,
   Agent 必须 read 输出中的错误信息并报告用户。Agent 不得直接跳过 Bash
   块进入下一步。

2. **Agent tool 不可用处理**：当 Plan agent 或 code-reviewer agent 不可用时,
   Agent 必须告知用户："dev-loop 需要 Plan agent（architect 阶段）和
   code-reviewer agent（critic 阶段）。当前不可用，是否继续手工模式？"
   然后等待用户确认。

3. **进度透明**：每个 dev-loop 阶段开始前，输出 `[Stage N/M] Running <stage>...`
   让用户明确知道 Agent 在遵循 dev-loop 工作流而非手工编码。

4. **不可恢复失败处理**：当连续 2 次 agent spawn 或 Bash 块失败时,
   dev-loop 应停止并告知用户："dev-loop 无法继续，请检查 auto-engineering
   安装状态或手动完成剩余工作。" 不得无限重试或静默切换模式。

---

## 当前测试状态 (2026-07-15)

- **全量**: ~2132 tests, ~50s (16G 内存约束, `--no-cov --timeout=120`)
- **PrismScan V5.1**: 92 tests (Phase 1 流转覆盖率 92%, 25 条路径覆盖 23 条)
- **v5.6 Tick 引擎**: TickOrchestrator 单测 52 + StageRouter 43 + BatchState 21 + ProgressTree 20 + 集成测试
- **契约测试**: action/result schema 21 tests + init_contract round-trip + Plugin 验收 20 场景
- **S6.6 Agent 运行时**: 2 tests (需 API key, 无 key 时自动 skip)

## 管理约束

- tests/ 下测试，覆盖率 ≥ 90%（用户硬指标）
- 全量 ~2132 tests 通过（2026-07-15 基准）
- 测试运行遵守 `@.claude/rules/pytest-memory-management.md`（16G 内存约束）
- **Agent tool spawn 遵守 `@.claude/rules/agent-spawn-timeout.md`（3 层超时防护）**
- **设计文档修改遵守 `@.claude/rules/design-document-inviolability.md`（🚨 2026-07-08 事故确立：BEACON决策翻转须审批、设计优先于代码）**
- **每次操作遵守「先记录→再执行→再更新」纪律**（memory `feedback-record-before-execute.md`）
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- Init Engineering 是独立项目——本项目通过 Init-Loop 接口契约（IL.1-IL.6）消费 Init 产物，不包含 Init 实现