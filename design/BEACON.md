> 来源：@design/INDEX.md | 创建：2026-06-24 | 更新：2026-07-04 | 阶段：v5.0 Loop-only (Init Engineering 已拆分独立项目, 见 BEACON 决策 30)

## 目标与成功标准

1. **`/dev-loop` slash command**：用户在 Claude Code 会话中触发 Plugin, 调度 Python Engine 运行 Architect → Developer → Critic 三阶段 Agent 循环
2. **`ae dev-loop` CLI**：Engine 调试入口, stdout JSON 契约
3. **确定性 Guardrail**：每 Stage 前后自动检查（pass/block/drop/retry 四态）
4. **Checkpoint 恢复**：中断后从 checkpoint 恢复, 不丢失进度（SQLite WAL）
5. **结构化 Agent 输出**：双层防御解析（schema + regex fallback）
6. **多 Agent 并发**（v2.0）：Round 内 asyncio.gather + Channel + Task DAG + 文件隔离 + 4 级收敛 + SQLite
7. **7 道 Gate**（v2.0）：safety/lint/type_check/contract/test/coverage/build
8. **Init-Loop 接口契约**（IL.1-IL.6）：消费 Init 项目产出的 `.ae-state/init-manifest.json`, 配置对应 Gate

## 范围边界

**做：** LoopEngine/StageGraph/AgentRuntime；单 Agent 串行 + SQLite checkpoint + Claude output_json；GuardrailChain + RetryPolicy + CancellationToken；v2.0/v2.1 Channel + TaskDAG + check_file_isolation + asyncio.gather + 7 Gates + CLI v2 + Channel 序列化三件套 + load() 完整闭环；Init-Loop 接口契约 (Loop 侧) 定义

**不做：** Init 工程（项目脚手架初始化 = 独立 Init Engineering 项目）；Init 增量/嵌套交互/远程模板（v1.1+）；多 LLM Provider、Web UI；CrewAI Memory/RAG、AutoGen Pub/Sub、Jinja2 用于 Task 描述

**项目结构变化（2026-06-30）**: Init Engineering 拆分独立, 本项目移除 `auto_engineering/init/`(528K) + `design/v5.0-Design-Init.md` + 7 Init 测试. Init 侧按本项目 §IL.1-IL.6 接口契约实现.

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
| 21 | **version_utils.get_new_channel_versions 标记 ⚠️ 死代码 → 模块删除** | 原定义 0 生产引用; 算法 1:1 复制到 `loop/convergence.py::_get_new_channel_versions` (Phase P1-II 迁移, 当前同样 0 引用). v2.5 P0-FINAL+: 删除 `loop/version_utils.py` 模块本身, 死代码在 convergence.py 仍保留作 dormant helper 供未来接 orchestrator.py tick() 时取用. | 2026-06-26 | ✅ |
| 22 | **gates/builtin.py 冻结 — 不再主动开发, 保留为向后兼容** | v2.3 P1-I: builtin.py 文件头添加 ⚠️ 冻结标记, 不新增 Guardrail, 仅修复 bug | 2026-06-26 | ✅ |
| 23 | **P0-A: v2.0 Channel 体系归属 = checkpoint 专用; v2.0 Pydantic LoopState 重命名为 CheckpointEnvelope** | 消除 "LoopState" 同名双义 (engine.state.LoopState v1.0 dataclass 运行时 vs loop.state.LoopState v2.0 Pydantic checkpoint 专用). 详见下方决策 23 展开 | 2026-06-26 | ✅ |
| 24 | **P0-B: engine/checkpoint.py 冻结 — 不再主动开发, 保留仅为向后兼容** | v1.0 CLI (ae checkpoint list/show/resume) 已切到 SQLiteCheckpointStore; engine/checkpoint.py 仍被 engine.loop.LoopEngine (v1.0 runtime) 使用, 因此保留. 文件头加 ⚠️ 冻结标记 (与 builtin.py 决策 22 同模式) | 2026-06-26 | ✅ |
| 25 | **P0-C: CoverageGate (gates/coverage.py) 冻结 — 永远返回 'skip' Verdict, 不阻塞 dev-loop** | 本项目未装 pytest-cov (pyproject.toml addopts 不含 --cov), Gate 永远 'skip: 未提取到覆盖率数据'. 选 (b) 冻结而非 (a) 安装: (a) 装 pytest-cov 会让所有 pytest 跑 ~2x 内存 (CLAUDE.md 16G 内存约束, .claude/rules/pytest-memory-management.md), 真实覆盖率检查应在 CI 独立配置. 文件头加 ⚠️ 冻结标记 + DeprecationWarning 每 5 run 触发 1 次 + 测试保留 verdict.passed 接口 (向后兼容). 与决策 22 (builtin.py) / 24 (engine/checkpoint.py) 同模式 | 2026-06-27 | ✅ |
| 26 | **P1-C: gates/builtin.py 加运行时 DeprecationWarning 信号 (每次 import/check 触发 1 次)** | builtin.py 文件头已有 ⚠️ 冻结标记 (决策 22) 但缺运行时信号. 加 module-level _WARNED flag + _warn_deprecation_once(), 5 个 Guardrail.check() 入口各调用 1 次 (整体守门, 避免刷屏). 引导用户迁移到 v2.0 Gate 体系 (gates/{safety,lint,test,coverage,build,...} 7 道). 与决策 25 (CoverageGate) 同模式 — 简单 module-level 守门, 无需 sys.modules 钩子 (过度设计). 测试: TestBuiltinDeprecationWarning 4 个新用例 (20/20 PASS) | 2026-06-27 | ✅ |
| 27 | **P0-FINAL: v1.0 路径退役 — 撤销决策 11/12/22/24/26** | v2.5 P0-FINAL (commit 2994c7e) 删除 `engine/{loop,graph,checkpoint,messages}.py`、`runtime/mock.py`、`gates/{builtin,guardrail}.py` 及对应测试. **例外**: `engine/state.py` 保留 — 决策 23 重命名生效后, 运行时 Orchestrator / Runtime / Gates 仍走 engine.state.EngineState (LoopState 别名) dataclass, engine.state 是 v2.0 运行时状态容器, 不是 v1.0 遗产. 决策 11/12/22/24/26 关于"冻结/兼容"的策略不再适用 — 这些文件不再存在, v2.5 仅有 v2.0 path. CLI flags `--use-v1` / `--use-v2` 同时移除 (docs 已更新, 见 v2.5-Plan-Dev.md P1-B/P1-C). CoverageGate 冻结 (决策 25) 保留 — 该决策不涉及被删文件, 且 pytest-cov 仍不安装. | 2026-06-28 | ✅ |
| 28 | **v2.5 深度审计 + 25 项修复 (P0×1 + P1×9 + P2×15)** | v2.5 P0-FINAL 合并后做深度审计 (4 个 Sonnet agent 并行 — 架构漂移/测试覆盖/安全/性能). 发现 36 项问题, 全部修完. 关键: D-P0-1 (asyncio.gather 假象 — LLM sync 调用阻塞 event loop, 用 asyncio.to_thread 修), C-P1-1 (macOS symlink 沙箱绕过 — Path.resolve 不展 symlink, 改 realpath 双侧 + lexical fallback), C-P1-2 (Bash shell=True 弱 deny-list — 扩展 6→13 模式 + 审计日志), C-P1-3 (external_data 路径未沙箱 — opt-in sandbox_roots 校验), D-P1-3 (SQLite 每操作 connect/close — 缓存连接 + WAL), D-P1-5 (history 无界 — deque(maxlen=50)), D-P2-1 (Gate 串行 — asyncio.gather 并行 7 个), C-P2-1/2/4 文档化 invariants. 项目健康 6.5/10 → 8.0/10. 全部 564 测试通过, 无回归. | 2026-06-28 | ✅ |
| 29 | **v5.0 路线图: Claude Code plugin 集成 + Loop + Init 合订最终方案** | 详见 `@design/v5.0-Design.md`. 借鉴业界 (LangGraph PregelLoop tick/after_tick / AutoGen MessageEnvelope / CrewAI Guardrail 4 态 / Devin plan-act-observe / Copier 5 阶段 + !include / Cookiecutter progress bar + hooks / Yeoman composable features). 在 v2.5 已有 Python 引擎基础上, plugin 形态 = Bash 委托 `uv run ae <subcommand>`, 控制流仍在 Python (LangGraph 借鉴), Claude 在 agent 里提供 UX. 3 Stage (architect/developer/critic) + 5 Guardrail + 7 Gate = 12 层保险, 8 类型 × 4 语言 = 32 模板组合, SQLite checkpoint 跨 session 持久化, critic_feedback channel 显式反馈回路. 不重写 v2.5 已有引擎, 借鉴保留, plugin 是新 UX 层. | 2026-06-29 | ✅ 设计完成 |
| 30 | **Init Engineering 拆分独立项目** | 2026-06-30 项目结构变化: Init Engineering 拆分独立, 本项目移除 `auto_engineering/init/`(528K) + `design/v5.0-Design-Init.md` + 7 Init 测试. Init 侧按本项目 §IL.1-IL.6 接口契约实现. **2026-07-04 审计修订 (决策 31)**: 实际 init/ 残留 40KB (6 文件) + skill.py (162 行) 死代码, 引用不存在的 detector / _shared 模块. v5.0 深度审计后完整清理. | 2026-06-30 | ✅ |
| 31 | **v5.0 深度审计 + 4 P0 修复 + 决策记录偏差诚实标注** | 2026-07-04 AI 深度审计发现 23 项 (P0×4 + P1×11 + P2×8). 修复 4 P0: (1) `loop/orchestrator.py:152` 错误环境变量名 `KEY` → `ANTHROPIC_API_KEY`/`AUTH_TOKEN` (阻断语义收敛); (2) `loop/semantic_evaluator.py` `__call__` 早期返回 bug + `__init__` 接受 `api_key` 参数 (让 9 个测试通过); (3) `auto_engineering/init/` + `auto_engineering/skill.py` 完整删除 (BEACON 决策 30 修订); (4) `.claude-plugin/plugin.json` 恢复 commands/hooks/skills/metadata 完整字段 (commit 076758b 过度删除). **决策 20 虚报修订**: BEACON 决策 20 声称 "Phase J 默认启用 ClaudeSemanticEvaluator 完成" 实际是虚报, 9 个 semantic_evaluator 测试失败证明. **决策 28 修订**: 564 测试通过无回归声称需复核, 本次修复后预期恢复. `docs/api-reference.md` OrchestratorConfig 示例从 v2.0 风格重写为 v5.0 实际签名 (P0-Doc-01). 详见 `_scratch/audit-2026-07-04/SUMMARY.md`. | 2026-07-04 | ✅ |
| 32 | ~~Agent Tool spec 模式~~ (撤销, 后改为 JSONL 协议) | speculation 模式——dev-loop.md 被 Claude Code agent 读到后自觉执行, agent 可能跳过任何规范串行写代码 | 2026-07-04 | ❌ 撤销 |
| 33 | **Agent-Engine JSONL 通信协议 (v5.1, 2026-07-04, BEACON §C)** | 参考 LangGraph PregelLoop/CrewAI kickoff/AutoGen AgentRuntime 的共同模式 "Python 控制流 + LLM 数据流": Python orchestrator 保留全部 while 循环/收敛/Gate/持久化逻辑, 将 3 个 agent 的 LLM 调用从 SDK 改为 JSONL stdin/stdout 协议——Claude Code agent 响应 JSON 请求后执行 Plan/code-reviewer/developer 任务. 保留全部 12,385 LOC Python 引擎 + 1337 tests. 解决子进程无法获取 ANTHROPIC_AUTH_TOKEN 问题 (Claude Code agent 有完整的 ANTHROPIC_AUTH_TOKEN). 详见 `design/v5.0-Design-Loop.md` §C (Agent-Engine JSONL 通信协议). | 2026-07-04 | ✅ |

## 决策 23 展开: Channel 体系归属 = checkpoint 专用

**问题:** `loop.state.LoopState` (v2.0 Pydantic) 与 `engine.state.LoopState` (v1.0 dataclass) 同名双义. 实际 v2.0 Orchestrator 走 v1.0, v2.0 Pydantic 仅供 checkpoint / v1.1→v2.0 migrate.

**选择 (b) Channel 仅供 checkpoint 专用** — 不强行改造运行时 (会破坏 13+ 文件 v1.0 契约). Pydantic `LoopState` → `CheckpointEnvelope` (明确语义), `loop.__init__` 移除公共导出 (从 API 消除双义).

**借鉴:** LangGraph `State` (Pregel) 既是 envelope 也是 runtime; v2.0 实现只做了 envelope 角色. 决策 23 把"半成品"明确化, 不强行补另一半.

## 当前状态

**阶段：** v5.0 plugin 完整最终方案 (BEACON 决策 29, 借鉴保留 v2.5 决策 1-28)。

**最近动作：** 2026-06-28 v2.5 P0-FINAL + 深度审计修复 — 删除 `auto_engineering/engine/{loop,graph,checkpoint,messages}.py` (engine/state.py 保留作运行时 LoopState/EngineState 容器, 决策 23 命名重构生效) + `runtime/mock.py` + `gates/{builtin,guardrail}.py` 及其 16 测试, 正式撤销决策 11/12/22/24/26 (v1.0 不再保留, 仅有 v2.0 path); CLI flags `--use-v1` / `--use-v2` 同步移除, 文档 (api-reference/production-deployment/e2e-real-run) 标记 "v2.5 起移除"; BEACON 决策 27 记录撤销依据. **深度审计 25 项修复**: D-P0-1 asyncio.gather 真并行 (asyncio.to_thread) / C-P1-1 realpath 沙箱 (macOS symlink 防御) / C-P1-2 Bash 黑名单 6→13 + 审计日志 / C-P1-3 external_data opt-in 沙箱 / D-P1-3 SQLite WAL + 连接缓存 / D-P1-5 history deque(maxlen=50) / D-P2-1 Gate 平行 7 个 / 9 个测试文件 (engine_state / parser / git_tools / checkpoint_envelope / config_loader / 22 ErrorCode / init_config_loader / envelope / engine_state 等). 项目健康 6.5/10 → 8.0/10; 564 测试通过. `_scratch/` gitignore 保留, `references/` gitignore 保留 (96GB 内存事故防线).

**下一步：** v2.5 P0-FINAL 完成后 → 用户 manual gate 决策 v2.5 → 是否启动 v3.0 (production hardening / 真跑验证 / Web UI)？

**阻塞项：** 无

**v2.0/v2.1 里程碑：** Phase 01（`c3077bf`/`3857366`/`73ee4bc`）Channel + LoopState；Phase 02（`1dd2ff8`/`4038ca2`/`704987d`）ConvergenceJudge + SQLite；Phase 03（`4f3d932`/`3a3edd1`/`23584b6`）TaskDAG + check_file_isolation + Orchestrator；Phase 04（`feb4af8`→`da759cd`）7 Gates + CLI v2；v2.1 Phase A（`71434bc`/`364c7ad`/`e938e72`）Channel 序列化三件套；Phase B（`337fcc1`/`a99b60a`）Orchestrator Gate+LLM 集成；Phase C（`a8ba445`/`eebcfb1`/`739330d`）CLI 集成 v2；Phase D（`7c63a91`/`4ea0ec9`）字段补全 + load() 重建。

**v2.0 删除项取消（决策 11/12，2026-06-25 → 2026-06-28 撤销）：** 决策 11/12 已被决策 27 撤销，原始"保留 engine/runtime/tools 作为旧路径兼容"策略不再适用 — engine/* + runtime/mock.py + gates/{builtin,guardrail}.py 全部退役 (commit 2994c7e)。v2.5 纯 v2.0 path。详见 v2.0-Design-Loop.md §一（历史参考）。

**v1.1/init 修复：** D1-D6 + B1-B6 全完（Plan A 40 测试全过，覆盖率 state 100% / messages 100% / checkpoint 89% / graph 95% / loop 82%）；init 21 偏差项 + 8 项目类型 E2E + hooks 31%→88%。详见 v1.1-Plan-Dev.md + v1.0-Design-Init.md §1.7-§1.9。

**v2.5 P0-FINAL（决策 27）：** v1.0 engine/{loop,graph,checkpoint,messages}.py + runtime/mock.py + gates/{builtin,guardrail}.py 全部退役. **engine/state.py 保留** — 决策 23 重命名生效, 运行时 Orchestrator / Runtime / Gates 仍走 engine.state.EngineState (LoopState 别名) dataclass; engine.state 仍为 v2.0 path 的运行时状态容器, 不是 v1.0 遗产. CLI flags --use-v1/--use-v2 不再支持. v2.5 仅有 v2.0 path, 详见 v2.5-Plan-Dev.md.

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-04 | **v5.0 深度审计 + 4 P0 修复 (BEACON 决策 31)** | AI 静态审计 23 项问题 (P0×4+P1×11+P2×8). 关键修复: orchestrator.py:152 KEY 错误 (语义收敛阻断) + semantic_evaluator.py __call__ 早期返回 bug (9 测试失败) + init/ + skill.py 完整删除 (BEACON 决策 30 修订) + plugin.json 恢复完整字段. BEACON 决策 20/28 诚实标注偏差. 详见 `_scratch/audit-2026-07-04/`. |
| 2026-06-28 | v2.5 深度审计 + 25 项修复 (BEACON 决策 28) | 4 个 Sonnet agent 并行扫描架构/测试/安全/性能. 修 P0×1 (asyncio.gather 假象) + P1×9 (realpath/Bash 沙箱/external_data 等) + P2×15 (SQLite WAL/history cap/平行 gates/4 个新测试文件). 项目健康 6.5/10 → 8.0/10. 564 测试通过. |
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
