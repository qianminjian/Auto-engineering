# Auto-Engineering 入口路径说明

三条路径的适用场景、代码调用链、环境要求。

## 1. Plugin slash command (`/ae:dev-loop`)

**适用场景**: Claude Code 内日常使用。用户输入 `/ae:dev-loop "实现登录功能"`，Claude Code Agent 按 `commands/dev-loop.md` 协议调度。

**调用链**:
```
/ae:dev-loop → commands/dev-loop.md → Agent tool spawn:
  1. Plan agent (architect) → batch_plan
  2. Claude Code agent (developer) → TDD + Gates
  3. code-reviewer agent (critic) → findings
```

**环境要求**: Claude Code Plugin 安装（`.claude-plugin/`），无需手动 `pip install`。Agent 复用当前会话的 ANTHROPIC_AUTH_TOKEN。

**代码路径**: `.claude-plugin/commands/dev-loop.md`（Agent 协议），不经过 Python Engine。

---

## 2. CLI `ae dev-loop`（调试入口）

**适用场景**: 开发 Auto-Engineering 本身时调试 Python Engine。不需要在 Claude Code 内运行。

**调用链**:
```
ae dev-loop → cli/dev_loop.py:dev_loop_command()
  → Orchestrator(requirement, tasks, executor, config)
  → Orchestrator.run() → tick/after_tick 主循环
  → AgentRuntime → ae agent architect/developer/critic
```

**环境要求**:
- `pip install auto-engineering`（或 `uv run ae`）
- `ANTHROPIC_API_KEY` 环境变量
- Python 3.11+

**限制**: 子进程方式运行，无法获取 Claude Code agent 的 ANTHROPIC_AUTH_TOKEN。仅用于 Engine 层调试。

**代码路径**: `auto_engineering/cli/dev_loop.py` → `loop/orchestrator.py`

---

## 3. Agent Tool 直接执行（commands/dev-loop.md）

**适用场景**: Claude Code Agent 解释 `commands/dev-loop.md` 后直接 spawn Plan agent + code-reviewer agent。这是生产路径。

**调用链**: 见 §1。

**代码路径**: `auto_engineering/loop/orchestrator_agent.py`（`_orchestrator_run_agent`）

---

## 4. 单 Agent 调用 (`ae agent`)

**适用场景**: 单独调用某个角色 Agent。

```bash
ae agent architect "设计用户登录模块"
ae agent developer "实现 JWT 认证"
ae agent critic "审查 auth.py"
```

**代码路径**: `auto_engineering/cli/agent.py` → `agents/base.py:BaseAgent.execute()`

---

## 5. Gate 检查 (`ae gate-check`)

**适用场景**: 手动检查代码质量。

```bash
ae gate-check --quick   # safety + lint + type_check
ae gate-check --all     # 全量 5 道
```

**代码路径**: `auto_engineering/cli/gate_check.py` → `gates/`

---

## 6. 环境诊断 (`ae doctor`)

```bash
ae doctor   # 检查 Python/uv/git/sqlite3/API_KEY/.ae-state
```

---

## 路径选择速查

| 场景 | 使用 |
|------|------|
| 日常开发（Claude Code 内） | `/ae:dev-loop` |
| 调试 Python Engine | `ae dev-loop` |
| 单独调 Agent | `ae agent <role>` |
| 手动质量检查 | `ae gate-check --all` |
| 环境诊断 | `ae doctor` |
