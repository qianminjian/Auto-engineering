---
phase: 06
plan: 06-v2-multi-agent-prep
subsystem: v2.0-multi-agent
tags: [architect, contract-gate, worktree, tdd]
dependency_graph:
  requires:
    - phase-01-dev-loop-baseagent-tools-agent
  provides:
    - file-precheck-prompt
    - contract-gate-hook
    - worktree-include-template
  affects:
    - auto_engineering/agents/base.py
    - auto_engineering/agents/architect.py
    - auto_engineering/errors.py
    - auto_engineering/init/templates/app-service/
tech-stack:
  added: []
  patterns:
    - two-green-gate (v2.0 multi-agent 前置)
    - dataclass field with None default (contract_gate)
    - jinja2 conditional include (worktreeinclude.tmpl)
key-files:
  created:
    - auto_engineering/init/templates/app-service/.worktreeinclude.tmpl
    - tests/test_phase06.py
  modified:
    - auto_engineering/agents/architect.py
    - auto_engineering/agents/base.py
    - auto_engineering/errors.py
decisions:
  - Task 5.4 Channel 系统 + Orchestrator deferred 到 v2.0（v1.1 验证未完成,需独立设计阶段）
  - contract_gate 默认 None = auto-approve,不阻塞现有调用流
  - CONTRACT_REJECTED 用 ErrorCode 而非 GuardrailRetrySignal（契约拒绝 = fatal,不可重试）
metrics:
  duration_min: ~12
  tasks_done: 3
  files_modified: 4
  files_created: 2
  test_count: 11
  completed_date: 2026-06-25
---

# Phase 06 Plan: v2.0 多 Agent 并行前置工作

## One-liner

Architect 文件集预检 prompt + BaseAgent contract_gate 钩子 + .worktreeinclude.tmpl 恢复,
为 v2.0 多 Agent 并行铺路；Task 5.4 Channel 系统 + Orchestrator 显式 deferred.

---

## 执行摘要

本阶段完成 Phase 5（v1.1-Plan-Dev.md §三）的前 3 个前置任务,
Channel 系统 + Orchestrator（5.4）作为 final-phase manual gate 决策点
明确标记 deferred 到 v2.0.

**关键产出**:

1. **Architect prompt 文件集预检**: 在 `ARCHITECT_SYSTEM_PROMPT` 增加
   "工作流程（v2.0 多 Agent 前置）"段,要求 Architect 在分析前先输出
   `files_needed` / `files_to_create` / `files_to_modify` 三段式结构.
   这是后续多 Agent 并行时分文件派单的依据.

2. **BaseAgent contract_gate 钩子**: two-green gate 的第一层.
   `execute()` 在 LLM 调用前触发 `contract_gate(task, ctx) -> bool`,
   返回 False 抛 `AEError(CONTRACT_REJECTED)`,LLM 不被调用.
   默认 `None` = auto-approve,不破坏现有调用流.

3. **`.worktreeinclude.tmpl` 恢复**: Claude Code `claude --worktree`
   多 Agent 并行时的 include 规则,只同步规则中列出的文件,
   避免每个 worktree 复制整个项目（~100MB+）.

---

## 任务完成情况

### Task 5.1: Architect prompt 文件集预检指令 ✅

**Commit**: `cc21861`
**Files**: `auto_engineering/agents/architect.py` (+25 行)
**Tests**: 4/4 通过

新增 prompt 段:
```
## 工作流程（v2.0 多 Agent 前置）

在分析任何需求前,你必须先输出**文件集预检**(file precheck).
预检是一份关于"这次实现将涉及哪些文件"的结构化清单.

**预检顺序：先输出文件集预检,再进入 plan 分析**(两个阶段不可混淆).
```

输出字段强制:
- `files_needed`: 所有涉及文件（创建+修改+仅引用）
- `files_to_create`: 本次新创建
- `files_to_modify`: 本次修改

### Task 5.2: 契约确认机制（two-green gate） ✅

**Commit**: `5384e2b`
**Files**: `auto_engineering/agents/base.py` (+11 行), `auto_engineering/errors.py` (+2 行)
**Tests**: 4/4 通过

新增:
- `BaseAgent.contract_gate: Callable[[Task, TaskContext], bool] | None = None`
- `ErrorCode.CONTRACT_REJECTED = "CONTRACT_REJECTED"`
- `execute()` 第一行（messages 构造后）插入 gate 调用

**关键设计选择**:

| 选择 | 理由 |
|------|------|
| 默认 `None` = auto-approve | 不破坏现有所有调用方（architect/developer/critic/runtime） |
| 抛 AEError 而非 GuardrailRetrySignal | 契约拒绝 = fatal,不可重试（与 GUARDRAIL_RETRY 对齐的语义边界） |
| gate 在 messages 构造后立即调用 | 在 LLM 调用前最早拦截点,避免浪费 token |

### Task 5.3: templates/app-service/.worktreeinclude.tmpl 恢复 ✅

**Commit**: `56b1a14`
**Files**: `auto_engineering/init/templates/app-service/.worktreeinclude.tmpl` (新, 50 行)
**Tests**: 3/3 通过

模板内容覆盖:
- 核心交付物（README.md / CLAUDE.md / Makefile / pyproject.toml 等）
- 源码根（src/lib/app/**, 按 language 条件渲染）
- 配置（config/** + *.yml/*.yaml/*.toml）
- 测试（tests/**）
- 文档（docs/** + design/BEACON.md + design/INDEX.md）
- 工作流产物（_scratch/**）
- 显式排除（.git / node_modules / .venv / dist / __pycache__）

### Task 5.4: Channel 系统 + Orchestrator — DEFERRED ✅

**实施状态**: 未实施
**理由**: v1.1 验证未完成,v2.0 Channel 系统需要独立设计阶段

本阶段**不**实施 Channel 系统 + Orchestrator. 这是 final-phase manual gate
的决策点之一 — 用户需明确 v2.0 范围后启动独立阶段.

---

## 验证结果

| 项目 | 结果 |
|------|------|
| Phase 06 新测试 (test_phase06.py) | 11/11 通过 |
| ruff check Phase 06 改动 | 0 errors |
| 相关模块回归测试 | 61/61 通过（test_base_agent + test_agents_3 + test_base_agent_llm_errors + test_loop + test_e2e_real_llm + test_runtime）,2 skipped |
| 全项目 ruff check | 0 errors |

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] 新增 ErrorCode.CONTRACT_REJECTED**
- **Found during:** Task 5.2 RED phase
- **Issue:** 契约拒绝需要结构化错误码,但 ErrorCode 没有对应值
- **Fix:** 在 errors.py:39 添加 `CONTRACT_REJECTED = "CONTRACT_REJECTED"`
- **Files modified:** auto_engineering/errors.py
- **Commit:** 5384e2b

---

## TDD Gate Compliance

| Gate | Status | Evidence |
|------|--------|----------|
| RED | ✅ | tests/test_phase06.py 创建时 10/11 FAIL（仅 execute_with_precheck_output 通过,因为它只测字段解析） |
| GREEN | ✅ | 全部实现后 11/11 PASS |
| REFACTOR | ✅ | ruff 修复 SIM102（嵌套 if → 单 if + and）+ I001（test imports 集中到顶部） |

---

## Deferred Issues

### Task 5.4 Channel 系统 + Orchestrator

**Why deferred**:
- v1.1 验证（Phase 03 init E2E / Phase 04 ruff 债清理 / Phase 05 docs）尚未全绿
- Channel 是 Loop Engine 的基础抽象,直接破坏 v1.0 风险高
- Orchestrator 涉及多 Agent 调度协议,需要独立设计阶段 + 用户确认范围

**Requires before un-deferring**:
- [ ] v1.1 全部阶段 E2E 验证通过
- [ ] 用户对 v2.0 范围决策（参考 v2.0-LOOP-ANALYSIS.md）
- [ ] 独立 v2.0 design phase 启动

---

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| 无新增威胁面 | - | 本阶段改动: prompt 加字段 + BaseAgent 加可选 gate + jinja2 模板. 均不引入新网络/认证/文件访问路径. |

---

## Self-Check: PASSED

- [x] tests/test_phase06.py 已创建并存在
- [x] architect.py / base.py / errors.py 改动存在
- [x] .worktreeinclude.tmpl 已创建
- [x] 4 个 commits 全部存在:
  - cc21861 (Task 5.1)
  - 5384e2b (Task 5.2)
  - 56b1a14 (Task 5.3)
  - b216712 (tests)
- [x] ruff 0 errors
- [x] 11/11 新测试通过
- [x] 61/61 回归测试通过

---

## Next Phase Handoff

**Final phase manual gate (awaiting_user_review)**:

本阶段完成后,orchestrator 应发起 AskUserQuestion 询问用户对 v2.0 范围决策:
1. Channel 系统设计范围（LastValue/Accumulating/Barrier 哪些 v2.0 必须）
2. Orchestrator 是否独立阶段
3. v2.0 时间窗口（v1.2 之后 vs 立即启动）

详见 design/v2.0-LOOP-ANALYSIS.md.