<<<<<<< HEAD
> 来源：@design/INDEX.md | 创建：2026-06-24 | 更新：2026-06-30 | 阶段：v5.0 Loop-only (Init Engineering 已拆分独立项目, 见 BEACON 决策 30)

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
| 29 | **v5.0 路线图: Claude Code plugin 集成 + Loop + Init 合订最终方案** | 详见 `@design/v5.0-Design.md`. 借鉴业界 (LangGraph PregelLoop tick/after_tick / AutoGen MessageEnvelope / CrewAI Guardrail 4 态 / Devin plan-act-observe / Copier 5 阶段 + !include / Cookiecutter progress bar + hooks / Yeoman composable features). 在 v2.5 已有 Python 引擎基础上, plugin 形态 = Bash 委托 `uv run ae <subcommand>`, 控制流仍在 Python (LangGraph 借鉴), Claude 在 agent 里提供 UX. 3 Stage (architect/developer/critic) + 5 Guardrail + 7 Gate = 12 层保险, 8 类型 × 4 语言 = 32 模板组合, SQLite checkpoint 跨 session 持久化, critic_feedback channel 显式反馈回路. 不重写 v2.5 已有引擎, 借鉴保留, plugin 是新 UX 层. | 2026-06-29 | ⏳ 设计中 |

## 决策 23 展开: Channel 体系归属 = checkpoint 专用

**问题:** `loop.state.LoopState` (v2.0 Pydantic) 与 `engine.state.LoopState` (v1.0 dataclass) 同名双义. 实际 v2.0 Orchestrator 走 v1.0, v2.0 Pydantic 仅供 checkpoint / v1.1→v2.0 migrate.

**选择 (b) Channel 仅供 checkpoint 专用** — 不强行改造运行时 (会破坏 13+ 文件 v1.0 契约). Pydantic `LoopState` → `CheckpointEnvelope` (明确语义), `loop.__init__` 移除公共导出 (从 API 消除双义).

**借鉴:** LangGraph `State` (Pregel) 既是 envelope 也是 runtime; v2.0 实现只做了 envelope 角色. 决策 23 把"半成品"明确化, 不强行补另一半.

## 当前状态

**阶段：** v5.0 plugin 完整最终方案 (BEACON 决策 29, 借鉴保留 v2.5 决策 1-28)。
=======
> 创建：2026-06-24 | 更新：2026-06-30 | 阶段：v5.0 Init Engineering（Agent Skill 模式）

## 目标与成功标准

1. **Agent Skill 模式运行**：`ae init` 作为 Claude Code Skill 在 agent 里调用，为 agent 工作流提供项目环境初始化能力
2. **存量项目自动初始化**：通过代码分析自动识别项目类型、依赖、配置，生成正确的初始化配置
3. **新项目向导初始化**：交互式询问确认项目方向、技术栈、目录结构，生成定制化项目骨架
4. **模板组合引擎**：8 类型 × 4 语言 = 32 种模板组合，覆盖 app-service/cli/library/package 四类
5. **路径穿越防护**：!include 路径必须在项目根内，禁止 `..` 逃逸
6. **钩子错误传播**：模板渲染失败时错误信息可追踪到具体文件和行号

## 范围边界

**做：**
- Agent Skill 模式：`ae init` 作为 Claude Code Skill 在 agent 里调用
- 存量项目初始化：代码分析 → 自动识别 → 自动化配置
- 新项目向导：交互式询问 → 确认方向 → 生成骨架
- init 模板体系：43 个模板文件 + `ae-template.yml` 8 字段
- 路径穿越防护 + 钩子错误传播
- `ae init` CLI 命令
- 项目类型：app-service / cli / library / package
- 技术栈：Python / TypeScript / JavaScript / Go

**不做：**
- dev-loop 开发循环（Loop Engineering 已裁剪）
- 多 LLM Provider 支持
- Web UI 界面
- 远程模板 / 嵌套交互
- CrewAI Memory/RAG、AutoGen Pub/Sub、Jinja2 用于 Task 描述

## 设计决策

| # | 决策 | 理由 | 日期 | status |
|---|------|------|------|--------|
| 1 | **v5.0 精简：只保留 Init 部分，Loop 部分裁剪** | 项目聚焦 Init 工程，Loop 功能不在本项目范围 | 2026-06-30 | ✅ |
| 2 | **Agent Skill 模式：init 作为 agent 内 skill 运行** | agent 工作流中需要项目初始化能力 | 2026-06-30 | ✅ |
| 3 | **存量项目：代码分析驱动自动初始化** | 减少人工配置成本，通过分析现有代码推断正确配置 | 2026-06-30 | ✅ |
| 4 | **新项目：向导式询问确认方向** | 新项目方向不明确，需要交互式确认 | 2026-06-30 | ✅ |

## 当前状态

**阶段：** v5.0 Init Engineering（Agent Skill 模式）
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1

**最近动作：** 2026-06-30 更新项目目标 — 明确为 Agent Skill 模式、存量项目自动初始化、新项目向导初始化

**下一步：** 基于新的项目目标更新设计文档和代码实现

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | v5.0 精简 + 项目目标更新 | 明确 Agent Skill 模式、存量/新项目两种初始化路径 |
| 2026-06-24 | Init 深度审计 21 项 | 对照设计+实现+Copier/Cookiecutter/Yeoman 源码 |

## 待解决问题

| 状态 | 问题 | 说明 |
|------|------|------|
| [Q?] | 代码分析深度？ | 存量项目识别需要分析多少代码才能准确初始化？ |
| [Q?] | 向导字段数量？ | 新项目向导需要询问多少字段？哪些是必填？ |

## 引用文件

@design/INDEX.md · @design/v5.0-Design-Init.md · @design/v1.0-Design-Init.md · @design/v1.0-Design-Templates.md · @design/his_bak/
