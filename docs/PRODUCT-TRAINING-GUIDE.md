# Auto-Engineering 产品培训手册

> v5.6 + v7.0 双驱动 + v8.0 多平台 | 2026-07-19 | 适用版本: ae ≥ 5.6.0
> 目标读者: 团队开发者、技术负责人、平台运维
> 预计阅读时间: 30 分钟

---

## 目录

1. [产品概述](#1-产品概述)
2. [核心概念速览](#2-核心概念速览)
3. [安装](#3-安装)
4. [快速上手](#4-快速上手)
5. [三种使用模式](#5-三种使用模式)
6. [Stage Checkpoint Gate — 人在环控制](#6-stage-checkpoint-gate--人在环控制)
7. [多 Provider 与模型配置](#7-多-provider-与模型配置)
8. [DebugTracer — 调度轨迹诊断](#8-debugtracer--调度轨迹诊断)
9. [安全管理 — PII 防护与文件访问控制](#9-安全管理--pii-防护与文件访问控制)
10. [可观测性 — OTLP 追踪与审计日志](#10-可观测性--otlp-追踪与审计日志)
11. [Context 管理](#11-context-管理)
12. [Gate 质量门系统](#12-gate-质量门系统)
13. [Checkpoint 恢复](#13-checkpoint-恢复)
14. [单 Agent 调用与辅助命令](#14-单-agent-调用与辅助命令)
15. [环境变量完整参考](#15-环境变量完整参考)
16. [故障排查](#16-故障排查)
17. [FAQ](#17-faq)

---

## 1. 产品概述

### 1.1 Auto-Engineering 是什么

**Auto-Engineering** 是一个 **AI 驱动的软件工程调度框架**，以 Claude Code / Codex / CodeBuddy Plugin 形态运行。用户在会话中输入 `/dev-loop "需求描述"`，系统自动执行**多阶段多 Agent 循环**——分析需求 → 生成计划 → 编写代码 → 跑测试 → 质量门禁 → 审查修正，最终产出可提交的代码变更。

**一句话**: 给 AI 一个需求描述，它完成架构设计、编码实现、测试验证、质量审查的全流程。

### 1.2 解决什么问题

| 痛点 | Auto-Engineering 如何解决 |
|------|------------------------|
| AI 编码无结构，直接写代码跳过了设计思考 | architect → developer → critic 三阶段强制设计先行 |
| 每次 AI 对话都是"一次性"，没有可复现的工程流程 | Tick 协议持久化每步状态到 SQLite，中断可恢复 |
| AI 产出的代码质量和安全性不可控 | 7 道 Gate 门禁 + 9 道 Guardrail 守门，自动化拦截质量问题 |
| 模型锁定（只能用 Claude） | 多 Provider 支持（Anthropic/Ollama/GLM/通义/OpenAI），按角色分配模型 |
| 无法追踪 AI 编码过程 | DebugTracer 完整轨迹 + OpenTelemetry OTLP + 审计日志 JSONL |
| 缺乏人在环控制 | Stage Checkpoint Gate 在关键阶段暂停，等用户决策 |

### 1.3 核心架构：双驱动 + 三平台

```
┌──────────────────────────────────────────────────┐
│                  用户入口                          │
│  Claude Code │ Codex │ CodeBuddy │ 终端 CLI       │
└────────┬────────────────────────────────┬────────┘
         │                                │
    ┌────▼─────┐                    ┌────▼──────────┐
    │ Driver A │   Agent 驱动        │  Driver B     │  Standalone 驱动
    │ Agent    │   文件桥接           │  进程内 LLM    │  自带 API Key
    │ 填 result │                    │  填 result    │
    └────┬─────┘                    └────┬──────────┘
         │                                │
         └──────────┬─────────────────────┘
                    │
         ┌──────────▼──────────┐
         │  TickOrchestrator   │  唯一循环引擎
         │  读 SQLite → 验证   │  Python 纯逻辑, 永不调 LLM
         │  → Guardrail → Gate │
         │  → 路由 → action    │
         └─────────────────────┘
```

- **Driver A（Agent 驱动）**: Claude Code Agent 按照 Tick 协议反复调用 `ae dev-loop --tick`，通过文件桥接与引擎交互
- **Driver B（Standalone 驱动）**: 进程内直接调 LLM，不依赖外部 Agent，适合 CI/CD 流水线、银行内网部署
- **TickOrchestrator**: Python 确定性引擎，所有编排逻辑纯代码，不调 LLM，可测试

### 1.4 5 层验证管道

每个需求经过 5 层渐进验证（频率×范围矩阵，高频窄用轻量模型，低频全量用重量模型）:

| 层 | Agent | 模型 | 触发频率 | 检查范围 |
|----|-------|------|---------|---------|
| ① critic | 代码审查 | Sonnet | 每个 developer batch | diff 级变更 |
| ② component_verifier | 组件覆盖 | Haiku | 每个 component 完成 | 单组件设计覆盖 |
| ③ plate_deep_audit | 板块审计 | Sonnet | 每个 plate 完成 | 跨组件交互质量 |
| ④ system_verifier | 全量覆盖 | Haiku | 退出前一次 | 全量设计覆盖 |
| ⑤ system_deep_audit | 全量审计 | Sonnet | 退出前一次 | 6 维代码质量 |

**自动裁剪**: 单组件需求只跑 ①②⑤（跳过 ③ 跨组件审计和 ④ 全量覆盖——范围与 ② 完全重合）。

### 1.5 适合谁用

- **5-20 人团队内部使用**: 作为 AI 编码的标准工作流（非 SaaS，本地安装）
- **需要编码规范化的团队**: Gate 门禁强制安全/lint/类型/测试/覆盖率标准
- **银行/金融/合规场景**: 多 Provider（国产模型）、PII 防护、可观测性、审计日志
- **CI/CD 集成**: Standalone 模式可直接嵌入流水线

---

## 2. 核心概念速览

### Tick-Based 离散调用协议

```
Tick 1: Engine 输出 action JSON → Agent 执行 architect → 写 result JSON
Tick 2: Engine 读 result → 验证 → 输出 action → Agent 执行 developer
Tick 3: Engine 读 result → 验证 → 输出 action → Agent 执行 critic
...
Tick N: Engine 判定 GOAL_ACHIEVED → 输出 done
```

每个 tick Python 进程独立启动、读取状态、处理验证、输出下一 action、退出。Agent 在 tick 之间做 LLM 工作。引擎本身**永远不调 LLM**。

### 关键术语

| 术语 | 含义 |
|------|------|
| Tick | 一次引擎处理周期（读 result → 验证 → 输出 action） |
| Stage | 当前阶段（architect / developer / critic / verifier / audit） |
| Batch | developer 阶段内的一组 task（≤5 文件/batch） |
| Gate | 自动化质量门（7 道：safety/lint/type_check/audit/contract/test/build） |
| Guardrail | 守护规则（9 道：GitDiff/RED/TDD/Fresh/Regression/Context/Schema/PII/FileAccess） |
| Action | 引擎输出的 JSON 指令（告诉 Agent 下一步做什么） |
| Result | Agent 执行后写回的 JSON 报告 |
| Checkpoint | SQLite 持久化的完整引擎状态（中断后可恢复） |

---

## 3. 安装

### 3.1 前置条件

| 组件 | 版本要求 | 检查命令 |
|------|---------|---------|
| Python | ≥ 3.12 | `python3 --version` |
| uv | ≥ 0.5.0 | `uv --version` |
| git | ≥ 2.30 | `git --version` |
| sqlite3 | ≥ 3.35 | `sqlite3 --version` |
| API Key | Anthropic / OpenAI / 其他 | `echo $ANTHROPIC_API_KEY \| head -c 8` |

### 3.2 安装（2 条命令）

在 Claude Code / Codex / CodeBuddy 会话中:

```
/plugin marketplace add qianminjian/Auto-engineering
/plugin install auto-engineering@qianminjian --scope user
```

平台自动 `git clone` 仓库到插件缓存目录，加载所有 commands/hooks/skills。**安装后重启对应平台**。

Codex 等效:
```
codex plugin marketplace add qianminjian/Auto-engineering
codex plugin install auto-engineering
```

### 3.3 开发环境安装（从源码）

```bash
git clone https://github.com/qianminjian/Auto-engineering.git
cd Auto-engineering
ln -sfn "$(pwd)" ~/.claude/plugins/auto-engineering
uv sync
```

### 3.4 验证安装

```bash
ae doctor    # 应全部 7 项 PASS
```

在 Claude Code 中输入 `/help`，应看到 `/ae:dev-loop`、`/ae:status` 等命令。

---

## 4. 快速上手

### 4.1 第一次使用（5 分钟）

```bash
# 1. 进入任意 Python 项目
cd ~/projects/my-project

# 2. 环境预检
ae doctor
# 输出: ✓ Python 3.13 ✓ uv ✓ git ✓ sqlite3 ✓ API_KEY ✓ .ae-state/found

# 3. Standalone 模式（推荐，进程内完成，无需外部 Agent）
ae dev-loop --standalone "实现一个 fibonacci 函数，含单元测试"

# 输出示例:
# [architect] 分析需求，生成计划...
# [developer] 实现代码 + 测试...
# [critic] 审查代码...
# ✓ GOAL_ACHIEVED | ticks=6 | tests=10/10 | 文件: src/fibonacci.py, tests/test_fibonacci.py
```

### 4.2 在 Claude Code 中使用

```
# 在任意项目目录的 Claude Code 会话中:
/dev-loop "实现用户登录 API，支持 JWT 令牌"
```

Agent 自动执行完整三阶段循环，输出包括代码变更、测试结果、审查结论。

### 4.3 第一个设计文档驱动项目

如果项目已有设计文档:

```bash
ae dev-loop --standalone --design-doc design/spec.md "按设计文档实现"
```

引擎首先运行 Pre-flight Gap Analysis（检查设计文档的模糊章节），然后按照设计文档中的组件层次结构执行实现。

---

## 5. 三种使用模式

### 5.1 Plugin 模式 — Claude Code 内 `/dev-loop`

**适用**: 日常交互式开发，需要人类在环决策

```
# 基本用法
/dev-loop "实现 Redis 缓存层"

# 带选项
/dev-loop "实现支付回调" --max-rounds 10 --pause-at-stage critic

# 查看进度
/status

# 中断后恢复
/checkpoint list
/checkpoint resume <id>
```

Agent 会在内部 spawn Plan agent（architect）、code-reviewer agent（critic），developer 阶段由 Claude Code 自己执行。

### 5.2 CLI Tick 模式 — 离散调用 `ae dev-loop --init → --tick → --result`

**适用**: 脚本化、手动控制每个 tick、CI/CD 集成

```bash
# Step A: 初始化
ae dev-loop --init "实现 Redis 缓存" --max-rounds 5
# 输出: {"action": "architect", "tick": 1, "stage": "architect", ...}

# Step B: Agent 执行 architect，产出 result.json，提交
ae dev-loop --tick --result result.json
# 输出: {"action": "developer", "tick": 2, ...}

# Step C: 反复 --tick --result 直到 done
ae dev-loop --tick --result result2.json
# → {"action": "critic", ...}
ae dev-loop --tick --result result3.json
# → {"action": "done", "verdict": "GOAL_ACHIEVED"}

# 查看当前状态
ae dev-loop --status --format json
```

### 5.3 Standalone 模式 — `ae dev-loop --standalone`

**适用**: CI/CD 流水线、批量自动化、银行内网部署（不需要外部 Claude Code Agent）

```bash
# 基本用法
ae dev-loop --standalone "实现用户注册 API"

# 带设计文档
ae dev-loop --standalone --design-doc design/api-spec.md "实现"

# 自定义模型
AE_MODEL_ARCHITECT=claude-opus-4-7 ae dev-loop --standalone "复杂架构设计"

# 使用国产模型
AE_PROVIDER_ARCHITECT=glm AE_PROVIDER_DEVELOPER=glm ae dev-loop --standalone "实现 CRUD"

# 调试模式
ae dev-loop --standalone --debug "实现 fibonacci"

# Stage Checkpoint Gate
ae dev-loop --standalone --pause-at-stage architect,critic "实现缓存"
```

**v5.5 legacy 路径已弃用**: `ae dev-loop "需求"`（裸参数）仍可运行但输出弃用警告，30 天后移除。请改用 `--standalone`。

---

## 6. Stage Checkpoint Gate — 人在环控制

> 新增于 T64 | 设计参考: BEACON 决策 #67 ORCA DecisionGate 形态 3

### 6.1 是什么

在指定 stage 开始前暂停循环，输出当前进度摘要，**等待用户决策**后继续。三种决策选项:

| 选项 | 行为 |
|------|------|
| **继续** | 正常进入该 stage，执行对应 Agent |
| **审查当前产出** | 展示当前已完成的代码/测试/结果，供人工审查 |
| **终止 loop** | 停止循环，返回 TERMINATED |

### 6.2 使用方式

```bash
# 在 architect 阶段前暂停（审查计划是否合理）
ae dev-loop --standalone --pause-at-stage architect "实现支付模块"

# 在多个阶段前暂停
ae dev-loop --standalone --pause-at-stage architect,critic "实现支付模块"

# Plugin 模式
/dev-loop "实现支付模块" --pause-at-stage critic
```

### 6.3 工作流示例

```
1. 用户: ae dev-loop --standalone --pause-at-stage critic "实现缓存"
2. Engine: gap_scan → architect → developer（正常通过）
3. Engine 在 critic 前暂停，输出:
   ┌─────────────────────────────────────────┐
   │ Gate: checkpoint_critic                  │
   │ 即将进入 critic 阶段                      │
   │ 当前进度: tick=4/5, stage=developer,      │
   │           batch=B1                        │
   │ 选项: 继续 / 审查当前产出 / 终止 loop       │
   └─────────────────────────────────────────┘
4. 用户选择"审查当前产出" → 查看 developer 产出的代码
5. 用户确认无误 → 下一 tick 选择"继续" → critic 执行审查
```

### 6.4 可用 Stage 列表

`architect` | `developer` | `critic` | `component_verifier` | `plate_deep_audit` | `system_verifier` | `system_deep_audit`

拼写错误的 stage 名会在 stderr 输出 WARN，不会静默忽略。

---

## 7. 多 Provider 与模型配置

> 新增于 T58/T59 | 设计参考: BEACON 决策 #55 Provider 抽象

### 7.1 支持的 Provider

| Provider | 标识 | 所需环境变量 | 用途 |
|----------|------|-------------|------|
| Anthropic Claude | `anthropic` | `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` | 主力模型（Sonnet/Opus/Haiku） |
| Ollama（本地） | `ollama` | `OLLAMA_HOST` | 本地部署、离线环境 |
| 智谱 GLM | `glm` | `ZHIPUAI_API_KEY` | 国产模型、信创合规 |
| 通义千问 | `qwen` | `DASHSCOPE_API_KEY` | 国产模型、信创合规 |
| OpenAI | `openai` | `OPENAI_API_KEY` | GPT-4o 等 |

### 7.2 自动检测

引擎自动从环境变量推断 Provider（优先级从高到低）:

```
OLLAMA_HOST → ZHIPUAI_API_KEY → DASHSCOPE_API_KEY → OPENAI_API_KEY → ANTHROPIC_API_KEY
```

**注意**: 如同时设置多个 Key，OLLAMA_HOST 优先级最高。如需指定，使用 `AE_LLM_PROVIDER` 全局变量或 `AE_PROVIDER_<ROLE>` 按角色覆盖。

### 7.3 按角色配置 Provider

每个 Agent 角色可独立指定 Provider 和模型:

```bash
# architect 用 Claude Opus（最强推理），developer 用本地 Ollama（省钱）
export AE_PROVIDER_ARCHITECT=anthropic
export AE_MODEL_ARCHITECT=claude-opus-4-7
export AE_PROVIDER_DEVELOPER=ollama
export AE_MODEL_DEVELOPER=codellama:34b

ae dev-loop --standalone "实现支付模块"
```

### 7.4 按角色配置模型

```bash
# 轻量角色用 Haiku（快速、低成本）
export AE_MODEL_GAP_SCAN=claude-haiku-4-5-20251001
export AE_MODEL_COMPONENT_VERIFIER=claude-haiku-4-5-20251001
export AE_MODEL_SYSTEM_VERIFIER=claude-haiku-4-5-20251001

# 重量角色用 Sonnet（深度推理）
export AE_MODEL_ARCHITECT=claude-sonnet-4-6
export AE_MODEL_DEVELOPER=claude-sonnet-4-6
export AE_MODEL_CRITIC=claude-sonnet-4-6
```

### 7.5 完整角色列表

| 角色 | 环境变量 | 默认模型 |
|------|---------|---------|
| gap_scan | `AE_MODEL_GAP_SCAN` | claude-haiku-4-5-20251001 |
| research | `AE_MODEL_RESEARCH` | claude-haiku-4-5-20251001 |
| architect | `AE_MODEL_ARCHITECT` | claude-sonnet-4-6 |
| developer | `AE_MODEL_DEVELOPER` | claude-sonnet-4-6 |
| critic | `AE_MODEL_CRITIC` | claude-sonnet-4-6 |
| component_verifier | `AE_MODEL_COMPONENT_VERIFIER` | claude-haiku-4-5-20251001 |
| plate_deep_audit | `AE_MODEL_PLATE_DEEP_AUDIT` | claude-sonnet-4-6 |
| system_verifier | `AE_MODEL_SYSTEM_VERIFIER` | claude-haiku-4-5-20251001 |
| system_deep_audit | `AE_MODEL_SYSTEM_DEEP_AUDIT` | claude-sonnet-4-6 |

### 7.6 Prompt Caching（Anthropic 专用）

引擎自动为 system prompt 和 tool definitions 注入 `cache_control: ephemeral`，减少重复 token 消耗。默认启用。

```bash
# 禁用（本地测试/调试时）
AE_CACHE_CONTROL=0 ae dev-loop --standalone "需求"
```

---

## 8. DebugTracer — 调度轨迹诊断

> 新增于 Phase 15 T45 | 设计参考: BEACON 决策 #61

### 8.1 激活方式

```bash
# CLI flag
ae dev-loop --standalone --debug "需求"
ae dev-loop --init --debug "需求"

# 环境变量
AE_DEBUG=1 ae dev-loop --standalone "需求"

# 自定义输出目录
ae dev-loop --standalone --debug --debug-dir /tmp/my-debug "需求"
```

默认输出: `<project_root>/_scratch/debug/`

### 8.2 三输出文件

| 文件 | 内容 | 用途 |
|------|------|------|
| `tick-{0001..NNNN}.json` | 每个 tick 完整快照：stage_in/out, action, state_snapshot, guardrail 结果, gate 结果, 耗时(ms) | 逐 tick 排查调度异常 |
| `errors.jsonl` | 故障事件追加：ErrorResponse, guardrail block/retry, 格式验证错误 | 查看所有故障点 |
| `trace.json` | 最终摘要：verdict, total_ticks, stage_sequence, error_counts, total_duration_ms | 快速了解 loop 全貌 |

### 8.3 解读 trace.json

```json
{
  "verdict": "GOAL_ACHIEVED",
  "total_ticks": 6,
  "stage_sequence": ["architect", "developer", "critic", "component_verifier", "system_deep_audit", "done"],
  "error_counts": {"REDGuardrail": 1},
  "total_duration_ms": 163245.50,
  "finished_at": "2026-07-19T10:30:00.123456Z"
}
```

- `error_counts` 显示哪个 guardrail 触发了几次——开发阶段 TDD 纪律问题一目了然
- `stage_sequence` 显示实际走了哪些 stage——对比预期排查自动裁剪逻辑

### 8.4 零开销保证

不激活 DebugTracer 时（默认）: 零文件 IO，零 JSON 序列化，对性能无影响。实现: `DebugTracer.disabled()` 工厂返回 `self._dir = None` 的 no-op 实例，每个方法第一行 `if self._dir is None: return`。

---

## 9. 安全管理 — PII 防护与文件访问控制

> 新增于 Phase 18 T56/T57 + T62 | 设计参考: BEACON 决策 #63 银行生产级框架

### 9.1 PII 防护（三道防线）

引擎在 LLM 调用链路上设置三道防线，防止敏感数据外泄:

| 防线 | 位置 | 行为 | 阻断 |
|------|------|------|------|
| ① Prompt PII Redaction | LLM 调用前 | 正则扫描 system prompt + messages，身份证号/手机号/银行卡/API Key 自动脱敏 | 否（脱敏不阻断，WARN 日志） |
| ② Tool Result PII Scan | Tool 返回结果写入前 | 扫描 tool 输出中的敏感信息 | 否（脱敏不阻断） |
| ③ PII Guardrail G10 | Post-agent 全量文件扫描 | 扫描 developer 产出的所有文件 | 可配置阻断 |

### 9.2 检测规则

| 数据类型 | 检测模式 | 脱敏格式 |
|---------|---------|---------|
| 身份证号（18 位） | `\d{17}[\dXx]` | `3201**********1234` |
| 手机号（11 位） | `1[3-9]\d{9}` | `138****1234` |
| 银行卡号（13-19 位） | `\d{13,19}` | `6222****1234` |
| API Key | `sk-[a-zA-Z0-9]+` 等模式 | `sk-****` |
| 邮箱 | 标准 email regex | `u***@domain.com` |

### 9.3 文件访问控制（FileAccessGuardrail, G11)

**规则**: developer 产出的 `files_changed` 中的文件，必须全部在 architect 规划的 `file_targets` 列表中。

**支持 glob 模式**（pathspec 库）:

```python
# architect 在 batch_plan 中声明 file_targets
"file_targets": [
    "src/auth/*.py",
    "tests/test_auth*.py",
    "docs/auth.md"
]
# developer 只能修改匹配这些 glob 模式的文件
# 修改 src/auth/JWT.py → ✅ 匹配 src/auth/*.py
# 修改 src/payment/handler.py → ❌ 不匹配任何 target
```

---

## 10. 可观测性 — OTLP 追踪与审计日志

> 新增于 T60/T61 | 设计参考: BEACON 决策 #66

### 10.1 OpenTelemetry OTLP 追踪

每个 stage/guardrail/gate 执行自动打 OTLP span:

```bash
# 配置 OTLP endpoint
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=auto-engineering

ae dev-loop --standalone "实现登录"
# 每个 stage 自动生成 OTLP span，可在 Jaeger/Grafana 查看
```

### 10.2 结构化审计日志

LLM 每次调用的完整 request/response 写入 JSONL:

```bash
# 输出位置: <project_root>/_scratch/audit/llm-calls.jsonl
ae dev-loop --standalone "实现登录"

# 每行格式:
{"timestamp": "2026-07-19T10:30:00Z", "role": "architect", "model": "claude-sonnet-4-6",
 "request": {"system": "...", "messages": [...]}, "response": {"content": "...",
 "usage": {"input": 1500, "output": 800}, "stop_reason": "end_turn"}}
```

---

## 11. Context 管理

> 新增于 T53/T54

### 11.1 Stage Context Offloading

每个 stage 完成后，完整 context 写入文件，下一个 stage 只加载摘要——避免 LLM 上下文累积超出窗口:

```
architect 完成 → 输出 plan 摘要 + file_list → developer 只读摘要
developer 完成 → 输出 files_changed + test_results → critic 只读 diff
```

### 11.2 Cross-tick Session Summarization

Tick > 5 时，对 developer 对话历史做摘要压缩。subagent 每次新 spawn 天然无累积压力，只有 developer（在主会话中）需要此处理。

注意: 这对用户透明，不影响正常使用。

---

## 12. Gate 质量门系统

### 12.1 7+1 道 Gate

| Gate | 检查内容 | 失败处理 |
|------|---------|---------|
| **safety** | API key / token / PII 泄露 | 阻断，必须修复 |
| **lint** | ruff / eslint 静态检查 | 可自动修复 |
| **type_check** | mypy / pyright / tsc 类型 | 阻断 |
| **audit** | 代码审计（按 audit-role.md 规范） | P0 阻断 |
| **contract** | 接口契约一致性 | 阻断 |
| **test** | pytest / vitest 通过 | 阻断 |
| **build** | import / build 通过 | 阻断 |
| **deep_audit** (按需) | 3-Agent 并行深度审计 | P0 阻断 |

### 12.2 手动调用

```bash
ae gate-check --quick    # safety + lint + type_check（秒级）
ae gate-check --all      # 全部 7 道（~30-60s）
```

---

## 13. Checkpoint 恢复

Engine 每 tick 将完整状态写入 SQLite WAL。中断后（Ctrl+C / 崩溃 / 会话结束），可无缝恢复:

```bash
# 查看所有 checkpoint
ae checkpoint list

# 查看详情
ae checkpoint show <id>

# 恢复
ae checkpoint resume <id>
# 或
ae dev-loop --resume <id>
```

---

## 14. 单 Agent 调用与辅助命令

### 14.1 单 Agent 调用

```bash
ae agent architect "分析用户模块的架构设计"
ae agent developer "实现 JWT 认证的 token 刷新逻辑"
ae agent critic "审查 src/auth.py 的安全性和代码质量"
```

### 14.2 其他辅助命令

```bash
ae doctor          # 环境预检（7 项）
ae doctor --json   # JSON 输出，适合 CI 解析
ae status          # 当前 loop 进度
ae status --format json
ae progress        # ProgressTree 看板
ae gate-check --quick
ae gate-check --all
ae checkpoint list|show|resume|delete
```

## 15. 环境变量完整参考

### 核心

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |
| `ANTHROPIC_AUTH_TOKEN` | Claude Code OAuth Token（Plugin 模式自动注入） | — |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `ZHIPUAI_API_KEY` | 智谱 GLM API Key | — |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | — |
| `OLLAMA_HOST` | Ollama 服务地址 | — |

### 引擎控制

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AE_LLM_PROVIDER` | 全局 LLM Provider（覆盖自动检测） | 自动检测 |
| `AE_PROVIDER_<ROLE>` | 按角色指定 Provider | — |
| `AE_MODEL_<ROLE>` | 按角色指定模型 | 见 §7.5 |
| `AE_LOG_LEVEL` | 日志级别 (DEBUG/INFO/WARN/ERROR) | INFO |
| `AE_GATE_TIMEOUT` | Gate 执行超时（秒） | 300 |
| `AE_MAX_ITERATIONS` | Tick 循环最大迭代次数 | 20 |
| `AE_DB_PATH` | SQLite checkpoint 路径 | `.ae-state/checkpoints.db` |
| `AE_NO_GATES` | 设为 `1` 跳过全部 Gate | false |

### 调试与可观测性

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AE_DEBUG` | 设为 `1` 激活 DebugTracer（等价 `--debug`） | 0 |
| `AE_CACHE_CONTROL` | 设为 `0` 禁用 prompt caching | 1 |
| `AE_SUPPRESS_DEPRECATION` | 设为 `1` 抑制 v5.5 弃用警告 | 0 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP 遥测端点 | — |
| `OTEL_SERVICE_NAME` | OTLP 服务名 | auto-engineering |

---

## 16. 故障排查

### 16.1 `ae doctor` 不通过

```
✗ ANTHROPIC_API_KEY: missing
```

CLI Standalone 模式需要显式设置 API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```
Plugin 模式从 Claude Code Agent 继承 token，不需要手动设置。

### 16.2 Loop 不推进 / 卡住

```bash
# 1. 查看状态
ae dev-loop --status --format json

# 2. 开启 debug 重新运行，检查 trace.json
AE_DEBUG=1 ae dev-loop --standalone "需求"

# 3. 查看 debug 目录
cat _scratch/debug/trace.json    # 最终摘要
cat _scratch/debug/errors.jsonl  # 故障事件
ls _scratch/debug/tick-*.json    # 停在哪个 tick
```

### 16.3 REDGuardrail 频繁触发

StageRouter 中的 `MAJOR` 判定导致频繁回到 architect。常见原因:
- developer 没有先写测试再写代码（TDD 纪律）
- architect 的 batch_plan 粒度太粗

解决:
- 确保 developer 遵守 Red→Green→Refactor 顺序
- 减小 batch_plan 的 task 粒度（≤5 files/batch）

### 16.4 Provider 选择不符合预期

```bash
# 检查哪几个 Key 同时设置
env | grep -E "OLLAMA_HOST|ZHIPUAI|DASHSCOPE|OPENAI_API_KEY|ANTHROPIC"

# 显式指定（优先级最高）
export AE_LLM_PROVIDER=anthropic
```

### 16.5 Standalone 模式下 `BaseAgent` 工具调用卡住

常见原因: anthropic SDK 的 tool_use block 解析问题。检查:
- Claude API 是否返回 `stop_reason: tool_use`
- `max_tool_calls` 是否过小（architect: 15, developer: 30, critic: 15）

---

## 17. FAQ

**Q: Plugin 模式和 Standalone 模式怎么选？**

| 场景 | 推荐 |
|------|------|
| Claude Code 会话中交互式开发 | Plugin `/dev-loop` |
| CI/CD 流水线自动化 | Standalone `--standalone` |
| 批量需求处理 | Standalone |
| 内网/离线环境（无 Claude Code） | Standalone + Ollama |
| 需要人工审查每个阶段 | Plugin + `--pause-at-stage` |

**Q: 可以用国产模型跑完整 loop 吗？**

可以。设置:
```bash
export AE_PROVIDER_ARCHITECT=glm
export AE_PROVIDER_DEVELOPER=glm
export AE_PROVIDER_CRITIC=glm
export ZHIPUAI_API_KEY=xxx
ae dev-loop --standalone "需求"
```

轻量角色（verifier 类）也可用 GLM/Qwen，Haiku 默认仅用于 Anthropic 路径。

**Q: 性能怎么样？**

- StandaloneDriver 真实 LLM E2E（fibonacci 需求）: ~163 秒，6 ticks，10 tests
- AgentDriver 手动驱动: ~8 分钟/需求（含人类交互延迟）
- Python 编排开销 P95 < 2s

**Q: 如何关闭所有 AI 自动修改行为，只审查不改？**

```bash
# 所有 Gate 都配置为 block-on-fail，而不进 auto-fix
export AE_NO_AUTOFIX=1
# 使用 --pause-at-stage 在每个 stage 前审查
ae dev-loop --standalone --pause-at-stage architect,developer,critic "需求"
```

**Q: 数据库/状态文件在哪里？**

- Checkpoint: `.ae-state/checkpoints.db`（SQLite WAL）
- Debug: `<project_root>/_scratch/debug/`（仅 `--debug` 时）
- Audit log: `<project_root>/_scratch/audit/llm-calls.jsonl`
- Init manifest: `.ae-state/init-manifest.json`（Init 项目生成）

**Q: 如何升级？**

```
/plugin update auto-engineering
```

从源码升级:
```bash
cd ~/.claude/plugins/auto-engineering
git pull origin main
uv sync
```

---

## 相关文档

| 文档 | 用途 |
|------|------|
| `design/BEACON.md` | 项目明灯 — 目标/范围/全部设计决策 |
| `design/v5.6-Design-Loop.md` | Tick 协议完整设计规格 |
| `docs/api-reference.md` | v5.6 API 接口文档 |
| `docs/USER_GUIDE.md` | 用户指南（含安装/入口路径/命令参考/工作流示例/部署配置/故障排查） |

---

_手册版本: v1.0 创建于 2026-07-19 | 覆盖版本: ae 5.6.0 + v7.0 双驱动 + v8.0 多平台_
