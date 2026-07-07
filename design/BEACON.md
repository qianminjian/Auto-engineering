> 创建：2026-06-24 | 更新：2026-07-06 | 阶段：v5.5 Design (DeepAudit 扩展设计)

## 目标与成功标准

1. **`/ae:dev-loop` slash command**：用户触发 Plugin → Python Orchestrator 执行 Architect→Developer→Critic 三阶段 Agent 循环
2. **`ae dev-loop` CLI**：调试入口, stdout JSON 契约 (6 字段)
3. **确定性 Guardrail**：每 Stage 前后自动检查 (G1-G5, pass/block/retry 三态)
4. **Checkpoint 恢复**：SQLite WAL 持久化, 中断可恢复
5. **8 道 Gate**（v5.5）：DEFAULT_GATES 7 道: safety → lint → type_check → audit → contract → test → build；按需 Gate 1 道: deep_audit（仅 critic APPROVE 时触发）
6. **Init-Loop 接口契约**（IL.1-IL.6）：消费 Init 项目 `.ae-state/init-manifest.json`

## 范围边界

**做：** Python Orchestrator 12 步主循环；Agent Tool 直接执行模式 (architect/critic/developer 统一走 AgentRuntime 路径)；GuardrailChain + 8 Gates + StageRouter + ConvergenceJudge + SQLite checkpoint；Agent Working Agreements Hook；Init-Loop 接口契约
**不做：** Init Engineering（独立项目）；多 LLM Provider（--llm-provider 选项仅 anthropic，为预留扩展点）、Web UI、SaaS 服务端

## 设计决策

| #  | 决策 | 理由 | 日期 | status |
|----|------|------|------|--------|
| 1-28 | v1.0 → v2.5 完整演进 | LoopEngine/StageGraph/AgentRuntime → Channel/TaskDAG/ConvergenceJudge → Gates/CLI → v1.0 退役 | 2026-06-24→28 | ✅ |
| 29 | **v5.0 路线图: Plugin + Loop + Init 合订** | Plugin 形态 = Bash 委托 `uv run ae <subcommand>`, 控制流在 Python, 参考 LangGraph/AutoGen/CrewAI | 2026-06-29 | ✅ |
| 30 | **Init Engineering 拆分独立项目** | 移除 init/ (528K), 项目只保留 Loop, Init 按 §IL.1-IL.6 实现 | 2026-06-30 | ✅ |
| 31 | **v5.0 深度审计 + 4 P0 修复** | KEY 错误/语义评估器早期返回/init 残留/plugin.json 恢复 (23 项, P0×4) | 2026-07-04 | ✅ |
| 32 | ~~Agent Tool spec 模式~~ (撤销) | Agent 可能跳过规范, markdown 规则无法强制执行 → 改为 JSONL | 2026-07-04 | ❌ |
| 33 | ~~Agent-Engine JSONL 通信协议~~ (已废弃) | Python orchestrator 保留全控制流, architect/critic LLM 走 JSONL stdin/stdout. v5.4 移除 JSONL 路径, 改为 Agent Tool 直接执行模式 | 2026-07-04 | ❌ |
| **34** | ~~AE_JSONL_MODE 条件开关~~ (已废弃) | JSONL 路径仅在 `AE_JSONL_MODE=1` 时启用. v5.4 删除 `_orchestrator_agent.py` + 所有 AE_JSONL_MODE 引用 | 2026-07-05 | ❌ |
| **35** | **GuardrailChain.default() 工厂 + _tasks_from_batch_plan 接入** | guardrail.py 加 default() 返回 5 Guardrail 链；orchestrator 架构师响应中 batch_plan 接入 _tasks_from_batch_plan → developer tasks | 2026-07-05 | ✅ |
| **36** | **TDDGate + StageTransitionGate（借鉴 CrewAI + SonarQube）** | CrewAI GuardrailResult(success/result/error) 三态 + SonarQube 条件门禁模式；TDDGate 强制 Red→Green→Refactor, StageTransitionGate 检查阶段过渡前置条件. v5.4 已删除 — 两者实现的是有状态 Guardrail 检查而非无状态 Gate, 与 Gate.run() 接口不兼容 | 2026-07-05 | ❌ (superseded) |
| **38** | **v5.5 DeepAudit 扩展设计 (T9 plan-refine 回路) + Superpowers 工具集整合** | critic APPROVE 后触发 DeepAuditGate (3-agent 并行全量代码审计), P0>0 或 P1>阈值 → T9 回到 architect 修正计划; P1 阈值从 6 开始自动学习; Architect 集成 Agent-Reach + brainstorming 设计流程; max_iter 从运行日志自动评估; 明确 Python 控制流 vs LLM 推理边界; 整合 Superpowers 5 个 skill (code-reviewer.md 模板 → Critic+DeepAudit, receiving-code-review → Developer, brainstorming+writing-plans → Architect) | 2026-07-06 | ✅ |

## 当前状态

**阶段：** v5.5 Design — DeepAudit Gate + T9 plan-refine 回路设计完成。

**最近动作 (2026-07-07)：**
- **v5.5 设计文档三轮深度审计 + 修复**: 审计报告 `_scratch/reports/2026-07-07-audit-v5.5-design.md` (第一轮, 7.2→7.8) + `round2` (第二轮, 7.8→8.2) + `round3` (第三轮, 8.2→预估 8.5+)。修复 8 P0 + 18 P1 + 5 P2:
  - **第一轮 (3 P0 + 8 P1)**: B7.1 DeepAuditGate+T9+DocSync步骤 / B2.2 StageRouter签名 / PART C废弃标注 / B3.1 T9触发归属 / DeepAuditGate不注册DEFAULT_GATES / B1.1字段18-19 / P1阈值公式p75 / severity映射 / Architect自动化子规则 / Design Doc Sync步骤 / D.3c隔离边界 / IMPL-PLAN Task 1.2+4.2
  - **第二轮 (2 P0 + 4 P1 + 3 P2)**: B7.1 all_gates_passed变量定义 / B2b.2 T9数据流路径 / B2b.3 TaskContext条件化 / T9 batch_plan重转换 / B2b.1 previous_plan幽灵字段 / IMPL-PLAN依赖图+Task 2.3步骤引用
  - **第三轮 (3 P0 + 6 P1 + 2 P2)**: D.3a/D.3b触发归属+幽灵字段同步 / IMPL-PLAN Phase 2头注释 / B4.1a/B6.5e/D.5/IMPL-PLAN 共11处 previous_plan→state.plan 命名统一 / Task 2.3方法名+Task 2.4标题更新
- **Pre-v5.5 全量代码审计 + IMPL-PLAN Phase 0**: 全量审计确认所有 v5.0 核心基础设施 (Gates/Guardrail/Checkpoint/CLI/Orchestrator) 均为真实实现无 stub。发现 4 项遗留问题: doctor.py _check_api_key 未调用 / semantic_evaluator 模型名不完整 / CLAUDE.md authz 工具数 9→10 / errors.py 3 保留 ErrorCode 确认有意设计。排入 IMPL-PLAN Phase 0 (4 Task)

**下一步：** Phase 0 清理 (4 Task) → DeepAuditGate 骨架 (Phase 1) → Orchestrator 集成 (Phase 2) → Architect 扩展 (Phase 3) → 学习系统 (Phase 4) → E2E 验证 (Phase 5)

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-07 | **v5.5 设计文档三轮审计修复 (8 P0 + 18 P1 + 5 P2) + 实施计划全面更新 + Pre-v5.5 代码审计 + Phase 0 清理任务** | 三轮审计: 控制流补全→数据流一致→章节同步。IMPL-PLAN 扩展为 6 Phase 26 Task: +Phase 0 清理(4) +EngineState(2.0) +severity映射(2.3b) +DocSync骨架(2.6) +batch_plan扩展(3.5) +E2E验证(Phase 5); 全量代码审计确认 v5.0 核心无 stub; +设计→任务对照表 +未覆盖项owner追踪 |
| 2026-07-06 | **v5.5 DeepAudit 扩展设计** | T9 plan-refine 回路 (DeepAudit → architect); P1 阈值自学习; Agent-Reach 集成; max_iter 自适应; Python/LLM 边界映射 |
| 2026-07-06 | **v5.4 JSONL 协议移除 + BEACON 同步 + P0 dead code 清理** | JSONL 路径 (`_orchestrator_agent.py`) 已删除；BEACON.md 移除 7 处 JSONL 引用；`_derive_status` dead code 清理 |
| 2026-07-05 | **v5.1 JSONL 集成修复 + Quality Gates + Hook** (BEACON 34-37) | JSONL 25 测试全修复；借鉴 CrewAI/SonarQube/pre-commit 实现 TDDGate/StageTransitionGate/Agent Working Agreements；DEFAULT_GATES 7→9 |
| 2026-07-04 | **v5.0 深度审计 23 项 + 4 P0 修复 + Agent-Engine JSONL 协议** (BEACON 31-33) | KEY 错误/语义评估 bug/init 清理/plugin.json 恢复；Agent Tool spec → JSONL 协议 |
| 2026-06-28 | v2.5 P0-FINAL (v1.0 退役) + 深度审计 25 项 (BEACON 27-28) | engine/* + gates/{builtin,guardrail}.py 退役；asyncio.to_thread 真并行；SQLite WAL；项目健康 6.5→8.0 |
| 2026-06-27 | v2.4 P0-C + P1-C (CoverageGate/builtin.py 冻结) (BEACON 25-26) | 避免 pytest-cov 内存 ×2；builtin.py 运行时 DeprecationWarning |
| 2026-06-26 | v2.3 Wave 2 完成 (CheckpointEnvelope + LLM 评估器) (BEACON 20-24) | 消除 LoopState 双义；ClaudeSemanticEvaluator 默认启用 |
| 2026-06-26 | v2.2 Wave 3 完成 (生产文档 + 闭环) (BEACON 19) | 7 Gates 集成 + CLI v2；项目生产就绪 |
| 2026-06-25 | v2.0 + v2.1 完整演进 (BEACON 11-18) | Channel/TaskDAG/ConvergenceJudge/Orchestrator/7 Gates；atdo Plan 报告内联 smoke test |
| 2026-06-24 | v1.0 基础 + init 21 项修复 + Plan A bug 修复 (BEACON 1-10) | dev-loop 多轮审计；LoopEngine/StageGraph/AgentRuntime + Guardrail/init |

## 待解决问题

[Q?] DeepAuditGate 3-agent spawn 在子进程中的可行性 — 需验证 ae 子进程能否 spawn agent | [Q?] P1 阈值初始 6 是否合理 — 需 10+ 次真实运行后学习调整

## 引用文件

@design/v5.0-Design-Loop.md · @design/INDEX.md · @docs/EARS-v5.0.md · @docs/api-reference.md · @docs/production-deployment.md
