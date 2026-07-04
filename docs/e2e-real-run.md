# Auto-Engineering v5.0 End-to-End Real Run

> **Version**: 5.0.0 | **Status**: Production-ready | **Last updated**: 2026-07-01
> 决策依据: `design/BEACON.md` 决策 #28 · `design/v5.0-Design-Loop.md` §B7.6
>
> v1.0 / v2.0 端到端流程已删除 — 归档版本见 `_scratch/his_bak/e2e-real-run.md` (v2.2 FINAL, 49 行)。

本文档描述 Auto-Engineering v5.0 真实端到端运行流程：Plugin 安装 → dev-loop 启动 → 3 Stage → APPROVE → Gate → Checkpoint → 验收。

---

## 1. 完整流程图

```
[用户]                         [Plugin]                       [Engine]
  │                              │                              │
  │ /ae:dev-loop "需求"          │                              │
  ├─────────────────────────────→│                              │
  │                              │ session-start.sh              │
  │                              │   (uv/python/git/API_KEY)    │
  │                              │                              │
  │                              │ .venv/bin/ae dev-loop ...    │
  │                              ├─────────────────────────────→│
  │                              │                              │ 1. _init_state()
  │                              │                              │ 2. while not _should_stop:
  │                              │                              │ 3.   stage = router.next(state)
  │                              │                              │ 4.   plan = plan.get_tasks_by_stage(stage)
  │                              │                              │ 5.   ctx = _build_per_task_ctx(state)
  │                              │                              │ 6.   outcomes = round.run_round(...)
  │                              │                              │ 7.   _apply_outcome_to_state(...)
  │                              │                              │ 8.   verdict = _run_gates()
  │                              │                              │ 9.   guardrail = chain.check()
  │                              │                              │ 10.  _save_checkpoint(state)
  │                              │                              │ 11.  _clear_stage_fields(...)
  │                              │                              │ 12.  _derive_status(state)
  │                              │                              │
  │                              │   ┌─ Stage: architect ─┐    │
  │                              │   │ PlanExists G2 pass │    │
  │                              │   │ → T1→T2: developer  │    │
  │                              │   └─────────────────────┘    │
  │                              │                              │
  │                              │   ┌─ Stage: developer ─┐    │
  │                              │   │ GitDiffExists G3 ✓  │    │
  │                              │   │ TestsPass G4 ✓      │    │
  │                              │   │ LintGate ✓ Type ✓   │    │
  │                              │   │ → T2→T3: critic     │    │
  │                              │   └─────────────────────┘    │
  │                              │                              │
  │                              │   ┌─ Stage: critic ────┐    │
  │                              │   │ verdict: PASS      │    │
  │                              │   │ → T4: APPROVE       │    │
  │                              │   └─────────────────────┘    │
  │                              │                              │
  │                              │   <stdout JSON 6 fields>     │
  │                              │←─────────────────────────────┤
  │                              │ status=success              │
  │ <Plugin 展示 JSON>           │ thread_id=xxx                │
  │←─────────────────────────────┤ rounds=3                     │
  │                              │ verdict=APPROVE              │
  │                              │ duration_sec=180             │
  │                              │ gate_summary={...}           │
  │                              │                              │
```

---

## 2. 标准场景："实现 hello world 函数"

### 2.1 启动

```bash
# 在 Claude Code 中
/ae:dev-loop "实现一个返回 'Hello, World!' 的 Python 函数 hello()，包含单元测试"
```

### 2.2 期望 stdout JSON (EARS AC-01)

```json
{
  "status": "success",
  "thread_id": "thread-20260701-094512-abc123",
  "rounds": 3,
  "verdict": "APPROVE",
  "duration_sec": 87.4,
  "gate_summary": {
    "lint": true,
    "type_check": true,
    "test": true,
    "coverage": null,
    "safety": true,
    "build": null,
    "contract": null
  }
}
```

### 2.3 实际步骤展开

| Step | Stage | 耗时 (实测) | 关键事件 |
|------|-------|------------|----------|
| 1 | (init) | <1s | OrchestratorConfig 构造 + StageRouter 初始化 |
| 2 | architect | 25s | PlanExists (G2) pass → 进入 developer |
| 3 | developer | 35s | GitDiffExists (G3) ✓ + TestsPass (G4) ✓ + LintGate ✓ → 进入 critic |
| 4 | critic | 25s | verdict: PASS (0 MAJOR, 0 MINOR) → APPROVE |
| 5 | (finalize) | <1s | _save_checkpoint → exit 0 |

> 实测单 Stage 25-35s (含 LLM 调用 + Gate 跑)，3 Stage 总计 80-100s。

---

## 3. 性能基准 (v5.0 §B7.6)

### 3.1 单 Stage 时序

| Stage | LLM 调用 | 工具执行 | Gate 跑 | 合计 |
|-------|----------|----------|---------|------|
| architect | 8-20s | <1s | <1s (skip) | **8-20s** |
| developer | 10-25s | 2-10s | 5-30s (lint+type+test) | **17-65s** |
| critic | 8-20s | 1-3s | <1s (skip) | **9-23s** |

**单 Stage 边界**：15s ~ 2min (P50 ~40s, P95 ~80s, P99 ~120s)。

### 3.2 完整 3 Stage 端到端

| 场景 | P50 | P95 | P99 |
|------|-----|-----|-----|
| 简单需求 (hello world) | **85s** | 130s | 200s |
| 中等需求 (5-10 文件改动) | **180s** | 360s | 480s |
| 复杂需求 (10+ 文件 + 多模块) | **400s** | 720s | 1100s |

**3 Stage 边界**：45s ~ 6min (P50 ~3min, P95 ~6min, P99 ~10min)。

### 3.3 性能瓶颈分布

| 瓶颈 | 占比 | 缓解 |
|------|------|------|
| LLM 网络延迟 | ~40% | Anthropic API 区域优化 + 流式响应 |
| LintGate (ruff) | ~15% | 缓存 ruff 结果 (Phase 12 路线图) |
| TestGate (pytest) | ~25% | `--timeout=60` + 测试并行 |
| TypeCheckGate (mypy) | ~10% | 增量 mypy |
| Checkpoint SQLite 写 | <1% | 已优化 (P0-2 性能基线) |

### 3.4 内存占用 (16G 物理)

| 组件 | 峰值 |
|------|------|
| Python 引擎 | ~250 MB |
| uv sync 后 .venv | ~800 MB |
| pytest + coverage (禁用) | 0 (coverage 默认关) |
| pytest 无 coverage | ~150 MB |
| **单 dev-loop run 总计** | **~1.2 GB** |

> Coverage 默认禁用，详见 `docs/production-deployment.md` §5.1。

---

## 4. 错误场景与恢复

### 4.1 Stage 失败 (Gate FAIL)

```
Stage: developer
  → TestsPass (G4) FAIL: test_hello.py::test_empty_input FAILED
  → retry_count = 1
  → StageRouter: 重试 developer
  → 第 2 次: GitDiffExists (G3) ✓ + TestsPass (G4) ✓ → 进入 critic
```

恢复：自动重试。retry_count 持久化到 checkpoint，重启后保留。

### 4.2 连续 MAJOR (StageRouter T6)

```
Stage: critic
  → verdict: MAJOR (majors_in_a_row = 1)
  → 退回 developer
Stage: critic
  → verdict: MAJOR (majors_in_a_row = 2)  ← 触发 T6
  → StageRouter.should_stop = True
  → exit 1
```

恢复：人工 review 失败原因，调整需求或 plan 后重启：

```bash
/ae:dev-loop "需求 (调整后)" --max-rounds 20
```

### 4.3 LLM 超时

```
AnthropicProvider.create_message → 连续 3 次 timeout
  → raise AEError(LLM_MAX_RETRIES)
  → 退出码 1，无 checkpoint
```

恢复：检查网络 / API key 后重试。

### 4.4 用户 Ctrl-C

```
Ctrl-C → CancellationToken.trigger() → TASK_CANCELLED
  → 写 interrupted checkpoint
  → exit 130
```

恢复：
```bash
/ae:dev-loop --resume
# 或
.venv/bin/ae dev-loop --resume
```

### 4.5 ANTHROPIC_API_KEY 缺失

```
Settings.from_env() → CONFIG_MISSING_API_KEY
  → exit 2
  → 无 checkpoint
```

恢复：
```bash
.venv/bin/ae doctor    # 验证
/ae:dev-loop "..."
```

---

## 5. 真实环境验证清单 (EARS AC-11/12/14/15)

| AC | 场景 | 验证方式 | 状态 |
|----|------|----------|------|
| AC-11 | Plugin → Engine + Agent 展示 JSON | `bash ae-plugin-acceptance-test.sh` 场景 1 | PASS (Phase 09) |
| AC-12 | plugin.json + requirements → 8 slash command 注册 | cp + restart + `/help` | **用户验证** (真实环境) |
| AC-14 | pre-tool hook denylist 拦截 | `bash ae-plugin-acceptance-test.sh` 场景 2 | PASS (Phase 09) |
| AC-15 | Engine 崩溃 Plugin 优雅展示 | `bash ae-plugin-acceptance-test.sh` 场景 3 | PASS (Phase 09) |

> 真实环境（cp + restart + /help + 端到端 dev-loop）由用户手动执行，AI 仅提供 acceptance test 脚本。

---

## 6. 验收脚本

```bash
# 一键端到端验证
bash ae-plugin-acceptance-test.sh           # 18 场景 (Phase 09 实装 3 场景)
.venv/bin/ae doctor                          # 环境自检
pytest tests/ --no-cov --timeout=300 -q      # 799 测试
```

---

## 7. 引用

- `docs/PLUGIN-USAGE.md` — Plugin 命令 + 降级
- `docs/production-deployment.md` — 安装 + 环境变量
- `docs/api-reference.md` — 完整接口
- `docs/EARS-v5.0.md` — 15 AC + 5 IL-AC 验收表
- `design/v5.0-Design-Loop.md` §B7.6 — 性能基准
- `ae-plugin-acceptance-test.sh` — 18 场景 acceptance test

---

_v2.0 端到端流程已删除。归档版本见 `_scratch/his_bak/e2e-real-run.md`。_
