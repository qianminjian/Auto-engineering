# dev-loop 子系统后续待办

> 创建：2026-06-24 | 来源：本会话 Phase 3 C3c 中断
> 关联：`design/BEACON.md` 当前状态 / `design/LOOP-DEVELOPMENT-PLAN.md` Phase 3 详情

---

## 背景

按用户 2026-06-24 指令「续做 dev-loop Plan B.02 收尾 + 后续 Phase（严格 TDD 每 commit 一环）」启动 Phase 3 工作。Phase 1（核心引擎）/ Phase 2（Runtime + Guardrail）已完成或由 parallel work 落地。Phase 3（Agent + 工具）已 commit 4 个 cycle：

- C1 AnthropicProvider + LLMUsage/LLMResponse（`d424bed`）
- C2 agent output parser 双层防御（`2116391`）
- C3a BaseTool/ToolResult API 契约测试（`7502ae1`）
- C3b ToolRegistry 注册表（`b582961`）

---

## 当前阻塞：C3c BaseAgent 测试 API 不对齐

**问题**：C3c 写的 RED 测试 `tests/test_base_agent.py` 使用了错误的 API 形状：

| 测试假设 | 实际 `runtime.task.TaskResult` 字段 |
|----------|-------------------------------------|
| `result.content` | `result.raw_response` |
| `result.parsed` | `result.values`（dict） |
| `result.usage` | 无独立字段（usage 在 raw_response.usage） |
| `result.error` | 无 |

`auto_engineering/runtime/task.py:TaskResult` 已存在（parallel work 落地），字段：
```python
@dataclass
class TaskResult:
    task_id: str
    values: dict[str, Any]
    raw_response: Any = None
    tool_calls: list[dict] = field(default_factory=list)
    agent_type: str = ""
```

**修复路径**（严格 TDD）：

1. 改写 `tests/test_base_agent.py` 对齐 TaskResult API：
   - `result.values` 替代 `result.parsed`
   - `result.raw_response` 替代 `result.content`
   - `result.tool_calls` 记录工具调用
   - 添加 `result.task_id` 验证
2. 重跑确认 RED → 写 BaseAgent GREEN → commit

---

## 后续 Phase 3 工作清单（按依赖顺序）

- **C3c** BaseAgent（~200 行 per plan）— **阻塞中**，待 API 对齐
  - execute() 无工具循环版
  - execute() 工具循环版（tool_use → execute → 续调 LLM）
  - output_schema 集成 parser
- **C4** 4 个工具 TDD（per plan 文件 14-17）— 待 C3c 完成
  - ReadFileTool / WriteFileTool / EditFileTool（file_tools.py）
  - RunBashTool（bash_tools.py）
  - GitCommitTool / GitDiffTool / GitStatusTool（git_tools.py）
  - RunTestsTool（test_tools.py）
- **C5** 3 个 Agent TDD（per plan 文件 21-23）— 待 C4 完成
  - ArchitectAgent + ARCHITECT_SYSTEM_PROMPT
  - DeveloperAgent + DEVELOPER_SYSTEM_PROMPT
  - CriticAgent + CRITIC_SYSTEM_PROMPT

---

## 设计参考

- `design/LOOP-DEVELOPMENT-PLAN.md` Phase 3 文件 12-23（行数估算 + 依赖图）
- `design/v1.0-LOOP.md` v3.0 设计基线（含 §十一 bug 修复记录）
- `auto_engineering/runtime/task.py` TaskResult 定义
- `auto_engineering/llm/anthropic_provider.py` LLM API 形状

---

## 建议执行顺序

1. C3c 改写测试对齐 TaskResult → RED 确认 → GREEN 实现 BaseAgent → commit
2. C4 4 个工具按 file → bash → git → test 顺序，每个 1 个 TDD commit
3. C5 3 个 Agent 按 architect → developer → critic 顺序，每个 1 个 TDD commit

每个 commit 遵循 strict TDD（Red → Green → Refactor 每 commit 一环）。

---

## 已知偏差（Phase 3 工作期间发现）

- 测试 `tests/test_base_agent.py` 假设的 API 与 `runtime.task.TaskResult` 不一致 — 需要对齐