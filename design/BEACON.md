> 创建：2026-06-24 | 更新：2026-07-05 | 阶段：v5.1 JSONL Protocol (Agent-Engine 通信)

## 目标与成功标准

1. **`/ae:dev-loop` slash command**：用户触发 Plugin → Python Orchestrator 执行 Architect→Developer→Critic 三阶段 Agent 循环
2. **`ae dev-loop` CLI**：调试入口, stdout JSON 契约 (6 字段)
3. **确定性 Guardrail**：每 Stage 前后自动检查 (G1-G5, pass/block/retry 三态)
4. **Checkpoint 恢复**：SQLite WAL 持久化, 中断可恢复
5. **9 道 Gate**（v5.1）：safety → stage_transition → lint → type_check → contract → test → tdd → coverage → build
6. **Init-Loop 接口契约**（IL.1-IL.6）：消费 Init 项目 `.ae-state/init-manifest.json`
7. **JSONL 通信协议**：architect/critic LLM 调用走 stdin/stdout JSONL, 复用 Agent ANTHROPIC_AUTH_TOKEN

## 范围边界

**做：** Python Orchestrator 12 步主循环；JSONL stdin/stdout 协议 (agent context)；GuardrailChain + 9 Gates + StageRouter + ConvergenceJudge + SQLite checkpoint；Agent Working Agreements Hook；Init-Loop 接口契约
**不做：** Init Engineering（独立项目）；多 LLM Provider、Web UI、SaaS 服务端

## 设计决策

| #  | 决策 | 理由 | 日期 | status |
|----|------|------|------|--------|
| 1-28 | v1.0 → v2.5 完整演进 | LoopEngine/StageGraph/AgentRuntime → Channel/TaskDAG/ConvergenceJudge → Gates/CLI → v1.0 退役 | 2026-06-24→28 | ✅ |
| 29 | **v5.0 路线图: Plugin + Loop + Init 合订** | Plugin 形态 = Bash 委托 `uv run ae <subcommand>`, 控制流在 Python, 参考 LangGraph/AutoGen/CrewAI | 2026-06-29 | ✅ |
| 30 | **Init Engineering 拆分独立项目** | 移除 init/ (528K), 项目只保留 Loop, Init 按 §IL.1-IL.6 实现 | 2026-06-30 | ✅ |
| 31 | **v5.0 深度审计 + 4 P0 修复** | KEY 错误/语义评估器早期返回/init 残留/plugin.json 恢复 (23 项, P0×4) | 2026-07-04 | ✅ |
| 32 | ~~Agent Tool spec 模式~~ (撤销) | Agent 可能跳过规范, markdown 规则无法强制执行 → 改为 JSONL | 2026-07-04 | ❌ |
| 33 | **Agent-Engine JSONL 通信协议 (v5.1)** | Python orchestrator 保留全控制流, architect/critic LLM 走 JSONL stdin/stdout, 复用 Agent ANTHROPIC_AUTH_TOKEN | 2026-07-04 | ✅ |
| **34** | **AE_JSONL_MODE 条件开关 + 合成架构师 task** | JSONL 路径仅在 `AE_JSONL_MODE=1` 时启用 (agent context)；非 agent 回退 run_round (CLI+测试兼容)；空 tasks 时自动创建合成 architect task 触发 JSONL 规划 | 2026-07-05 | ✅ |
| **35** | **GuardrailChain.default() 工厂 + _tasks_from_batch_plan 接入** | guardrail.py 加 default() 返回 5 Guardrail 链；orchestrator 架构师响应中 batch_plan 接入 _tasks_from_batch_plan → developer tasks | 2026-07-05 | ✅ |
| **36** | **TDDGate + StageTransitionGate（借鉴 CrewAI + SonarQube）** | CrewAI GuardrailResult(success/result/error) 三态 + SonarQube 条件门禁模式；TDDGate 强制 Red→Green→Refactor, StageTransitionGate 检查阶段过渡前置条件 | 2026-07-05 | ✅ |
| **37** | **Agent Working Agreements Hook（借鉴 pre-commit "No Escape"）** | pre-tool.sh 新增 7 条 agent 规则: 拦截 --no-verify/HUSKY=0/SKIP=pre-commit/force push/--no-gpg-sign；业界三层防御架构: hook → CI → review | 2026-07-05 | ✅ |

## 当前状态

**阶段：** v5.1 JSONL Protocol — Python Orchestrator 完整 12 步主循环运行中。

**最近动作 (2026-07-05)：**
- P0: JSONL 协议 25 测试修复 (import json + AE_JSONL_MODE 开关 + 合成架构师 task + batch_plan 接入 + GuardrailChain.default() + .ae-state/ 自动创建 + run_round stage 参数)
- P1: _tasks_from_batch_plan 接入 orchestrator；commands/dev-loop.md 改为 Bash 委托 + 参数解析
- feat: TDDGate + StageTransitionGate (DEFAULT_GATES 7→9)；pre-tool.sh Agent Working Agreements (7 拦截规则)
- 插件副本 `~/.claude/plugins/auto-engineering/` 已同步
- **1349 tests passed, 0 failed**

**下一步：** 生产环境真跑验证 /ae:dev-loop JSONL 协议端到端

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-05 | **v5.1 JSONL 集成修复 + Quality Gates + Hook** (BEACON 34-37) | JSONL 25 测试全修复；借鉴 CrewAI/SonarQube/pre-commit 实现 TDDGate/StageTransitionGate/Agent Working Agreements；DEFAULT_GATES 7→9 |
| 2026-07-04 | **v5.0 深度审计 23 项 + 4 P0 修复 + Agent-Engine JSONL 协议** (BEACON 31-33) | KEY 错误/语义评估 bug/init 清理/plugin.json 恢复；Agent Tool spec → JSONL 协议 |
| 2026-06-28 | v2.5 P0-FINAL (v1.0 退役) + 深度审计 25 项 (BEACON 27-28) | engine/* + gates/{builtin,guardrail}.py 退役；asyncio.to_thread 真并行；SQLite WAL；项目健康 6.5→8.0 |
| 2026-06-27 | v2.4 P0-C + P1-C (CoverageGate/builtin.py 冻结) (BEACON 25-26) | 避免 pytest-cov 内存 ×2；builtin.py 运行时 DeprecationWarning |
| 2026-06-26 | v2.3 Wave 2 完成 (CheckpointEnvelope + LLM 评估器) (BEACON 20-24) | 消除 LoopState 双义；ClaudeSemanticEvaluator 默认启用 |
| 2026-06-26 | v2.2 Wave 3 完成 (生产文档 + 闭环) (BEACON 19) | 7 Gates 集成 + CLI v2；项目生产就绪 |
| 2026-06-25 | v2.0 + v2.1 完整演进 (BEACON 11-18) | Channel/TaskDAG/ConvergenceJudge/Orchestrator/7 Gates；atdo Plan 报告内联 smoke test |
| 2026-06-24 | v1.0 基础 + init 21 项修复 + Plan A bug 修复 (BEACON 1-10) | dev-loop 多轮审计；LoopEngine/StageGraph/AgentRuntime + Guardrail/init |

## 待解决问题

[Q?] 是否需要 streaming 进度输出？ — CLI UX | [Q?] JSONL 协议 developer 阶段是否也应走 JSONL？ — 当前走 run_round+agent_runtime, 仍需要 ANTHROPIC_API_KEY

## 引用文件

@design/v5.0-Design-Loop.md · @design/INDEX.md · @docs/EARS-v5.0.md · @docs/api-reference.md · @docs/production-deployment.md
