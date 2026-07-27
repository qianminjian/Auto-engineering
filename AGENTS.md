<!--
此文件由 agent-rules/ 公共模板与平台适配模板自动生成，请勿直接修改。
修改模板后运行：python3 scripts/sync_agent_instructions.py
-->

# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 跨 Agent 规则同步

- 公共规则编辑 `agent-rules/instructions.md.tmpl`，平台差异编辑对应的
  `agent-rules/claude.md.tmpl` 或 `agent-rules/codex.md.tmpl`。
- 禁止直接编辑生成的 `CLAUDE.md` 和 `AGENTS.md`。
- 修改模板后必须运行 `python3 scripts/sync_agent_instructions.py`，并用 `--check` 校验无漂移。

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

**Why：** 2026-06-24 atdo Phase 02 spawn 3 个 subagent，每个 Codex 进程扫描 project root 建立 file tree index，3 个进程叠加吃掉 96 GB 物理内存 → macOS 强制重启。

---

## 项目信息

- Auto-Engineering — Python CLI + Codex Plugin，Loop Engineering 调度脚手架
- 入口命令：`ae <subcommand>`，核心流程：`ae dev-loop --init → --tick → --result`
- Init Engineering 是独立项目，本项目通过 `.ae-state/init-manifest.json` 消费其产物

## 关键设计文档

| 文档 | 用途 |
|------|------|
| `design/BEACON.md` | 设计基线，任何设计讨论前先读 |
| `design/v5.6-Design-Loop.md` | Tick 协议 + 验证层完整规格 |
| `design/IMPLEMENTATION-TRACKER.md` | 实施进度跟踪 |
| `skills/auto-engineering/SKILL.md` | dev-loop Agent 执行协议 |

## 核心命令

```bash
# v5.6 Tick 循环 (离散调用, Python 每次 tick 独立进程)
ae dev-loop --init                           # 初始化 tick 循环
ae dev-loop --tick --result <result.json>    # 提交本轮 result, 推进 tick
ae dev-loop --status --format json           # 当前进度
ae dev-loop --resume                         # 从 checkpoint 恢复
ae dev-loop "需求"                           # v5.5 裸参数路径 (legacy, 连续 while 循环)

# 测试（16G 内存约束 + 虚拟环境）
# 全量: ~1703 tests, ~10s (1702 passed + 1 skipped)
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

---

## 管理约束

- tests/ 下测试，覆盖率 ≥ 90%（用户硬指标）
- 全量 1702 passed / 1 skipped（2026-07-26 基准，含审计回归测试；死测试已随 tools/ 删除，OTel flaky 已修复）
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- Init Engineering 是独立项目——本项目通过 Init-Loop 接口契约（IL.1-IL.6）消费 Init 产物，不包含 Init 实现

## 编码约定

- **语言约定**：用户可见字符串（CLI 输出、错误消息）用中文；error_code / 日志 key / 变量名 / 代码标识符用英文。禁止同一消息中英混杂。
- **命名约定**：Guardrail 后缀统一 (`XxxGuardrail`)，Gate 后缀统一 (`XxxGate`)；REDGuardrail / FreshGuardrail / RegressionGuardrail 均使用 `Guardrail` 后缀。

## Codex 平台适配

- Codex 通过 `AGENTS.md` 层级加载本规则，不解析 Claude Code 的 `@include` 语义。
- Skill 与 Plugin 资产位于 `.codex-plugin/`；共享循环必须通过 `scripts/ae-run` 调用。
- 子代理调用使用 Codex 当前原生协作能力，但仍须遵守公共并发和内存边界。

### Codex 必载关键规则

- **测试内存**：本机按 16G 物理内存约束执行。优先运行单文件或关键字测试，
  必须带 `--no-cov --timeout=60`；全量测试仅在开发节点串行运行，
  禁止并发运行多个 pytest 进程，禁止后台运行 pytest。覆盖率只可显式启用。
- **Agent 超时**：调用前展示阶段、步骤和超时阈值；调用期间执行
  5 / 10 / 15 分钟心跳，15 分钟无进展时停止等待、报告状态并按授权边界处理，
  不得无限等待或静默重试。
- **设计不可降级**：设计与代码不一致时默认补齐代码，禁止通过降低设计标准消除差异。
  BEACON 决策状态翻转必须先获得用户审批；涉及架构约束的删除、废弃、降级或替代同样
  必须先审批。引用 BEACON 决策编号前须确认编号真实存在。
- **操作纪律**：所有实施遵守“先记录 → 再执行 → 再更新”；先在跟踪表记录进行中，
  再执行代码或文档变更，验证后更新状态与证据。
