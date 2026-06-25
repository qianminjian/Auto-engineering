# Auto-Engineering v1.0 — Loop 子系统开发计划

> 基线设计：`design/v1.0-LOOP.md`（v3.0，四轮审计后）
> 创建日期：2026-06-24

---

## 总览

| Phase | 名称 | 优先级 | 文件数 | 代码行数 | 依赖 |
|:-----:|------|:-----:|:-----:|:------:|------|
| 1 | 核心引擎 | **P0** | 5 | ~600 | 无 |
| 2 | Runtime + Guardrail | **P0** | 5 | ~430 | Phase 1 |
| 3 | Agent + 工具 | P1 | 9 | ~1100 | Phase 2 |
| 4 | CLI + 可观测性 | P1 | 3 | ~400 | Phase 3 |

**总计：22 文件，~2,530 行 Python**

---

## Phase 1：核心引擎（P0）

> 目标：LoopEngine 可在 MockRuntime 下跑通完整的 architect → developer → critic → APPROVE 路径
> 预估：~3h

### 文件清单

| # | 文件 | 内容 | 行数 | 参考源码 |
|---|------|------|:---:|---------|
| 1 | `engine/state.py` | `LoopState` dataclass + `to_dict`/`from_dict`/`get_channels`/`set_channels` | 60 | — |
| 2 | `engine/checkpoint.py` | `CheckpointStore`（连接管理/WAL/CRUD）+ `Checkpoint` dataclass + SQL schema | 180 | LangGraph `checkpoint-sqlite/__init__.py:85-120` |
| 3 | `engine/graph.py` | `Stage` dataclass + `StageGraph`（START sentinel/builder/next_stage）+ `build_dev_loop_graph()` | 150 | LangGraph `state.py:915-1017` |
| 4 | `engine/loop.py` | `LoopEngine`（`__init__`/`_init_checkpoint`/`run`/`tick`/`after_tick`/`resume`）+ `StageResult`/`LoopResult`/异常类 | 170 | LangGraph `_loop.py:592-712` |
| 5 | `engine/messages.py` | `Send` dataclass（v2.0 预留骨架） | 40 | — |

### 依赖链

```
state.py ──► checkpoint.py ──► graph.py ──► loop.py
                                                     │
                                        messages.py ─┘ (独立)
```

### 验证标准

- [ ] `python -c "from auto_engineering.engine import LoopEngine, StageGraph, LoopState"` 通过
- [ ] `test_loop_state_serialization_roundtrip` — dataclass ↔ dict 双向序列化
- [ ] `test_checkpoint_store_save_load` — SQLite CRUD 正确
- [ ] `test_full_loop_approve_path` — architect → developer → critic → APPROVE → done 全路径
- [ ] `test_loop_hits_step_limit` — max_steps 上限生效
- [ ] `test_checkpoint_resume` — 中断恢复正确

### 前置条件

- 项目 `pyproject.toml` 已配置（已完成）
- `tests/conftest.py` 含 `MockRuntime` + pytest-asyncio 配置
- `ANTHROPIC_API_KEY` 环境变量不需设置（Phase 1 不调用 LLM）

---

## Phase 2：Runtime + Guardrail（P0）

> 目标：真实 AgentRuntime 可注册 Agent、执行 Stage、Guardrail 中间件触发失败
> 预估：~3h

### 文件清单

| # | 文件 | 内容 | 行数 | 参考源码 |
|---|------|------|:---:|---------|
| 6 | `errors.py` | `ErrorCode` Enum + `AEError` + `GuardrailBlockedError`/`GuardrailRetrySignal`/`OutputDropped` | 50 | LangGraph `errors.py` |
| 7 | `runtime/task.py` | `Task` + `TaskResult` dataclass | 60 | CrewAI `task.py:114-213` |
| 8 | `runtime/context.py` | `TaskContext` dataclass | 40 | AutoGen `MessageContext` |
| 9 | `runtime/runtime.py` | `AgentRuntime`（register/_get_or_create_agent/execute） | 150 | AutoGen `_single_threaded_agent_runtime.py:249-270, 976-986` |
| 10 | `gates/guardrail.py` | `GuardrailResult` + `DropOutput` + `GuardrailHandler` Protocol + `GuardrailChain` | 80 | AutoGen `_intervention.py:20-83` + CrewAI `guardrail.py:60-83` |
| 11 | `gates/builtin.py` | 5 个内置 Guardrail（Requirement/PlanExists/GitClean/TestsPass/GitDiffExists） | 100 | — |

### 验证标准

- [ ] Mock Agent + 真实 GuardrailChain，验证 pre-guardrail block 正确抛出 `GuardrailBlockedError`
- [ ] Mock Agent + 真实 GuardrailChain，验证 post-guardrail retry 正确触发 `GuardrailRetrySignal`
- [ ] Mock Agent + 真实 GuardrailChain，验证 drop 语义（`OutputDropped` → `continue`）
- [ ] 真实 `LoopEngine.run()` + 真实 `AgentRuntime` + Mock Agent → 3 Stage 全流程通过

### 新增前置条件

- Phase 1 全部通过

---

## Phase 3：Agent + 工具（P1）

> 目标：3 个 Agent 可通过 Claude API 完成需求分析 → TDD 开发 → 代码审查的全流程
> 预估：~6h

### 文件清单

| # | 文件 | 内容 | 行数 | 参考源码 |
|---|------|------|:---:|---------|
| 12 | `tools/base.py` | `BaseTool` + `ToolResult` | 80 | AutoGen `_base.py` Tool Protocol |
| 13 | `tools/registry.py` | `ToolRegistry` | 40 | — |
| 14 | `tools/file_tools.py` | `ReadFileTool`/`WriteFileTool`/`EditFileTool` | 150 | — |
| 15 | `tools/bash_tools.py` | `RunBashTool` | 80 | — |
| 16 | `tools/git_tools.py` | `GitCommitTool`/`GitDiffTool`/`GitStatusTool` | 100 | — |
| 17 | `tools/test_tools.py` | `RunTestsTool` | 50 | — |
| 18 | `llm/anthropic_provider.py` | `AnthropicProvider` + `LLMResponse` + `LLMUsage` | 60 | Anthropic SDK |
| 19 | `agents/parser.py` | `parse_agent_output()` 双层防御 | 50 | CrewAI `converter.py:24-80` |
| 20 | `agents/base.py` | `BaseAgent` dataclass + `execute()`（LLM 调用/工具循环/输出解析） | 200 | AutoGen `_base_agent.py:60-254` |
| 21 | `agents/architect.py` | `ArchitectAgent(BaseAgent)` + `ARCHITECT_SYSTEM_PROMPT` | 150 | — |
| 22 | `agents/developer.py` | `DeveloperAgent(BaseAgent)` + `DEVELOPER_SYSTEM_PROMPT` | 150 | — |
| 23 | `agents/critic.py` | `CriticAgent(BaseAgent)` + `CRITIC_SYSTEM_PROMPT` | 100 | — |

### 验证标准

- [ ] 每个 Agent 单元测试：mock LLM 返回预设 JSON，验证 `_parse_output` → `TaskResult.values` 映射正确
- [ ] 每个工具单元测试：验证 `execute()` 输入/输出/错误处理
- [ ] `AnthropicProvider.create_message()` 集成测试：发真实 API 调用，验证 `LLMResponse` 字段完整
- [ ] 工具调用循环集成测试：mock LLM 返回 tool_use → 验证工具执行 → 再次调用 LLM

### 新增前置条件

- Phase 2 全部通过
- `ANTHROPIC_API_KEY` 环境变量已设置

---

## Phase 4：CLI + 可观测性（P1）

> 目标：`ae dev-loop "需求"` 端到端可用，含进度输出、token 追踪、dry-run 模式
> 预估：~3h

### 文件清单

| # | 文件 | 内容 | 行数 |
|---|------|------|:---:|
| 24 | `engine/retry.py` | `RetryPolicy` + `run_with_retry()` | 50 |
| 25 | `engine/cancellation.py` | `CancellationToken` | 30 |
| 26 | `engine/logging.py` | 结构化日志 + token 追踪 | 150 |
| 27 | `config/settings.py` | `Settings` dataclass（从环境变量加载 + 校验） | 50 |
| 28 | `cli.py` | Click 命令：`dev-loop`/`status`/`checkpoint list`/`checkpoint resume` + `--dry-run`/`--verbose`/`--max-steps`/`--max-tokens` | 200 |

### 验证标准

- [ ] `ae dev-loop "简单需求"` 端到端通过（真实 LLM 调用）
- [ ] `ae dev-loop --dry-run "需求"` 只输出计划不写文件
- [ ] `ae dev-loop --verbose "需求"` 输出完整 LLM 交互日志
- [ ] `ae dev-loop --max-steps 3 "需求"` 步数上限生效
- [ ] `ae status` 显示当前 checkpoint 状态
- [ ] `ae checkpoint list` 列出所有 checkpoint
- [ ] `ae checkpoint resume <id>` 从中断恢复并继续
- [ ] Ctrl-C 中断后 checkpoint 已保存，可 resume

### 新增前置条件

- Phase 3 全部通过

---

## 开发顺序与依赖图

```
Phase 1 ──────────────────────────────────────────────────────────┐
  state.py ──► checkpoint.py ──► graph.py ──► loop.py             │
                                                  │               │
                                     messages.py ─┘               │
                                                                  │
Phase 2 ──────────────────────────────────────────────────────────┤
  errors.py ──► task.py ──► context.py ──► runtime.py             │
                                               │                  │
                          guardrail.py ──► builtin.py             │
                                                                  │
Phase 3 ──────────────────────────────────────────────────────────┤
  tools/base.py ──► tools/registry.py ──► tools/4 files           │
  llm/anthropic_provider.py                                       │
  agents/parser.py ──► agents/base.py ──► agents/3 agents         │
                                                                  │
Phase 4 ──────────────────────────────────────────────────────────┤
  engine/retry.py + engine/cancellation.py                        │
  engine/logging.py + config/settings.py ──► cli.py               │
```

---

## 参考源码映射

| 开发文件 | 参考源码 | 学什么 |
|---------|---------|--------|
| `engine/loop.py` | LangGraph `_loop.py:592-712` | tick 检查顺序 + after_tick 持久化 |
| `engine/graph.py` | LangGraph `state.py:915-1017` | builder 链式 API + 条件边 |
| `engine/checkpoint.py` | LangGraph `checkpoint-sqlite/__init__.py:85-120` | 表结构 + serde + thread lock |
| `runtime/runtime.py` | AutoGen `_single_threaded_agent_runtime.py:249-270, 976-986` | 工厂延迟实例化 + 类型检查 |
| `gates/guardrail.py` | AutoGen `_intervention.py:20-83` + CrewAI `guardrail.py:60-83` | Protocol + DropMessage + GuardrailResult |
| `agents/base.py` | AutoGen `_base_agent.py:60-254` | agent 生命周期 |
| `runtime/task.py` | CrewAI `task.py:114-213` | 富 Task 字段 + output_schema |
| `agents/parser.py` | CrewAI `utilities/converter.py:24-80` | JSON 正则提取 |
