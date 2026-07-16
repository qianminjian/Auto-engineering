# Auto-Engineering 入口路径说明

> **Version**: 5.6.0 | **Last updated**: 2026-07-16

四条路径的适用场景、代码调用链、环境要求。

## 1. Plugin slash command (`/ae:dev-loop`)

**适用场景**: Claude Code 内日常使用。用户输入 `/ae:dev-loop "实现登录功能"`，Claude Code Agent 按 `commands/dev-loop.md` 协议调度。

**调用链**:
```
/ae:dev-loop → commands/dev-loop.md → Agent tool spawn:
  1. Plan agent (architect) → batch_plan
  2. Claude Code agent (developer) → TDD + Gates
  3. code-reviewer agent (critic) → findings
  4. Design Doc Sync → convergence check
```

**环境要求**: Claude Code Plugin 安装（`.claude-plugin/`），无需手动 `pip install`。Agent 复用当前会话的 ANTHROPIC_AUTH_TOKEN。

**代码路径**: `.claude-plugin/commands/dev-loop.md`（Agent 协议），不经过 Python Engine。

---

## 2. CLI `ae dev-loop` — v5.6 Tick 协议（主引擎）

**适用场景**: Tick-Based Discrete Invocation。Python 每次 tick 独立进程，读 SQLite → 验证 → 输出 action JSON → 退出。Agent 通过反复调用 `--tick` 驱动循环。

**调用链**:
```
ae dev-loop --init              → cli/dev_loop.py → tick_orchestrator.py
ae dev-loop --tick --result R   → 提交本轮 result, 推进 tick
ae dev-loop --status --format json → 当前进度
ae dev-loop --resume            → 从 checkpoint 恢复
```

**环境要求**:
- `uv sync` 安装依赖
- `ANTHROPIC_API_KEY` 环境变量（或 Plugin 模式的 ANTHROPIC_AUTH_TOKEN）
- Python 3.11+

**代码路径**: `auto_engineering/cli/dev_loop.py` → `loop/tick_orchestrator.py`

---

## 3. CLI `ae dev-loop` — v5.5 连续循环（legacy，共存）

**适用场景**: 裸参数路径 `ae dev-loop "需求"`，连续 while 循环直调 LLM。与 v5.6 Tick 引擎共存，不复用。

**代码路径**: `auto_engineering/cli/dev_loop.py` → `loop/orchestrator.py`

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
ae gate-check --all     # 全量 7 道
```

**代码路径**: `auto_engineering/cli/gate_check.py` → `gates/`

---

## 6. 环境诊断 (`ae doctor`)

```bash
ae doctor   # 检查 Python/uv/git/sqlite3/API_KEY/.ae-state
```

---

## 7. PrismScan (`ae prismscan`)

```bash
ae prismscan discover-extract     # discover + extract → action JSON
ae prismscan check-result <file>  # 校验 AnalysisResult JSON
```

---

## 路径选择速查

| 场景 | 使用 |
|------|------|
| 日常开发（Claude Code 内） | `/ae:dev-loop` |
| Tick 循环（离散调用） | `ae dev-loop --init → --tick → --result` |
| 连续循环（legacy） | `ae dev-loop "需求"` |
| 单独调 Agent | `ae agent <role>` |
| 手动质量检查 | `ae gate-check --all` |
| 环境诊断 | `ae doctor` |
| 代码库反向工程 | `ae prismscan discover-extract` |
