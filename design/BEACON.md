> 来源：@design/INDEX.md | 创建：2026-06-24 | 更新：2026-06-28 | 阶段：v2.5 P0-FINAL 完成 (v1.0 退役 + BEACON 决策 27)

## 目标与成功标准

1. **ae init 命令**：`ae init my-project --type app-service` 产出完整可运行项目骨架
2. **ae dev-loop 命令**：需求文本输入后自动完成 Architect → Developer → Critic 循环
3. **确定性 Guardrail**：每 Stage 前后自动检查（pass/block/drop/retry 四态）
4. **Checkpoint 恢复**：中断后从 checkpoint 恢复，不丢失进度
5. **结构化 Agent 输出**：双层防御解析（schema + regex fallback）
6. **多 Agent 并发**（v2.0）：Round 内 asyncio.gather + Channel + Task DAG + 文件隔离 + 4 级收敛 + SQLite
7. **7 道 Gate**（v2.0）：safety/lint/type_check/contract/test/coverage/build

## 范围边界

**做：** init 多层模板组合 + 路径穿越防护 + 钩子错误传播；LoopEngine/StageGraph/AgentRuntime；单 Agent 串行 + SQLite checkpoint + Claude output_json；GuardrailChain + RetryPolicy + CancellationToken；v2.0/v2.1 Channel + TaskDAG + check_file_isolation + asyncio.gather + 7 Gates + CLI v2 + Channel 序列化三件套 + load() 完整闭环

**不做：** init 增量/嵌套交互/远程模板（v1.1+）；多 LLM Provider、Web UI；CrewAI Memory/RAG、AutoGen Pub/Sub、Jinja2 用于 Task 描述

## 设计决策

| #  | 决策 | 理由 | 日期 | status |
|----|------|------|------|--------|
| 1-7  | v1.0 基础架构（LoopEngine/StageGraph/AgentRuntime + async + dataclass + GuardrailChain + init 断路修复 + llm/ 封装 + 现状清理） | 控制流/路由/执行分离；参考 CrewAI GuardrailResult + AutoGen DropMessage | 2026-06-24 | ✅ |
| 8  | render_description 空值整行删除 | 注释承诺"条件逻辑在 render_description 中处理"未实现 | 2026-06-24 | ✅ |
| 9  | run() 退出前同步 checkpoint.status | tick() 改 self.status 但不写 checkpoint | 2026-06-24 | ✅ |
| 10 | developer→critic 边显式注册 | build_dev_loop_graph 漏 add_edge，critic 永不调度 | 2026-06-24 | ✅ |
| 11 | **v2.0 是增量式演进，不是删除式重构** | 在 engine/runtime/tools 基础上**新增** loop/ 子系统 | 2026-06-25 | ✅ |
| 12 | **v2.0 删除项取消：保留 engine/runtime/tools 作为旧路径兼容** | CLI 仍 import 旧路径，v2.0 loop/ 是叠加而非替代 | 2026-06-25 | ✅ |
| 13 | **Channel 系统采用 Pydantic BaseModel (LoopState 容器) + Channel 抽象基类 (Python ABC)** | LoopState 用 Pydantic；Channel 基类用 ABC | 2026-06-25 | ✅ |
| 13a | v2.1 修订: 决策 13 修正 — 原写"dataclass"与实际不符 | 修正记录 | 2026-06-25 | ✅ |
| 14 | **check_file_isolation 是确定性检查，不是 LLM 自检** | Orchestrator 规划阶段 Python 代码检查 | 2026-06-25 | ✅ |
| 15 | **Gate 3（Contract）单 Agent 跳过，多 Agent 启用** | Phase 04 决策 | 2026-06-25 | ✅ |
| 16 | **Channel 序列化三件套: copy/from_checkpoint/checkpoint (LangGraph 对齐)** | v2.1 Phase A 修复 BarrierChannel 重构 | 2026-06-25 | ✅ |
| 17 | **SQLiteCheckpointStore.load() 必须返回 LoopState 实例 + Channel 实例 (完整闭环)** | v2.1 Phase D 修复 | 2026-06-25 | ✅ |
| 18 | **atdo Plan 报告必须含 runtime smoke 验证 (防止虚化测试)** | v2.1 强制 inline smoke test | 2026-06-25 | ✅ |
| 19 | **v2.2 闭环完成 + 生产就绪** | Wave 3 P2 改进 + atdo 防护规则化 | 2026-06-26 | ✅ |
| 20 | **v2.3 Wave 2 完成: Orchestrator 集成 LLM SemanticEvaluator (Claude)** | Phase J 实现, 第 4 级语义收敛生效 | 2026-06-26 | ✅ |
| 21 | **version_utils.get_new_channel_versions 标记 ⚠️ 死代码** | 定义存在 + 有测试, 但 0 生产引用; 文件头标记死代码, 从 __all__ 移除 | 2026-06-26 | ✅ |
| 22 | **gates/builtin.py 冻结 — 不再主动开发, 保留为向后兼容** | v2.3 P1-I: builtin.py 文件头添加 ⚠️ 冻结标记, 不新增 Guardrail, 仅修复 bug | 2026-06-26 | ✅ |
| 23 | **P0-A: v2.0 Channel 体系归属 = checkpoint 专用; v2.0 Pydantic LoopState 重命名为 CheckpointEnvelope** | 消除 "LoopState" 同名双义 (engine.state.LoopState v1.0 dataclass 运行时 vs loop.state.LoopState v2.0 Pydantic checkpoint 专用). 详见下方决策 23 展开 | 2026-06-26 | ✅ |
| 24 | **P0-B: engine/checkpoint.py 冻结 — 不再主动开发, 保留仅为向后兼容** | v1.0 CLI (ae checkpoint list/show/resume) 已切到 SQLiteCheckpointStore; engine/checkpoint.py 仍被 engine.loop.LoopEngine (v1.0 runtime) 使用, 因此保留. 文件头加 ⚠️ 冻结标记 (与 builtin.py 决策 22 同模式) | 2026-06-26 | ✅ |
| 25 | **P0-C: CoverageGate (gates/coverage.py) 冻结 — 永远返回 'skip' Verdict, 不阻塞 dev-loop** | 本项目未装 pytest-cov (pyproject.toml addopts 不含 --cov), Gate 永远 'skip: 未提取到覆盖率数据'. 选 (b) 冻结而非 (a) 安装: (a) 装 pytest-cov 会让所有 pytest 跑 ~2x 内存 (CLAUDE.md 16G 内存约束, .claude/rules/pytest-memory-management.md), 真实覆盖率检查应在 CI 独立配置. 文件头加 ⚠️ 冻结标记 + DeprecationWarning 每 5 run 触发 1 次 + 测试保留 verdict.passed 接口 (向后兼容). 与决策 22 (builtin.py) / 24 (engine/checkpoint.py) 同模式 | 2026-06-27 | ✅ |
| 26 | **P1-C: gates/builtin.py 加运行时 DeprecationWarning 信号 (每次 import/check 触发 1 次)** | builtin.py 文件头已有 ⚠️ 冻结标记 (决策 22) 但缺运行时信号. 加 module-level _WARNED flag + _warn_deprecation_once(), 5 个 Guardrail.check() 入口各调用 1 次 (整体守门, 避免刷屏). 引导用户迁移到 v2.0 Gate 体系 (gates/{safety,lint,test,coverage,build,...} 7 道). 与决策 25 (CoverageGate) 同模式 — 简单 module-level 守门, 无需 sys.modules 钩子 (过度设计). 测试: TestBuiltinDeprecationWarning 4 个新用例 (20/20 PASS) | 2026-06-27 | ✅ |
| 27 | **P0-FINAL: v1.0 路径退役 — 撤销决策 11/12/22/24/26** | v2.5 P0-FINAL (commit 2994c7e) 删除 `engine/{loop,graph,checkpoint,messages}.py`、`runtime/mock.py`、`gates/{builtin,guardrail}.py` 及对应测试. 决策 11/12/22/24/26 关于"冻结/兼容"的策略不再适用 — 这些文件不再存在, v2.5 仅有 v2.0 path. CLI flags `--use-v1` / `--use-v2` 同时移除 (docs 已更新, 见 v2.5-Plan-Dev.md P1-B/P1-C). CoverageGate 冻结 (决策 25) 保留 — 该决策不涉及被删文件, 且 pytest-cov 仍不安装. | 2026-06-28 | ✅ |

## 决策 23 展开: Channel 体系归属 = checkpoint 专用

**问题:** `loop.state.LoopState` (v2.0 Pydantic) 与 `engine.state.LoopState` (v1.0 dataclass) 同名双义. 实际 v2.0 Orchestrator 走 v1.0, v2.0 Pydantic 仅供 checkpoint / v1.1→v2.0 migrate.

**选择 (b) Channel 仅供 checkpoint 专用** — 不强行改造运行时 (会破坏 13+ 文件 v1.0 契约). Pydantic `LoopState` → `CheckpointEnvelope` (明确语义), `loop.__init__` 移除公共导出 (从 API 消除双义).

**借鉴:** LangGraph `State` (Pregel) 既是 envelope 也是 runtime; v2.0 实现只做了 envelope 角色. 决策 23 把"半成品"明确化, 不强行补另一半.

## 当前状态

**阶段：** v2.5 P0-FINAL 完成（v1.0 退役 + BEACON 决策 27）。

**最近动作：** 2026-06-28 v2.5 P0-FINAL 完成 — 删除 `auto_engineering/engine/` 全部 (loop/graph/checkpoint/messages) + `runtime/mock.py` + `gates/{builtin,guardrail}.py` 及其 16 测试, 正式撤销决策 11/12/22/24/26 (v1.0 不再保留, 仅有 v2.0 path); CLI flags `--use-v1` / `--use-v2` 同步移除, 文档 (api-reference/production-deployment/e2e-real-run) 标记 "v2.5 起移除"; BEACON 决策 27 记录撤销依据; `_scratch/` gitignore 保留, `references/` gitignore 保留 (96GB 内存事故防线).

**下一步：** v2.5 P0-FINAL 完成后 → 用户 manual gate 决策 v2.5 → 是否启动 v3.0 (production hardening / 真跑验证 / Web UI)？

**阻塞项：** 无

**v2.0/v2.1 里程碑：** Phase 01（`c3077bf`/`3857366`/`73ee4bc`）Channel + LoopState；Phase 02（`1dd2ff8`/`4038ca2`/`704987d`）ConvergenceJudge + SQLite；Phase 03（`4f3d932`/`3a3edd1`/`23584b6`）TaskDAG + check_file_isolation + Orchestrator；Phase 04（`feb4af8`→`da759cd`）7 Gates + CLI v2；v2.1 Phase A（`71434bc`/`364c7ad`/`e938e72`）Channel 序列化三件套；Phase B（`337fcc1`/`a99b60a`）Orchestrator Gate+LLM 集成；Phase C（`a8ba445`/`eebcfb1`/`739330d`）CLI 集成 v2；Phase D（`7c63a91`/`4ea0ec9`）字段补全 + load() 重建。

**v2.0 删除项取消（决策 11/12，2026-06-25 → 2026-06-28 撤销）：** 决策 11/12 已被决策 27 撤销，原始"保留 engine/runtime/tools 作为旧路径兼容"策略不再适用 — engine/* + runtime/mock.py + gates/{builtin,guardrail}.py 全部退役 (commit 2994c7e)。v2.5 纯 v2.0 path。详见 v2.0-Design-Loop.md §一（历史参考）。

**v1.1/init 修复：** D1-D6 + B1-B6 全完（Plan A 40 测试全过，覆盖率 state 100% / messages 100% / checkpoint 89% / graph 95% / loop 82%）；init 21 偏差项 + 8 项目类型 E2E + hooks 31%→88%。详见 v1.1-Plan-Dev.md + v1.0-Design-Init.md §1.7-§1.9。

**v2.5 P0-FINAL（决策 27）：** v1.0 engine/* + runtime/mock.py + gates/{builtin,guardrail}.py 全部退役. CLI flags --use-v1/--use-v2 不再支持. v2.5 仅有 v2.0 path, 详见 v2.5-Plan-Dev.md.

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-28 | v2.5 P0-FINAL 完成 (v1.0 退役 + BEACON 决策 27) | 删除 engine/* + runtime/mock.py + gates/{builtin,guardrail}.py + 16 测试. 决策 11/12/22/24/26 关于"冻结/兼容"不再适用. CLI flags --use-v1/--use-v2 同步移除. v2.5 纯 v2.0 path. |
| 2026-06-27 | v2.4 P1-C 完成 (builtin.py 运行时 DeprecationWarning + BEACON 决策 26) | builtin.py 文件头已有 ⚠️ 冻结标记 (决策 22) 但缺运行时信号. 加 module-level _WARNED flag + _warn_deprecation_once(), 5 个 Guardrail.check() 入口各调 1 次, 引导用户迁移到 v2.0 Gate 体系. 与决策 25 (CoverageGate) 同模式 |
| 2026-06-27 | v2.4 P0-C 完成 (CoverageGate 冻结 + DeprecationWarning + BEACON 决策 25) | 本项目未装 pytest-cov, Gate 永远 'skip'. 选冻结而非安装 (避免 pytest 内存翻倍爆 16G). 真实覆盖率走 CI 独立 job. |
| 2026-06-26 | v2.3 P0-B 完成 (v1.0 CLI list/show/resume 切到 SQLiteCheckpointStore, engine/checkpoint.py 冻结, BEACON 决策 24) | 统一 CLI backend: v1.0 与 v2 命令共用 SQLiteCheckpointStore; 旧 engine.checkpoint 保留兼容 (v1.0 runtime 仍用), 文件头加 ⚠️ 标记 |
| 2026-06-26 | v2.3 P0-A 完成 (LoopState → CheckpointEnvelope 重命名, Channel 体系归属 = checkpoint 专用, BEACON 决策 23) | 消除 LoopState 同名双义 (engine.state v1.0 vs loop.state v2.0). 13 文件 import 同步, 160+ 测试全 PASS |
| 2026-06-26 | v2.3 Phase J 完成（ClaudeSemanticEvaluator + OrchestratorConfig 默认 + BEACON 决策 20） | Wave 2 FINAL：内置 LLM 评估器 (P1.6)，第 4 级语义收敛开箱即用 |
| 2026-06-26 | v2.3 Phase E-I 完成 | max_iterations 单一来源 (P1.1) + exclude_callback (P1.2) + RoundResult.history (P1.3) + AgentRuntime 集成 (P1.4) + init 拆 8 模块 |
| 2026-06-26 | v2.2 Phase J 完成（生产文档 4 件 + BEACON 决策 19） | Wave 3 FINAL：production deployment / troubleshooting / api-reference / e2e-real-run |
| 2026-06-26 | v2.2 Phase G-I 完成 | Checkpoint.state Protocol+Generic + RoundResult Gate 集成 + init 拆 8 模块 |
| 2026-06-25 | v2.1 Phase F 完成（atdo 报告虚报防护 P1.6 FINAL） | Phase 1 审计：Plan 报告虚化案例全记录 + Runtime Smoke Policy 永久资产 + smoke helper 工具 |
| 2026-06-25 | v2.1 Phase A-D 修复完成（4 项 P0 阻断） | Phase 1 审计：Channel 序列化缺/Orchestrator 集成缺/CLI 未接 v2/字段不全 |
| 2026-06-25 | v2.0 全部完成（Phase 01-04）+ 决策 11/12 | v2.0 增量式演进 |
| 2026-06-25 | v1.1 计划 Phase 0-4 全完成 + 文档命名重构 + R26 init 模板 design 嵌入 | 见 v1.1-Plan-Dev.md §一，9 项全部关闭 |
| 2026-06-24 | Plan A bug 修复（D1-D6 v3.0 → v3.1） | 第四轮审计 6 处不一致 |
| 2026-06-24 | init 深度审计 21 项；dev-loop 多轮审计 17+10+6 项 | 对照设计+实现+Copier/Cookiecutter/Yeoman 源码 |

## 待解决问题

[Q?] 是否需要 streaming 进度输出？— CLI UX 决策 | [Q?] `_features/ae-feature.yml` 字段？— R17 实现时确定 | [Q?] 增量模式何时排期？— 当前 P3（v1.1）

## 引用文件

@design/INDEX.md · @design/v1.0-Design-Shared.md · @design/v1.0-Design-Loop.md · @design/v1.0-Design-Init.md · @design/v1.0-Design-Templates.md · @design/v1.1-Audit-Report.md · @design/v1.1-Plan-Dev.md · @design/v2.0-Analysis-Loop.md · @design/v2.0-Design-Loop.md · @design/v2.3-Plan-Dev.md · @design/v2.4-Plan-Dev.md · @design/v2.5-Plan-Dev.md · @design/his_bak/ · @tests/conftest.py
