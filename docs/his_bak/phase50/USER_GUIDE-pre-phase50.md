# Auto-Engineering v5.6 用户指南（Phase 50 重写前）

> **Version**: 5.6.0 | **Status**: Production-ready | **Last updated**: 2026-07-19
> 决策依据: `design/BEACON.md` 决策 #28, #41, #53

## 当前入口（2026-07-27）

本项目当前只有一套 Host-neutral Tick 核心，Claude Code 与 Codex 仅入口不同：

| 平台 | 用户入口 |
|------|---------|
| Claude Code | `/ae:dev-loop "需求"` |
| Codex | `$auto-engineering`，随后描述需求 |

```bash
scripts/ae-run doctor
scripts/ae-run dev-loop --init "需求"
```

第二条命令只产生首个 action JSON；宿主 Agent 必须按 action 执行，并通过
`scripts/ae-run dev-loop --tick --result <result.json>` 继续推进。`ae agent`、
`ae gate-check`、`ae checkpoint`、`ae progress`、裸参数循环和 Standalone 均不是
当前入口。本文后续若出现这些名称，属于历史说明，不能作为当前操作指引。

Auto-Engineering v5.6 是 Host-neutral Tick-Based Discrete Invocation Loop Engine，
当前通过 Claude Code 与 Codex 两个适配入口分发。Python 引擎永不调 LLM——Agent
通过文件桥接反复调用 `--tick` 驱动循环。

---

## 1. 产品概述

Auto-Engineering 是**平台无关核心 + 宿主适配器**形态的 Loop Engineering
脚手架，面向团队内部分发（5-20 用户本地安装）。

在 Claude Code 输入 `/ae:dev-loop "需求描述"`，或在 Codex 调用
`$auto-engineering`，宿主适配器都会调度同一 Python Loop Engine。

核心特性：

- **Tick-Based 离散调用**（v5.6 Tick 协议，文件桥接，Python 每次 tick 独立进程）
- **5 层验证管道**（architect → developer → critic → component_verifier → system_deep_audit）
- **10 Guardrail 守门**（3 态: pass/block/retry，含 REDGuardrail/FreshGuardrail/RegressionGuardrail/PIIGuardrail）
- **7 道 Gate 质量门**（safety / lint / type_check / audit / contract / test / build）
- **SQLite checkpoint 恢复**（中断后不丢进度）
- **LEAF/PLATE/FULL 自动验证深度裁剪**
- **Init-Loop 接口契约**（消费 Init 项目产出的 init-manifest.json）
- **Host Adapter**（Claude Code Command + Codex Skill 复用同一核心）

---

## 2. 安装

### 2.1 系统要求

| 组件 | 最低版本 | 检查命令 |
|------|---------|----------|
| Python | 3.12+ | `python3 --version` |
| uv | 0.1.0+ | `uv --version` |
| git | 2.30+ | `git --version` |
| sqlite3 | 3.35+ | `sqlite3 --version` |
| Claude Code | 1.0.0+ | `claude --version` |
| 操作系统 | macOS 12+ / Linux / WSL2 | — |
| 物理内存 | 16 GB+ | `free -h` / 活动监视器 |
| 磁盘 | 2 GB+ (含 .venv) | `df -h .` |

> **16G 内存约束**：本机 16 GB 物理内存时，pytest + coverage 叠加 ~2x → 必须 `--no-cov`。详见 `.claude/rules/pytest-memory-management.md`。

### 2.2 Marketplace 安装（推荐）

在 Claude Code / Codex / CodeBuddy 会话中输入：

```
/plugin marketplace add qianminjian/Auto-engineering
/plugin install auto-engineering@qianminjian --scope user
```

Codex 等效命令：
```
codex plugin marketplace add qianminjian/Auto-engineering
codex plugin install auto-engineering
```

平台自动 `git clone` 仓库到插件缓存目录，加载所有 commands/hooks/skills。安装完成后**重启对应平台**即可使用。

### 2.3 手动安装（开发用）

```bash
git clone https://github.com/qianminjian/Auto-engineering.git
cd Auto-engineering

# Claude Code — symlink .claude-plugin 到 plugins 目录
ln -sfn "$(pwd)" ~/.claude/plugins/auto-engineering

# 安装 Python 环境
uv sync
```

### 2.4 拷贝安装（目标项目）

```bash
cd ~/path/to/your-project
cp -r /path/to/auto-engineering/.claude-plugin ./
cp -r /path/to/auto-engineering/.claude ./your-project/.claude
uv sync
.venv/bin/ae doctor              # 必须全 ok
# 重启 Claude Code
```

### 2.5 验证安装

在平台中输入 `/help`，应看到 7 个 `/ae:*` 命令：

- `/ae:dev-loop`（Claude Code/CodeBuddy）或 `//ae:dev-loop`（Codex）
- `/ae:status`
- `/ae:checkpoint`
- `/ae:project-tdd`
- `/ae:project-worktree`
- `/ae:project-agent`
- `/ae:project-ci`

运行 `ae doctor` 验证 Python 引擎环境。

### 2.6 命令语法差异

| 平台 | 命令格式 | 备注 |
|------|---------|------|
| Claude Code | `/ae:dev-loop "需求"` | slash command 标准语法 |
| Codex | `//ae:dev-loop "需求"` | 双斜杠 skill 调用 |
| CodeBuddy | `/ae:dev-loop "需求"` | 与 Claude Code 相同（兼容 `plugin.json`） |

### 2.7 升级与回滚

**升级**：
```bash
cp -r .claude-plugin .claude-plugin.bak.$(date +%Y%m%d)
cp -r /path/to/auto-engineering-v5.x/.claude-plugin ./
uv sync
.venv/bin/ae doctor
bash ae-plugin-acceptance-test.sh
# 重启 Claude Code
```

**回滚**：
```bash
rm -rf .claude-plugin
mv .claude-plugin.bak.<date> .claude-plugin
git checkout pyproject.toml uv.lock
uv sync
# 重启 Claude Code
```

### 2.8 卸载

```
/plugin uninstall auto-engineering
```

或手动：
```bash
rm -rf .claude-plugin/
rm -rf .venv .ae-state/
```

---

## 3. 入口路径

Auto-Engineering 提供 6 条入口路径，适用不同场景。

### 3.1 Plugin slash command（`/ae:dev-loop`）

**适用场景**：Claude Code 内日常使用。

**调用链**：
```
/ae:dev-loop → commands/dev-loop.md → Agent tool spawn:
  1. Plan agent (architect) → batch_plan
  2. Claude Code agent (developer) → TDD + Gates
  3. code-reviewer agent (critic) → findings
  4. Design Doc Sync → convergence check
```

**环境要求**：Claude Code Plugin 安装（`.claude-plugin/`），无需手动 `pip install`。Agent 复用当前会话的 ANTHROPIC_AUTH_TOKEN。

### 3.2 CLI `ae dev-loop` — v5.6 Tick 协议（主引擎）

**适用场景**：Tick-Based Discrete Invocation。Python 每次 tick 独立进程，读 SQLite → 验证 → 输出 action JSON → 退出。

**调用链**：
```
ae dev-loop --init              → cli/dev_loop.py → tick_orchestrator.py
ae dev-loop --tick --result R   → 提交本轮 result, 推进 tick
ae dev-loop --status --format json → 当前进度
ae dev-loop --resume            → 从 checkpoint 恢复
```

**环境要求**：`uv sync` 安装依赖，`ANTHROPIC_API_KEY` 环境变量（或 Plugin 模式的 ANTHROPIC_AUTH_TOKEN），Python 3.12+。

**代码路径**：`auto_engineering/cli/dev_loop.py` → `loop/tick_orchestrator.py`

### 3.3 CLI `ae dev-loop` — v5.5 连续循环（legacy，退役过渡期）

**适用场景**：裸参数路径 `ae dev-loop "需求"`，连续 while 循环直调 LLM。

**状态**：2026-07-19 启动 30 天退役过渡期，`--standalone` 替代，2026-08-18 物理删除。

**代码路径**：`auto_engineering/cli/dev_loop.py` → `loop/orchestrator.py`

### 3.4 单 Agent 调用（`ae agent`）

```bash
ae agent architect "设计用户登录模块"
ae agent developer "实现 JWT 认证"
ae agent critic "审查 auth.py"
```

**代码路径**：`auto_engineering/cli/agent.py` → `agents/base.py:BaseAgent.execute()`

### 3.5 Gate 检查（`ae gate-check`）

```bash
ae gate-check --quick   # safety + lint + type_check
ae gate-check --all     # 全量 7 道
```

**代码路径**：`auto_engineering/cli/gate_check.py` → `gates/`

### 3.6 环境诊断（`ae doctor`）

```bash
ae doctor   # 检查 Python/uv/git/sqlite3/API_KEY/.ae-state/init-manifest
```

### 3.7 路径选择速查

| 场景 | 使用 |
|------|------|
| 日常开发（Claude Code 内） | `/ae:dev-loop` |
| Tick 循环（离散调用） | `ae dev-loop --init → --tick → --result` |
| 连续循环（legacy） | `ae dev-loop "需求"` |
| 单独调 Agent | `ae agent <role>` |
| 手动质量检查 | `ae gate-check --all` |
| 环境诊断 | `ae doctor` |

---

## 4. 命令参考

### 4.1 Slash Commands（Plugin 模式）

| Command | 作用 | 典型用法 |
|---------|------|---------|
| `/ae:dev-loop` | 启动 3 Stage Agent 循环 | `/ae:dev-loop "实现 JWT 登录" --max-rounds 20` |
| `/ae:dev-loop --init` | 初始化 tick 循环 | `/ae:dev-loop --init` |
| `/ae:dev-loop --tick` | 提交 tick result | `/ae:dev-loop --tick --result result.json` |
| `/ae:dev-loop --resume` | 从 checkpoint 恢复 | `/ae:dev-loop --resume` |
| `/ae:status` | 查看当前 loop 进度 | `/ae:status` 或 `/ae:status --json` 或 `/ae:status --verbose` |
| `/ae:checkpoint list` | 列出所有 checkpoint | `/ae:checkpoint list` 或 `/ae:checkpoint list --round 3` |
| `/ae:checkpoint show` | 查看 checkpoint 详情 | `/ae:checkpoint show --id ckpt-001` |
| `/ae:checkpoint resume` | 从 checkpoint 恢复 | `/ae:checkpoint resume --id ckpt-001` |
| `/ae:checkpoint delete` | 删除 checkpoint | `/ae:checkpoint delete --id ckpt-001` |
| `/ae:project-tdd` | TDD 快速循环 | `/ae:project-tdd "validate email format"` |
| `/ae:project-worktree` | 创建隔离 worktree | `/ae:project-worktree feat/oauth-login` |
| `/ae:project-agent` | 单 Agent 调用 | `/ae:project-agent architect "design REST API"` |
| `/ae:project-ci` | 跑全量 CI | `/ae:project-ci` 或 `/ae:project-ci --quick` 或 `/ae:project-ci --fix` |

### 4.2 Engine CLI 命令

```bash
# 环境验证
ae doctor                              # 7 项检查 (Python/uv/git/sqlite3/API_KEY/.ae-state/init-manifest)

# Gate 检查
ae gate-check --quick                  # 3 道核心 Gate (safety+lint+type_check)
ae gate-check --all                    # 全部 7 道 Gate

# 单 Agent 调用
ae agent architect "分析 OAuth2 流程"
ae agent developer "实现用户模型"
ae agent critic "审查 PR #42"

# Loop 状态
ae status --format json                # JSON 7 字段输出
ae status --verbose                    # 含 recent_history × 5

# Checkpoint 管理
ae checkpoint list
ae checkpoint show <id>
ae checkpoint resume <id>
ae checkpoint delete <id>

# 进度显示
ae progress                            # 显示 tick 循环进度树

# v5.5 legacy
ae dev-loop "需求"                     # 裸参数路径（退役过渡期）
```

### 4.3 Lifecycle Hooks

Plugin 安装 5 个 Hook（均 chmod +x）：

| Hook | 触发时机 | 用途 |
|------|---------|------|
| `session-start.sh` | SessionStart | 环境预检（uv/python/git/ANTHROPIC_API_KEY） |
| `pre-tool.sh` | PreToolUse | 拦截危险命令（13 denylist 模式）+ 文件 sandbox |
| `post-edit.sh` | PostToolUse (Edit/Write) | 自动跑 `ae gate-check --quick` |
| `stop.sh` | Stop | 标记 running checkpoint 为 interrupted |
| `on-pr.sh` | PostToolUse (gh pr create) | 追加 Gate 结果到 PR body |

---

## 5. 工作流示例

### 5.1 完整流程图

```
[用户]                         [Plugin]                       [Engine]
  │                              │                              │
  │ /ae:dev-loop "需求"          │                              │
  ├─────────────────────────────→│                              │
  │                              │ session-start.sh              │
  │                              │ .venv/bin/ae dev-loop ...    │
  │                              ├─────────────────────────────→│
  │                              │                              │ 1. _init_state()
  │                              │                              │ 2. while not _should_stop:
  │                              │                              │ 3.   stage = router.next(state)
  │                              │                              │ 4.   plan = plan.get_tasks_by_stage(stage)
  │                              │                              │ 5.   ctx = _build_per_task_ctx(state)
  │                              │                              │ 6.   round.run_round(...)
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
  │                              │   ┌─ Stage: developer ─┐    │
  │                              │   │ GitDiffExists G3 ✓  │    │
  │                              │   │ TestsPass G4 ✓      │    │
  │                              │   │ LintGate ✓ Type ✓   │    │
  │                              │   │ → T2→T3: critic     │    │
  │                              │   └─────────────────────┘    │
  │                              │   ┌─ Stage: critic ────┐    │
  │                              │   │ verdict: PASS      │    │
  │                              │   │ → T4: APPROVE       │    │
  │                              │   └─────────────────────┘    │
  │                              │   <stdout JSON 6 fields>     │
  │                              │←─────────────────────────────┤
  │ <Plugin 展示 JSON>           │ status=success              │
  │←─────────────────────────────┤ thread_id=xxx               │
  │                              │ rounds=3                     │
  │                              │ verdict=APPROVE              │
  │                              │ duration_sec=180             │
  │                              │ gate_summary={...}           │
```

### 5.2 标准场景："实现 hello world 函数"

```bash
# 在 Claude Code 中
/ae:dev-loop "实现一个返回 'Hello, World!' 的 Python 函数 hello()，包含单元测试"
```

**期望 stdout JSON**：
```json
{
  "status": "success",
  "thread_id": "thread-20260701-094512-abc123",
  "rounds": 3,
  "verdict": "APPROVE",
  "duration_sec": 87.4,
  "gate_summary": {
    "lint": true, "type_check": true, "test": true,
    "coverage": null, "safety": true, "build": null, "contract": null
  }
}
```

**实际步骤**：

| Step | Stage | 耗时（实测） | 关键事件 |
|------|-------|------------|----------|
| 1 | (init) | <1s | OrchestratorConfig 构造 + StageRouter 初始化 |
| 2 | architect | 25s | PlanExists (G2) pass → 进入 developer |
| 3 | developer | 35s | GitDiffExists (G3) ✓ + TestsPass (G4) ✓ + LintGate ✓ → 进入 critic |
| 4 | critic | 25s | verdict: PASS (0 MAJOR, 0 MINOR) → APPROVE |
| 5 | (finalize) | <1s | _save_checkpoint → exit 0 |

### 5.3 完整开发流程

```bash
# 1. 在 Claude Code 中启动
/ae:dev-loop "实现用户登录 API (JWT, 邮箱+密码)"

# Engine 自动:
#   - architect: 分析需求, 生成 plan/batch_plan/contracts
#   - developer: 实施代码 + 测试
#   - critic: 审查代码
#   - Guardrail 每阶段前后检查
#   - 7 道 Gate 全跑
#   - checkpoint 保存

# 2. 查看进度
/ae:status
# 输出: thread_id, round, stage, verdict, recent_history

# 3. 中断后恢复
/ae:checkpoint list
/ae:checkpoint resume <thread_id>

# 4. 项目级 CI
/ae:project-ci
```

### 5.4 团队协作流程

```bash
# 1. 团队成员各自安装（一次性）
git clone git@github.com:qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
cd ~/.claude/plugins/auto-engineering && uv sync

# 2. 成员 A 在项目 A 中运行
cd ~/projects/project-a
/ae:dev-loop "实现订单模块"

# 3. 成员 B 在项目 B 中运行
cd ~/projects/project-b
/ae:dev-loop "实现支付回调"

# 两人都使用同一 Engine，但 loop 状态独立（SQLite per-project）
```

### 5.5 性能基准

**单 Stage 时序**：

| Stage | LLM 调用 | 工具执行 | Gate 跑 | 合计 |
|-------|----------|----------|---------|------|
| architect | 8-20s | <1s | <1s (skip) | **8-20s** |
| developer | 10-25s | 2-10s | 5-30s (lint+type+test) | **17-65s** |
| critic | 8-20s | 1-3s | <1s (skip) | **9-23s** |

单 Stage 边界：15s ~ 2min（P50 ~40s, P95 ~80s, P99 ~120s）。

**完整 3 Stage 端到端**：

| 场景 | P50 | P95 | P99 |
|------|-----|-----|-----|
| 简单需求 (hello world) | **85s** | 130s | 200s |
| 中等需求 (5-10 文件改动) | **180s** | 360s | 480s |
| 复杂需求 (10+ 文件 + 多模块) | **400s** | 720s | 1100s |

**内存占用（16G 物理）**：

| 组件 | 峰值 |
|------|------|
| Python 引擎 | ~250 MB |
| .venv | ~800 MB |
| pytest (无 coverage) | ~150 MB |
| **单 dev-loop run 总计** | **~1.2 GB** |

### 5.6 错误场景与恢复

**Stage 失败（Gate FAIL）**：自动重试。retry_count 持久化到 checkpoint，重启后保留。

**连续 MAJOR**：critic verdict=MAJOR 连续 3 次 → StageRouter.should_stop=True → exit 1。人工 review 后调整需求或 plan 重启。

**LLM 超时**：AnthropicProvider 连续 3 次超时 → 退出码 1，无 checkpoint。检查网络/API key 后重试。

**用户 Ctrl-C**：写 interrupted checkpoint → exit 130。`/ae:dev-loop --resume` 恢复。

**ANTHROPIC_API_KEY 缺失**：exit 2，无 checkpoint。运行 `ae doctor` 验证后重试。

---

## 6. 部署与配置

### 6.1 环境变量

| 变量 | 必需 | 默认 | 说明 |
|------|------|------|------|
| `AE_PII_ENABLED` | 否 | `true` | PII 四层防护总开关 |
| `AE_METRICS` | 否 | `false` | AI Coding 度量采集（需 `AE_METRICS=1` 激活） |
| `AE_DEBUG` | 否 | `false` | DebugTracer 诊断轨迹 |
| `AE_LOG_LEVEL` | 否 | `INFO` | 引擎日志级别（`DEBUG`/`INFO`/`WARN`/`ERROR`） |
| `AE_GATE_TIMEOUT` | 否 | `300` | Gate 执行超时（秒） |
| `AE_LLM_PROVIDER` | 否 | `anthropic` | LLM Provider（anthropic/deepseek/glm/qwen/ollama） |
| `AE_PRODUCTION` | 否 | `false` | 生产模式 — 严格 REDGuardrail + block gate 降级 |
| `AE_CACHE_CONTROL` | 否 | `true` | Anthropic Prompt Caching |

```bash
# ~/.zshrc 或 ~/.bashrc（可选优化）
export AE_LOG_LEVEL=INFO
export AE_GATE_TIMEOUT=300
```

### 6.2 降级路径

Auto-Engineering v5.6 内置 5 类降级，按严重度排序：

**CoverageGate 永远 skip**：默认 `CoverageGate.run()` 直接返回 `SKIP`。coverage instrumentation 内存叠加 ~2x，在 16G 物理内存下频繁跑测试会爆。用户主动用 `ae gate-check --all` 时才会跑 coverage。

**SemanticEvaluator 不可用 → 3 级收敛**：`SemanticEvaluator` 初始化失败时，`loop.convergence` 切换到 3 级收敛（gate PASS / no-gates / max-round / stop），跳过 LLM 评估。

**Gate 工具缺失 → skip**：

| Gate | 缺失时行为 | 建议 |
|------|-----------|------|
| `LintGate` | skip | `pip install ruff` |
| `TypeCheckGate` | skip | `pip install mypy` |
| `TestGate` | skip | `pip install pytest` |
| `CoverageGate` | **永远 skip** | 不需操作 |
| `SafetyGate` | skip | `pip install bandit` |
| `BuildGate` | skip | 检查 build_cmd 配置 |
| `ContractGate` | skip | 检查 init-manifest.json |

**LLM 不可用 → 重试 + 退出码 1**：连续 3 次失败（`LLM_MAX_RETRIES`）→ 退出码 1，未写 checkpoint。检查网络/API key/API 限额后重试。

**Checkpoint DB 损坏 → 重建**：
```bash
.venv/bin/ae checkpoint list          # 列出有效 checkpoint
.venv/bin/ae checkpoint delete <bad-id>  # 删损坏 checkpoint
.venv/bin/ae dev-loop "..."           # 重新启动
```

### 6.3 监控与可观测性

**日志**：
- 引擎日志：`AE_LOG_LEVEL=DEBUG` 时输出 per-task 详细日志
- Plugin Hook 日志：`~/.claude/logs/` 下查看
- Checkpoint 历史：`ae status --verbose` 看 recent_history × 5

**关键指标**：

| 指标 | 来源 | 监控方式 |
|------|------|----------|
| dev-loop 收敛率 | AE 历史 | `.ae-state/checkpoints.db` SQL 聚合 |
| 单 Stage 平均时长 | `state.stage_started_at` | `ae status --json` |
| Gate 失败率 | `state.gate_results` | `ae status --json` |
| 连续 MAJOR 次数 | `state.majors_in_a_row` | `ae status --json` |
| Checkpoint 数 | `state.checkpoint_count` | `ae status` |

**SQL 监控示例**：
```bash
sqlite3 .ae-state/checkpoints.db \
  "SELECT checkpoint_id, stage, created_at FROM checkpoints ORDER BY created_at DESC LIMIT 10"

sqlite3 .ae-state/checkpoints.db \
  "SELECT AVG(round_index) FROM checkpoints WHERE status='APPROVE'"
```

### 6.4 Checkpoint 兼容性

- v5.6 → v5.x：兼容（`schema_version=1`）
- v5.0 JSON → v5.6 SQLite：自动迁移（`CheckpointMigrator`）
- v1.0/v2.0 JSON → v5.6：需手动 export/import

### 6.5 安全检查清单

部署前逐项确认：

- [ ] `ae doctor` 全 `ok`
- [ ] Plugin Hooks `chmod +x` 全部就绪
- [ ] pre-tool.sh denylist 已激活（13 模式）
- [ ] `.ae-state/` 在 `.gitignore` 中
- [ ] `.venv/` 在 `.gitignore` 中
- [ ] `init-manifest.json` 在项目根且 schema_version=1
- [ ] `bash ae-plugin-acceptance-test.sh` 20/20 PASS
- [ ] `.venv/bin/pytest tests/ --no-cov --timeout=120 -q` 全 PASS（~2587 tests）

---

## 7. 故障排查

### 7.1 Slash commands 未注册

**现象**：`/help` 不显示 `/ae:*` 命令。

**原因与修复**：
- Plugin 未安装 → `cp -r .claude-plugin TARGET/.claude-plugin/`
- Claude Code 未重启 → 关闭并重新打开会话
- 位置错误 → plugin 必须在 `<project>/.claude-plugin/`（非嵌套）

### 7.2 `ae_cli: missing`

**原因**：`ae` 不存在。

**修复**：
```bash
uv sync
ae doctor    # 应全部通过
```

### 7.3 `ANTHROPIC_API_KEY: missing`

**原因**：CLI 模式下 API key 未导出。

**修复**：Plugin 模式自动使用 Claude Code agent 的 OAuth token。CLI 模式：
```bash
echo $ANTHROPIC_API_KEY | head -c 8   # 验证
```

### 7.4 `denylist pattern matched`

**原因**：Bash 工具调用匹配了 13 个危险模式之一（如 `rm -rf /`）。

**修复**：使用更安全的变体（如 `rm -rf ./build/` 而非 `rm -rf /`）。

### 7.5 `path outside sandbox`

**原因**：尝试编辑项目根目录外的文件。

**修复**：保持在项目根目录内，或使用 `/tmp/` 下的绝对路径。

### 7.6 Loop 卡住或无响应

**现象**：dev-loop 几分钟无进展。

**修复**：
```bash
ae dev-loop --status --format json    # 检查状态
ae dev-loop --resume                  # 从最新 checkpoint 恢复
```

### 7.7 Gate 失败

| Gate | 失败原因 | 解决 |
|------|----------|------|
| safety | 检测到 API key / token | 从代码中删除敏感信息 |
| lint | ruff 检查失败 | `uv run ruff check --fix .` |
| type_check | mypy/pyright 失败 | `uv run mypy src/` |
| contract | ContractGate 不匹配 | 调整 architect 的 contracts 定义 |
| test | pytest 失败 | `uv run pytest -v` |
| coverage | 覆盖率 < 阈值 | 添加测试 |
| build | 导入失败 | `uv run python -c "import auto_engineering"` |

### 7.8 `/ae:dev-loop` 报 "init-manifest.json 不存在"

需要先运行 Init Engineering 项目初始化生成 `.ae-state/init-manifest.json`（Init-Loop 接口契约 IL-AC-01 要求）。

**手动创建**：
```json
{
  "schema_version": "1.0",
  "project_type": "app-service",
  "language": "python",
  "conventions": {
    "linter": "ruff",
    "type_checker": "pyright",
    "test_runner": "pytest"
  },
  "structure": {
    "source_root": "src/",
    "test_root": "tests/"
  }
}
```
放至 `.ae-state/init-manifest.json`。

### 7.9 `uv sync` 失败

```bash
cd ~/.claude/plugins/auto-engineering
uv sync                  # 依赖问题
ae doctor                # 环境问题
```

---

## 8. 项目结构

```
auto-engineering/                        # 仓库根目录
├── auto_engineering/                    # Engine 核心代码
│   ├── loop/                            # Loop 控制流
│   │   ├── tick_orchestrator.py       # v5.6 Tick 主引擎
│   │   ├── orchestrator.py            # v5.5 连续循环 (legacy)
│   │   ├── standalone_driver.py       # v7.0 StandaloneDriver
│   │   ├── stage_router.py            # T1-T22 转换表
│   │   ├── guardrail.py               # 10 Guardrail
│   │   ├── convergence.py             # 4 级收敛判定
│   │   ├── plan.py                    # Task DAG
│   │   └── init_contract.py           # Init-Loop 契约
│   ├── gates/                          # 7 Gate 实现
│   ├── agents/                         # BaseAgent + authz
│   ├── cli/                            # Click 命令
│   ├── tools/                          # file/bash/git tools
│   ├── metrics/                        # AI Coding 度量体系
│   ├── pii/                            # PII 检测与脱敏
│   ├── context/                        # 上下文卸载/摘要
│   ├── providers/                      # LLM Provider 抽象
│   └── observability/                  # LangSmith exporter
├── .claude-plugin/
│   └── plugin.json                    # Plugin manifest
├── commands/                           # 7 slash command 定义
├── hooks/                              # 5 lifecycle 事件脚本
├── skills/                             # Agent skill 描述
├── docs/                               # 用户文档 + API 参考
├── design/                             # 设计文档
├── tests/                              # ~2587 测试
├── Makefile
├── pyproject.toml
└── CLAUDE.md                           # 项目规则
```

---

## 9. 验收命令

```bash
# 1. 单元 + 集成测试
pytest tests/ --no-cov --timeout=300 -q
# 期望: ~2587 passed (2026-07-19 基准)

# 2. Plugin acceptance test
bash ae-plugin-acceptance-test.sh
# 期望: 20/20 PASS

# 3. 环境自检
uv run ae doctor
# 期望: status=ok, 7 checks 全 ok

# 4. 覆盖率
.venv/bin/pytest tests/ --cov=auto_engineering --cov-report=term-missing --timeout=120
# 期望: ≥ 90%
```

---

## 10. 参考文档索引

| 文档 | 用途 | 读者 |
|------|------|------|
| `CLAUDE.md` | 项目规则（Claude Code 行为约定） | 开发者 |
| `design/BEACON.md` | 项目明灯（目标/范围/74 条决策） | 架构师/开发者 |
| `design/v5.6-Design-Loop.md` | 完整设计文档（1728 行, Tick 协议） | 开发者 |
| `design/IMPLEMENTATION-TRACKER.md` | 实施跟踪表（Phase 1-26, 196/196） | 开发者/PM |
| `docs/api-reference.md` | v5.6 API 接口 + 代码示例 | 开发者 |
| `docs/EARS-v5.0.md` | 验收标准 15 AC + 5 IL-AC | QA/PM |
| `docs/PRODUCT-TRAINING-GUIDE.md` | 产品培训指南 | 新用户 |
| `.claude/rules/pytest-memory-management.md` | 16G 内存约束 | 开发者 |
| `.claude/rules/agent-spawn-timeout.md` | Agent 超时防护 | 开发者 |

---

## 11. 反馈

- GitHub: https://github.com/qianminjian/Auto-engineering
- 测试状态: ~2587 passed, 7/7 doctor, 20/20 acceptance, ≥90% coverage (2026-07-19 基准)
