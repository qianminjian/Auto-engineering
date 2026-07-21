# Auto-Engineering v5.6

Claude Code Plugin — Tick-Based Discrete Invocation Loop Engineering 调度脚手架

团队内部分发 (5-20 用户本地安装) — 不是 SaaS，不是个人工具。

## 环境要求

- Python >= 3.12
- uv >= 0.5.0
- git >= 2.40
- sqlite3 >= 3.42

## 安装

```bash
git clone https://github.com/qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
cd ~/.claude/plugins/auto-engineering && uv sync
```

重启 Claude Code 后 7 个 slash command 可用。

全局 `ae` 命令（可选，CLI 调试用）：

```bash
cd ~/.claude/plugins/auto-engineering
uv tool install . --force
ae doctor      # 环境预检
```

## 使用

### Plugin 模式（推荐，零配置）

```
/ae:dev-loop "实现用户登录功能，支持 JWT 认证"
```

直接在 Claude Code agent 内执行 Tick-Based 离散循环（architect → developer → critic → 5 层验证），复用 agent 的 LLM 连接。

### CLI 模式

```bash
ae dev-loop --init                        # 初始化 tick 循环
ae dev-loop --tick --result result.json   # 提交本轮 result，推进 tick
ae dev-loop --status --format json        # 查看进度
ae dev-loop --resume                      # 从 checkpoint 恢复
ae doctor                                 # 环境预检
ae gate-check --quick                     # 快速 Gate (safety+lint+type_check)
ae gate-check --all                       # 全量 Gate
```

## Slash Commands

| 命令 | 说明 |
|------|------|
| `/ae:dev-loop` | 开发循环 |
| `/ae:status` | 查看状态 |
| `/ae:checkpoint` | Checkpoint 管理 |
| `/ae:project-tdd` | TDD 执行 |
| `/ae:project-worktree` | 创建 worktree |
| `/ae:project-agent` | 单 Agent 调用 |
| `/ae:project-ci` | 跑全量 CI gate |

## 架构

```
Plugin 层 (.claude-plugin/)
  commands/*.md  ──→  Bash 委托 ae <subcommand>
  hooks/*.sh     ──→  事件响应
  skills/SKILL.md ──→  Agent 使用指引

Engine 层 (auto_engineering/)
  loop/tick_orchestrator.py  — v5.6 Tick 主引擎
  loop/standalone_driver.py  — v7.0 Standalone 驱动
  loop/stage_router.py       — T1-T22 转换表
  loop/guardrail.py          — 9 Guardrail (含 REDGuardrail/FreshGuardrail/RegressionGuardrail)
  loop/convergence.py        — 4 级收敛判定
  gates/                     — 7+1 道 Gate (safety→lint→type_check→audit→contract→test→build)
  agents/                    — BaseAgent + tool_use loop + AUTHZ_MATRIX
  prompts/                   — B12 中央提示词管理 (9 角色 + 8 片段)
  runtime/                   — AgentRuntime + CancellationToken
```

## 设计文档

| 文档 | 内容 |
|------|------|
| `design/BEACON.md` | 设计基线（目标/范围/74 条决策/当前状态） |
| `design/v5.6-Design-Loop.md` | 唯一设计文档：Tick-Based 协议 + 5 层验证 + Init→Loop 契约 + v7.0 双驱动 |
| `design/IMPLEMENTATION-TRACKER.md` | 实施跟踪表（Phase 1-26, 196/196 全部完成） |
| `design/INDEX.md` | 文档索引 |

## 测试

```bash
uv run pytest tests/ --no-cov --timeout=120 -q
# ~2587 tests passed
```

## 环境变量

所有功能开关集中在 `auto_engineering/config/feature_flags.py` FeatureManifest SSOT。运行 `ae doctor` 查看完整面板。

| 变量 | 默认 | 说明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | — | Anthropic API 密钥（必需） |
| `AE_PII_ENABLED` | 1 | PII 四层防护总开关 |
| `AE_METRICS` | 0 | AI Coding 度量与自进化体系 |
| `AE_AUDIT_LOG` | 0 | LLM 调用审计日志 (JSONL) |
| `AE_DEBUG` | 0 | DebugTracer 诊断轨迹 |
| `AE_OTLP_ENDPOINT` | — | OTLP 分布式追踪导出 |
| `AE_LANGSMITH` | 0 | LangSmith 可观测性集成 |
| `AE_GATE_TIMEOUT` | — | Gate 执行超时秒数 |
| `AE_PRODUCTION` | 0 | 生产安全模式（严格 REDGuardrail） |
| `AE_LLM_PROVIDER` | anthropic | LLM Provider 选择 |
| `AE_MODEL_ROLE` | — | 按 role 覆盖默认模型 (格式: `AE_MODEL_ARCHITECT=claude-sonnet-4-6`) |
| `AE_CACHE_CONTROL` | 1 | Anthropic Prompt Caching |
| `AE_TOKEN_TRACKING` | 0 | 逐 Tick Token JSONL 采集 |

完整 Manifest（22 项）通过 `ae doctor` 查看。

## 许可

MIT
