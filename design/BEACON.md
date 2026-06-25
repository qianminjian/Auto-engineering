> 来源：@design/INDEX.md | 创建：2026-06-24 | 更新：2026-06-25 | 阶段：P1 全部完成（8/8），准备 Phase 2

## 目标与成功标准

1. **ae init 命令**：用户输入 `ae init my-project --type app-service`，产出完整可运行的项目骨架
2. **ae dev-loop 命令**：用户输入需求文本，系统自动完成 Architect → Developer → Critic 循环，输出代码变更 + 测试通过
3. **确定性 Guardrail**：每个 Stage 前后自动检查 Guardrail 条件（结构化 GuardrailResult，pass/block/drop/retry 四态）
4. **Checkpoint 恢复**：中断后可从 checkpoint 恢复，不丢失进度
5. **结构化 Agent 输出**：Agent 输出按 output_schema 约束，双层防御解析（schema + regex fallback）

## 范围边界

**做：**
- init: 多层模板目录组合（_shared + _features + type）、from-answers 恢复、路径穿越防护、内置钩子错误传播
- LoopEngine（while True + tick/after_tick）+ StageGraph + AgentRuntime
- 单 Agent 串行执行、SQLite checkpoint、Claude API output_json
- GuardrailChain + RetryPolicy + CancellationToken + ErrorCode 体系

**不做：**
- init: 增量模式、嵌套模板交互选择、远程模板（v1.1+）
- 多 Agent 并行（v2.0）、多 LLM Provider、Web UI
- CrewAI 风格 Memory/RAG、AutoGen 风格 Pub/Sub、Jinja2 用于 Task 描述

## 设计决策

| # | 决策 | 理由 | 日期 |
|---|------|------|------|
| 1 | 三层架构：LoopEngine → StageGraph → AgentRuntime | 控制流/路由/执行三者职责分离 | 2026-06-24 |
| 2 | 全链路 async | 统一异步模型 | 2026-06-24 |
| 3 | dataclass 非 Pydantic | 核心模型轻量，LLM 输出用 output_schema | 2026-06-24 |
| 4 | GuardrailChain 替代 Gate | 参考 CrewAI GuardrailResult + AutoGen DropMessage | 2026-06-24 |
| 5 | init 审计后优先断路修复 | 3 个断路点使当前 init 代码在真实场景基本不可用 | 2026-06-24 |
| 6 | AnthropicProvider 封装在 llm/ | 不混入 agent 代码，方便测试 mock | 2026-06-24 |
| 7 | Phase 1 编码前先清理现状 | 占位符命名 `DevLoop*` 与 v3.0 `LoopEngine*` 冲突；`crew/contracts/tasks/runtime/registry.py/runtime/messages.py` 应删；SHARED.md 目录结构未同步 v3.0 | 2026-06-24 |
| 8 | render_description 空值整行删除 | v3.0 §3.1 注释承诺"条件逻辑在 render_description 中处理"但未实现；developer 模板 "上一轮审查反馈：{critic_feedback}" 首轮产生空行干扰 LLM | 2026-06-24 |
| 9 | run() 退出前同步 checkpoint.status | v3.0 §2.1 tick() 改 self.status 但不写 checkpoint，LoopResult.status 错位 | 2026-06-24 |
| 10 | developer→critic 边显式注册 | v3.0 §三 build_dev_loop_graph 漏 add_edge，critic 永不调度 | 2026-06-24 |

## 当前状态

**阶段：** init §1.3 接口规范 100% 完成（A1-A7 全部落地 + B1-B3 验证通过 + C1-C2 覆盖补充）

**Plan init-TODO.md 产出（2026-06-24）：**
- Phase 01（A1-A7）：7 atomic commits `00a94bb`/`961ca2a`/`8387bdd`/`ec2e108`/`92c3d32`/`74e16d7`/`e2044d6`
  - A1 增量模式（§1.3.10 P0）/ A2 current_phase 传递 / A3 git 非阻塞 / A4 symlink 处理
  - A5 `_warn_undetectable` / A6 spec-doc glob / A7 package_manager 默认 npm
- Phase 02（B1-B3）：8 项目类型 E2E 全过 / 增量模式幂等验证 / `--skip-tasks` 隔离 pnpm 缺失环境
- Phase 03（C1-C2）：hooks.py 31%→88% / scaffold.py 60%→62% / 11+1 新测试

**状态转换节点**：init 子系统从"§1.3 设计-实现偏差 7 项未修复"→"§1.3 100% 完成"

**下一步**：dev-loop 续做（Plan B.02 中断）或 v1.1 增量优化（per v1.0-INIT.md §1.8 P3/P4）

**Plan A 测试**：40 passed (33 原 + 7 新) in 0.12s
- 新增：B1 interrupt_after_breaks_loop / B3 context_manager_yields_store / B5 name_collision_raises + 2 add_edge tests / B6 resume_with_done_checkpoint_raises + resume_with_pending_checkpoint_works
- 覆盖率：state 100% / messages 100% / checkpoint 89% / graph 95% / loop 82% / errors 87%

**Plan A 审计**：0 blockers, 2 P3 warnings (add_conditional_edge 未做 START/END 守卫 / docstring 命名一致性)。Gate Integration: 0 errors

**v3.0 → v3.1 修复（D1-D6 + B1-B6 全部完成）：**
- D1 §3.1 build_dev_loop_graph 补 developer→critic 边（f4f9b9c 修复）
- D2 §3.1 render_description 空值整行删除（f4f9b9c 修复）
- D3 §2.1 run() 退出前同步 checkpoint.status（f4f9b9c 修复）
- D4 §2.1 run() while 循环 status.startswith('interrupt') 时 break（v1.1 Plan A.01 TDD 修复，test_interrupt_after_breaks_loop）
- D5 §7.4 → §7.4.1 增量差异小节，消除 §2.1 与 §7.4 run() 互指（v1.1 Plan A.01）
- D6 §八 8.1 parse_agent_output 注释说明 partial JSON 处理（v1.1 Plan A.01，Phase 3 实现）
- B1 interrupt_after break（同 D4，复测 PASS）
- B3 CheckpointStore 实现 __enter__/__exit__ context manager（Plan A.02 TDD）
- B5 Stage name collision 防御（add_stage 拒绝 __start__/__end__ / add_edge 拒绝 START sentinel，END sentinel 允许）（Plan A.02 TDD）
- B6 resume() 状态校验（拒绝 done checkpoint；要求 run() 持久化最终 status 到 DB）（Plan A.02 TDD）

**清理（决策 1C）：**
- 删 `crew/`, `contracts/`, `tasks/`, `runtime/registry.py`, `runtime/messages.py`, 旧 `engine/*.py`
- 重写 `runtime/__init__.py`（仅 AgentRuntime）
- 同步 `SHARED.md §三/§七` 对齐 v3.0

**审计报告：**
- `design/v1.0-LOOP-AUDIT.md` — dev-loop 初版（17 优化点）
- `design/v1.0-AUDIT-SUPPLEMENT.md` — dev-loop 补充（10 优化点）
- `design/v1.0-LOOP.md §十一` — dev-loop 第三轮 + 第四轮 bug 修复记录
- `design/v1.0-INIT.md §1.7` — init 实现偏差审计（21 偏差项）
- `design/v1.0-INIT.md §二` — init 修复实施计划

**下一步：** Phase 2 编码（Runtime + Guardrail，~430 行）→ Phase 3 (Agent + 工具 ~1100 行) → Phase 4 (CLI + 可观测性 ~400 行)

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | Plan A bug 修复完成（D1-D6 v3.0 → v3.1） | 第四轮审计发现 6 处设计/代码不一致；D4 interrupt_after TDD 修复，新增 test_interrupt_after_breaks_loop |
| 2026-06-24 | dev-loop Phase 1 编码完成 | 33 测试全绿；v3.0 → v3.1 三处 bug 修复 |
| 2026-06-24 | 现状清理：删 crew/contracts/tasks/runtime/registry+messages；同步 SHARED.md v3.0 | 占位符命名与 v3.0 冲突 + 文档间不一致 |
| 2026-06-24 | init 深度审计：21 个偏差项，设计文档更新 + 修复计划 | 对照设计+实现+Copier/Cookiecutter/Yeoman 源码逐模块检查 |
| 2026-06-24 | dev-loop 第三轮审计：6 设计 bug + 4 缺失维度 | 挑剔的独立审计角度验证可落地性 |
| 2026-06-24 | dev-loop 补充审计：10 个优化点 | 对照 CrewAI/AutoGen/LangGraph 源码补充维度 |
| 2026-06-24 | dev-loop 初始审计：17 个优化点 | 编码前对照源码验证设计质量 |

## 待解决问题

[Q?] 是否需要 streaming 进度输出？— CLI UX 决策
[Q?] `_features/` 的 ae-feature.yml 声明式配置需要什么字段？— R17 实现时确定
[Q?] 增量模式何时排期？— 当前计划 P3（v1.1），可提前如果存量项目接入是刚需

## 引用文件

@design/INDEX.md — 文档索引（含合并日志/归档清单）
@design/v1.0-SHARED.md — 共享架构基线（v3.0 对齐）
@design/v1.0-LOOP.md — dev-loop 子系统设计（v3.0）
@design/v1.0-INIT.md — init 子系统设计 + 实现偏差审计（§1.7）+ 修复计划（§二）
@design/v1.0-TEMPLATES.md — 模板资产定义
@design/v1.1-AUDIT-REPORT.md — 架构审计报告（P0-P2 + 3个附录）
@design/v1.1-UNIFIED-DEV-PLAN.md — 统一开发计划
@design/v1.1-TODO-LIST.md — 当前 TODO 清单
@design/v2.0-LOOP-ANALYSIS.md — v2.0 多 Agent 并发架构
@design/his_bak/ — 历史归档（审计报告/执行计划/设计文档）
@tests/conftest.py — MockRuntime + checkpoint_dir fixture

