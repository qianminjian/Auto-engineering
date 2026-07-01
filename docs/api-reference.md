# Auto-Engineering v5.0 API Reference

> **Version**: 5.0.0 | **Status**: Production-ready | **Last updated**: 2026-07-01
> 决策依据: `design/BEACON.md` 决策 #28 (v5.0 P0-FINAL) · `design/v5.0-Design-Loop.md`
>
> v1.0 (`engine/loop.py` 旧 LoopEngine) / v2.0 (`engine/runtime/` + `engine/loop.py` asyncio.gather) / v2.3 (orchestrator) 章节已删除 — 见 `_scratch/his_bak/api-reference.md` 归档版本。

Auto-Engineering v5.0 is a **stage-driven multi-agent engineering loop** with:
- **Orchestrator 12-step main loop** (v5.0 §B7.1)
- **StageRouter** (T1-T6 转换表 + MAJOR 计数)
- **GuardrailChain** (5 内置 Guardrails, fail-fast)
- **7 Gate 体系** (lint / type_check / test / coverage / safety / build / contract)
- **3 Stage pipeline** (architect → developer → critic, 后续 Stage 由 StageRouter 决定)
- **v2 SQLite Checkpoint** + retry_counters 持久化 (Phase 04 改造)
- **Init-Loop 契约** (init-manifest.json v1, 5 IL-AC 验证)
- **19 错误码** (ErrorCode 枚举, v5.0 §B10.1a)

---

## 1. CLI 入口 — `ae`

```bash
ae <subcommand> [options]
```

### 1.1 子命令总览 (v5.0)

| 子命令 | 类别 | 说明 | Phase |
|--------|------|------|-------|
| `ae doctor` | env | 环境自检（Python/uv/git/sqlite3/API_KEY/.ae-state/init-manifest）| 07+08 |
| `ae dev-loop "<req>"` | loop | 启动 3 Stage dev-loop（orchestrator 12 步主循环）| 04 |
| `ae dev-loop --resume` | loop | 从最近 checkpoint 恢复（带 retry_counters）| 04 |
| `ae dev-loop --no-gates` | loop | 3 级收敛（跳过 Gate 体系）| 07 |
| `ae gate-check [--all\|--quick]` | gate | 手动跑 7 Gates（按当前 stage 过滤）| 05+07 |
| `ae agent <role> "<req>"` | agent | 单 Agent 调用（architect/developer/critic）| 07 |
| `ae status` | state | 查 LoopState + recent_history × 5 | 07 |
| `ae checkpoint list` | ckpt | 列 v2 SQLite checkpoints | 04 |
| `ae checkpoint show <id>` | ckpt | 看 checkpoint 详情 | 04 |
| `ae checkpoint delete <id>` | ckpt | 删 checkpoint | 04 |
| `ae checkpoint resume <id>` | ckpt | 恢复指定 checkpoint | 04 |

> 旧路径 `ae init <project>` 在 v5.0 已迁移到 Init 子系统（不通过 `ae` 入口）。Init 子系统管理 `init-manifest.json`，详见 §6 Init-Loop 契约。

### 1.2 `ae doctor` 输出契约

```json
{
  "status": "ok|warn|fail",
  "checks": {
    "python": {"ok": true, "version": "3.12.4"},
    "uv": {"ok": true, "version": "0.4.18"},
    "git": {"ok": true, "version": "2.39.3"},
    "sqlite3": {"ok": true, "version": "3.43.2"},
    "ANTHROPIC_API_KEY": {"ok": true, "preview": "sk-ant-..."},
    ".ae-state": {"ok": true, "path": "/path/to/.ae-state"},
    "init-manifest": {"ok": true, "schema_version": 1, "path": "init-manifest.json"}
  }
}
```

退码：`0` = all ok / `1` = one or more fail。

### 1.3 `ae dev-loop` 退出码

| Code | 类别 | 触发 | EARS AC |
|------|------|------|---------|
| 0 | 成功 | 全部 Stage 收敛 + Gate 全 PASS | AC-01 |
| 1 | 通用 | 未捕获异常 | — |
| 2 | USER | 配置/参数错（缺 API_KEY / 无效 stage）| AC-09 |
| 130 | SIGINT | 用户 Ctrl-C（已写 interrupted checkpoint）| AC-10 |

> 详细错误码见 §5 19 错误码表。

---

## 2. Orchestrator 12 步主循环 (v5.0 §B7.1)

**模块**: `auto_engineering.loop.orchestrator.Orchestrator`

```python
from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig

config = OrchestratorConfig(
    project_root=Path("."),
    requirement="实现 OAuth2 登录",
    max_iterations=20,
    no_gates=False,           # True → 3 级收敛
    checkpoint_store=SQLiteCheckpointStore(...),
    guardrail_chain=GuardrailChain.default(),
    stage_router=StageRouter(),
)

orch = Orchestrator(config)
result = orch.run()           # 进入 12 步主循环
# 或: result = orch.resume(checkpoint_id="ckpt-xxx")
```

### 2.1 12 步主循环伪代码

```python
# v5.0 §B7.1 — 真实实现见 auto_engineering/loop/orchestrator.py:Orchestrator.run()
async def run(self) -> OrchestratorResult:
    state = self._init_state()                       # 1. 初始 LoopState
    while not self._should_stop(state):              # 2. 终止判定 (StageRouter)
        stage = self.stage_router.next(state)        # 3. Stage 决策 (T1-T6)
        plan = self.plan.get_tasks_by_stage(stage)   # 4. 取 Stage 内 Task DAG
        context = self._build_per_task_ctx(state)    # 5. 构造 per-task 上下文
        outcomes = await self.round.run_round(       # 6. 并发跑 Task (asyncio.gather)
            stage, plan, context
        )
        self._apply_outcome_to_state(state, outcomes)  # 7. 更新 state
        verdict = await self._run_gates()            # 8. 跑 Gate 体系
        guardrail = self.guardrail_chain.check()     # 9. 跑 Guardrail 链
        if guardrail.action == "block":
            break
        self._save_checkpoint(state)                 # 10. SQLite 持久化
        self._clear_stage_fields(state, stage)       # 11. 清 Stage 临时字段
        state.status = self._derive_status(state)    # 12. 推导新 status
    return OrchestratorResult(...)
```

### 2.2 关键签名

| 方法 | 输入 | 输出 | 异常 |
|------|------|------|------|
| `run()` | — | `OrchestratorResult` | `AEError` (CHECKPOINT_SAVE_FAILED 等) |
| `resume(checkpoint_id)` | str | `OrchestratorResult` | `CHECKPOINT_LOAD_FAILED` |
| `_save_checkpoint(state)` | EngineState | None | `CHECKPOINT_SAVE_FAILED` |
| `_run_gates()` | — | `dict[str, bool]` | Gate 自抛 |
| `_apply_outcome_to_state(state, outcomes)` | EngineState, list[TaskOutcome] | None | — |
| `_clear_stage_fields(state, stage)` | EngineState, str | None | — |
| `_derive_status(state)` | EngineState | str | — |

---

## 3. StageRouter (v5.0 §B3)

**模块**: `auto_engineering.loop.stage_router.StageRouter`

### 3.1 状态机 T1-T6 转换表

| 触发 | T# | current_stage → next_stage | 行为 |
|------|----|---------------------------|------|
| 启动 / architect 完成 | T1 | None → architect | 首次进入 |
| architect 通过 | T2 | architect → developer | 进入开发 |
| developer 通过 + critic MAJOR=0 | T3 | developer → critic | 进入评审 |
| critic MINOR/MAJOR=0 | T4 | critic → APPROVE | 终止 (success) |
| critic MAJOR ≥ 1 | T5 | critic → developer | 退回 (MAJOR 计数 +1) |
| critic 连续 2 MAJOR | T6 | developer → STOP | 终止 (StageRouter.should_stop=True) |

### 3.2 关键类

```python
from auto_engineering.loop.stage_router import StageRouter, StageDecision

router = StageRouter()
decision: StageDecision = router.next(engine_state)
# decision.next_stage: "architect" | "developer" | "critic" | "APPROVE" | "STOP"
# decision.should_stop: bool
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `next_stage` | str | 下一步 Stage 名（`APPROVE` / `STOP` 为终态）|
| `should_stop` | bool | 终态标志（成功或失败）|
| `reason` | str | 决策理由（用于日志）|

### 3.3 MAJOR 计数规则 (v5.0 §B3.2)

- `majors_in_a_row` — 连续 MAJOR 计数（达到 2 → should_stop=True）
- `total_majors` — 累计 MAJOR 计数（用于 metrics，不影响决策）
- 每次 critic verdict=MAJOR → `majors_in_a_row += 1`
- 每次 MINOR 或 PASS → `majors_in_a_row = 0`

---

## 4. GuardrailChain (v5.0 §B2)

**模块**: `auto_engineering.loop.guardrail`

### 4.1 5 内置 Guardrails

| ID | 类 | 触发时机 | 失败动作 |
|----|------|---------|----------|
| G1 | `RequirementValid` | pre / architect | block (空需求 / 超长) |
| G2 | `PlanExists` | post / architect | block (Plan 为空) |
| G3 | `GitDiffExists` | post / developer | block (无 diff) |
| G4 | `TestsPass` | post / developer | retry (测试失败) |
| G5 | `GitClean` | post / developer | retry (有未提交) |

### 4.2 GuardrailResult 数据类

```python
@dataclass
class GuardrailResult:
    guardrail_id: str           # "G1" / "G2" / ...
    action: str                 # "pass" | "retry" | "block" (v5.1 P0-1, 3 态)
    reason: str                 # 失败原因
    retry_count: int = 0        # 当前 Stage 已重试次数
```

> **v5.1 P0-1 YAGNI 变更**：`drop` 态已从公开契约删除（CrewAI 实际只 2 态, 4 态是过度设计). 
> `drop` 与 `retry` 语义重叠（皆为「重新执行当前 Stage」），保留 3 态 pass/block/retry 已覆盖所有场景.
> 旧 caller 传入 `drop` 时, `_handle_guardrail_result` 仍按 `retry` 处理（计数+1 + clear stage fields）并触发 `DeprecationWarning` 提示迁移. 
> 类型契约: `Action = Literal["pass", "block", "retry"]`.

### 4.3 3 态动作 (v5.1 §B2.4, P0-1)

| Action | 含义 | Orchestrator 处理 |
|--------|------|-------------------|
| `pass` | 通过 | 继续下一步 |
| `retry` | 重试 | 计数 +1，超限转 block |
| `block` | 阻塞 | 立即终止 Stage |
| ~~`drop`~~ | ~~丢弃~~ | **deprecated (v5.1 P0-1)** — 旧输入被 handler 当 retry 处理 + DeprecationWarning |

### 4.4 默认链

```python
from auto_engineering.loop.guardrail import GuardrailChain

chain = GuardrailChain.default()
# 等价于: G1 → G2 (architect 后) / G3 → G4 → G5 (developer 后)
result = chain.check(timing="pre", stage="architect", state=state)
```

---

## 5. 7 Gate 体系 (v5.0 §B6)

**模块**: `auto_engineering.gates`

### 5.1 Gate 列表

| Gate | 模块 | 适用 Stage | 不可用时降级 |
|------|------|-----------|-------------|
| `LintGate` | `gates/lint.py` | developer | skip (ruff 缺失) |
| `TypeCheckGate` | `gates/type_check.py` | developer | skip (mypy 缺失) |
| `TestGate` | `gates/test.py` | developer | skip (pytest 缺失) |
| `CoverageGate` | `gates/coverage.py` | developer | **永远 skip** (v5.0 §B6.4 决策) |
| `SafetyGate` | `gates/safety.py` | developer | skip (bandit 缺失) |
| `BuildGate` | `gates/build.py` | developer | skip (无构建) |
| `ContractGate` | `gates/contract.py` | developer | skip (无 manifest) |

### 5.2 Gate 基类

```python
class Gate(ABC):
    name: str
    def applies_to_stages(self) -> list[str]:
        """返回适用 Stage 列表。空 = 全部 Stage。"""
    async def run(self, state: EngineState) -> GateResult:
        """执行 Gate 检查。"""
```

### 5.3 GateVerdict

```python
class GateVerdict(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"     # 工具缺失 / 适用 Stage 不匹配
```

### 5.4 关键签名

```python
from auto_engineering.gates import DEFAULT_GATES, run_gates

verdicts: dict[str, bool] = await run_gates(
    state=state, stage="developer", gates=DEFAULT_GATES
)
# 返回: {"lint": True, "type_check": True, "test": False, ...}
```

---

## 6. Init-Loop 契约 (v5.0 §IL)

**模块**: `auto_engineering.loop.init_contract`

### 6.1 init-manifest.json Schema (schema_version=1)

```json
{
  "schema_version": 1,
  "project_type": "app-service",
  "package_manager": "uv",
  "test_runner": "pytest",
  "lint": {"tool": "ruff", "config": "ruff.toml"},
  "type_check": {"tool": "mypy", "config": "pyproject.toml"},
  "test_cmd": "pytest tests/ --no-cov --timeout=60",
  "build_cmd": null,
  "conventions": {
    "max_line_length": 100,
    "indent": "spaces",
    "indent_size": 4
  }
}
```

### 6.2 关键 API

```python
from auto_engineering.loop.init_contract import (
    INIT_MANIFEST_SCHEMA_VERSION,  # = 1
    load_init_manifest,            # → InitManifest | None
    validate_init_manifest,        # → list[str] (errors)
)

# 在 ae doctor 中自动调用
# 在 Gate 配置中替换硬编码 ruff/mypy/pytest
```

### 6.3 5 IL-AC 验收点

详见 `docs/EARS-v5.0.md` §IL-AC。

---

## 7. Checkpoint 持久化 (v5.0 §B11)

**模块**: `auto_engineering.loop.checkpoint`

### 7.1 持久化位置

- **v5.0 (新)**: `.ae-state/checkpoints.db` (SQLite, PRIMARY KEY = `checkpoint_id`)
- **v2.0 (旧)**: `.ae-state/v2-*.json` (JSON 文件, 已弃用, 自动迁移)
- **v1.0 (旧)**: `.ae-state/checkpoints/*.json` (v1.1, 已弃用)

### 7.2 关键类

```python
from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

store = SQLiteCheckpointStore(db_path=Path(".ae-state/checkpoints.db"))
store.save(envelope: CheckpointEnvelope)          # → checkpoint_id
envelope = store.load(checkpoint_id: str)         # → CheckpointEnvelope
store.list_all() -> list[dict]                    # → 元信息列表
store.delete(checkpoint_id: str) -> bool
```

### 7.3 CheckpointEnvelope 字段 (v5.0)

```python
@dataclass
class CheckpointEnvelope:
    checkpoint_id: str           # uuid
    thread_id: str               # 同一 dev-loop run
    round_index: int             # 0-based
    stage: str                   # 当前 Stage
    engine_state: EngineState    # 17 字段
    retry_counters: dict[str, int]  # 恢复时读 → 注入到 state
    created_at: datetime
    schema_version: int = 1
```

### 7.4 resume 语义 (v5.0 §B7.5)

- `Orchestrator.resume(checkpoint_id)` → `store.load()` → 重建 `LoopState` + `RoundHistory deque` + 注入 `retry_counters` → 进入 12 步主循环。

---

## 8. AgentRuntime 与 BaseAgent (v5.0 §B4)

**模块**: `auto_engineering.agents`

### 8.1 AgentRuntime

```python
from auto_engineering.agents import AgentRuntime, MockAgentRuntime

runtime = AgentRuntime.from_env()  # 真实 Anthropic SDK
# 或: runtime = MockAgentRuntime()  # 测试用

agent = runtime.get_agent("architect")  # → BaseAgent 实例
```

### 8.2 BaseAgent 三个子类

| Role | 模块 | Prompt |
|------|------|--------|
| `ArchitectAgent` | `agents/architect.py` | `prompts.ARCHITECT_PROMPT` (v5.0 §B4.1a) |
| `DeveloperAgent` | `agents/developer.py` | `prompts.DEVELOPER_PROMPT` (v5.0 §B4.2a) |
| `CriticAgent` | `agents/critic.py` | `prompts.CRITIC_PROMPT` (v5.0 §B4.3a) |

### 8.3 工具授权矩阵 (v5.0 §B4.4)

`agents/authz.py` 提供 9 工具 × 3 role = 27 组合的 `authz_check`：

| 工具 | architect | developer | critic |
|------|-----------|-----------|--------|
| `read_file` | ✓ | ✓ | ✓ |
| `write_file` | ✗ | ✓ | ✗ |
| `edit_file` | ✗ | ✓ | ✗ |
| `bash` | ✗ | ✓ | ✗ |
| `git_diff` | ✗ | ✓ | ✓ |
| `git_commit` | ✗ | ✓ | ✗ |
| `pytest` | ✗ | ✓ | ✗ |
| `ruff` | ✗ | ✓ | ✓ |
| `mypy` | ✗ | ✓ | ✓ |

---

## 9. 19 错误码 (v5.0 §B10.1a)

**模块**: `auto_engineering.errors.ErrorCode`

| 错误码 | 类别 | 抛出点 | 说明 |
|--------|------|--------|------|
| `CHECKPOINT_SAVE_FAILED` | IO | `CheckpointStore.save()` | SQLite 写失败 |
| `CHECKPOINT_LOAD_FAILED` | IO | `CheckpointStore.load()` | SQLite 读失败 |
| `LLM_TIMEOUT` | API | `AnthropicProvider.create_message` | 网络超时 |
| `LLM_MAX_RETRIES` | API | `AnthropicProvider.create_message` | 超 max_retries |
| `GUARDRAIL_BLOCKED` | GUARD | `Guardrail.check() action='block'` | 中止 Stage |
| `GUARDRAIL_RETRY` | GUARD | `Guardrail.check() action='retry'` | 重试 Stage |
| `STAGE_RETRY_EXCEEDED` | LOOP | 历史 (v1.0) | 保留 API |
| `MAX_TOOL_CALLS_EXCEEDED` | LOOP | `BaseAgent.execute()` | 工具循环超限 |
| `INVALID_AGENT_OUTPUT` | LOOP | `BaseAgent._parse_final_response()` | JSON 解析失败 |
| `GRAPH_RECURSION_LIMIT` | LOOP | 历史 (v1.0) | 保留 API |
| `TASK_NOT_FOUND` | TASK | 历史 (v1.0) | 保留 API |
| `TASK_CANCELLED` | TASK | `CancellationToken.check()` | Ctrl-C |
| `AGENT_REGISTRATION_ERROR` | TASK | `AgentRuntime` | agent_type 未注册 |
| `OUTPUT_DROPPED` | TASK | `Guardrail action='drop'` (deprecated v5.1 P0-1) | 静默丢弃 → 现按 retry 处理 |
| `CONFIG_MISSING_API_KEY` | CFG | `Settings.from_env()` | 缺 ANTHROPIC_API_KEY |
| `CONFIG_INVALID_VALUE` | CFG | `Settings` 校验 | 非法配置值 |
| `BUDGET_EXCEEDED` | BUDGET | `TokenTracker.add()` | 超 max_tokens |
| `CONTRACT_REJECTED` | BIZ | `BaseAgent.contract_gate` | Gate 拒绝 |
| `LLM_NETWORK_ERROR` | API | 预留 | 网络断开 |

> 19 错误码 = 13 实际抛出 + 6 预留（LLM 系列: `LLM_NETWORK_ERROR` / `LLM_INVALID_RESPONSE` / `LLM_AUTH_ERROR` / `LLM_RATE_LIMIT` / `LLM_UNKNOWN_ERROR` 5 + `STAGE_RETRY_EXCEEDED` / `GRAPH_RECURSION_LIMIT` / `TASK_NOT_FOUND` 3 个 v1.0 保留 API）。详见 `tests/test_error_codes.py`。

### 9.1 AEError 异常族

```python
from auto_engineering.errors import AEError, ErrorCode, GuardrailBlockedError

try:
    orch.run()
except AEError as e:
    print(f"[{e.code.value}] {e.message}")
    # e.original_error — 底层异常（若有）
```

---

## 10. 模块清单 (v5.0 Phase 01-10 落地)

| 模块路径 | Phase | 用途 |
|---------|-------|------|
| `auto_engineering/loop/state.py` | 01 | EngineState 17 字段 dataclass |
| `auto_engineering/loop/stage_router.py` | 01 | StageDecision + StageRouter T1-T6 |
| `auto_engineering/loop/guardrail.py` | 02 | 5 Guardrails + Chain |
| `auto_engineering/loop/plan.py` | 03 | Plan.get_tasks_by_stage + parallelism_groups |
| `auto_engineering/loop/task_factory.py` | 03 | _tasks_from_batch_plan |
| `auto_engineering/loop/orchestrator.py` | 04 | Orchestrator 12 步主循环 + resume |
| `auto_engineering/loop/round.py` | 05 | run_round + _topological_layers |
| `auto_engineering/gates/{base,lint,type_check,test,coverage,safety,build,contract}.py` | 05+06 | 7 Gate 实现 |
| `auto_engineering/agents/authz.py` | 07 | 9×3 工具授权矩阵 |
| `auto_engineering/agents/prompts.py` | 07 | 3 Agent prompt 模板 |
| `auto_engineering/cli.py` | 07+08 | 11 子命令 + JSON 契约 |
| `auto_engineering/loop/init_contract.py` | 08 | INIT_MANIFEST_SCHEMA_VERSION + load + validate |
| `auto_engineering/errors.py` | 10 | ErrorCode 19 错误码 + AEError |
| `auto_engineering/loop/checkpoint.py` | 04 | SQLiteCheckpointStore |
| `auto_engineering/loop/convergence.py` | 03 | 4 级收敛判定 (gate PASS / no-gates / max-round / stop) |
| `auto_engineering/loop/semantic_evaluator.py` | 04 | LLM 语义评估（不可用时降为 3 级）|

---

## 11. 引用

- `design/v5.0-Design-Loop.md` — v5.0 设计基线
- `design/BEACON.md` 决策 #28 (v5.0 P0-FINAL)
- `_scratch/v5.0-refactor-plan.md` 模块 12 — 文档 + EARS
- `docs/PLUGIN-USAGE.md` — Plugin 安装/命令
- `docs/production-deployment.md` — 部署 + 降级
- `docs/EARS-v5.0.md` — 15 AC + 5 IL-AC 验收表

---

_v1.0 / v2.0 / v2.3 章节已删除。归档版本见 `_scratch/his_bak/api-reference.md` (v2.2 FINAL, 79 行)。_
