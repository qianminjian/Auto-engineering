# Auto-Engineering v5.6.0

跨 Claude Code / Codex 的 Tick-Based Discrete Invocation Loop Engineering 调度脚手架。

团队内部分发 (5-20 用户本地安装) — 不是 SaaS，不是个人工具。

## 当前入口

Auto-Engineering 只有一套 Host-neutral Tick 核心，两个宿主仅入口不同：

| 平台 | 用户入口 |
|------|---------|
| Claude Code | `/ae:dev-loop "需求"` |
| Codex | `$auto-engineering`，随后描述需求 |

从源码安装后的最小验证：

```bash
uv sync
scripts/ae-run doctor
scripts/ae-run dev-loop --init "需求"
```

`--init` 只产生首个 action JSON；当前宿主 Agent 按 action 执行后，使用
`scripts/ae-run dev-loop --tick --result <result.json>` 推进，直到 Python 输出
`{"action":"done"}`。Python 引擎不直接调用 LLM。

## 环境要求

- Python >= 3.12
- uv >= 0.5.0
- git >= 2.40
- sqlite3 >= 3.42

## 从源码安装

```bash
git clone https://github.com/qianminjian/Auto-engineering.git
cd Auto-engineering
uv sync
scripts/ae-run doctor
```

发布包包含 Claude Code 与 Codex 两套 manifest、Hook、规则和 Skill/Command；
安装到宿主后仍通过顶部“当前入口”进入同一循环。

## 架构

```
Host Adapter 层
  .claude-plugin/ + commands/  ──→ Claude Code
  .codex-plugin/ + skills/     ──→ Codex
  scripts/ae-run               ──→ 共享 CLI resolver

Host-neutral Core (auto_engineering/)
  loop/tick_orchestrator.py  — v5.6 Tick 主引擎
  loop/stage_router.py       — T1-T22 转换表
  loop/guardrail.py          — 9 Guardrail (含 REDGuardrail/FreshGuardrail/RegressionGuardrail)
  loop/convergence.py        — 4 级收敛判定
  gates/                     — 7+1 道 Gate (safety→lint→type_check→audit→contract→test→build)
  prompts/                   — B12 中央提示词管理 (9 角色 + 8 片段)
```

## 设计文档

| 文档 | 内容 |
|------|------|
| `design/BEACON.md` | 当前目标、范围、决策和下一步（≤80 行） |
| `design/v5.6-Design-Loop.md` | 当前 Tick、Host Adapter、验证与 Release 契约 |
| `design/v5.7-Protocol-Kernel-Design.md` | 已批准的协议内核目标设计 |
| `design/v5.7-Protocol-Kernel-PLAN.md` | Phase 52-56 实施计划 |
| `design/IMPLEMENTATION-TRACKER.md` | 当前里程碑和新鲜验证证据 |
| `design/HISTORY.md` | 历史里程碑与 Git 追溯入口 |

## 测试

```bash
uv run pytest tests/ --no-cov --timeout=120 -q
<!-- test-baseline --> 1913 passed / 1 skipped
```

## 环境变量

所有功能开关集中在 `auto_engineering/config/feature_flags.py` FeatureManifest SSOT。运行 `ae doctor` 查看完整面板。

| 变量 | 默认 | 说明 |
|------|------|------|
| `AE_PII_ENABLED` | 1 | PII 四层防护总开关 |
| `AE_METRICS` | 0 | AI Coding 度量与自进化体系 |
| `AE_AUDIT_LOG` | 0 | LLM 调用审计日志 (JSONL) |
| `AE_DEBUG` | 0 | DebugTracer 诊断轨迹 |
| `AE_OTLP_ENDPOINT` | — | OTLP 分布式追踪导出 |
| `AE_GATE_TIMEOUT` | — | Gate 执行超时秒数 |
| `AE_PRODUCTION` | 0 | 生产安全模式（严格 REDGuardrail） |
| `AE_TOKEN_TRACKING` | 0 | 逐 Tick Token JSONL 采集 |

完整 Manifest 通过 `ae doctor` 查看。

## 许可

MIT
