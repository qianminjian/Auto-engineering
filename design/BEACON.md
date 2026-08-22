# Auto-Engineering BEACON
> 创建：2026-06-24｜更新：2026-08-21｜阶段：Phase 83 Host Runtime 产品闭环收敛
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。

## 目标与成功标准
1. 定位为跨 Agent 宿主的确定性工程治理内核。
2. 宿主负责推理与工具执行；Core 负责协议、状态、验证、安全和审计。
3. 所有跨宿主消息使用版本化协议，并具有消息身份与因果关系。
4. 状态可由 append-only 事件重放，重复 Result 不重复推进。
5. Claude Code 与 Codex 对同一黄金轨迹产生等价 Core 结果。

## 范围边界

**做：** Protocol Envelope、Event Store、Tick Kernel、StageHandler、Host SPI、
Gate/Guardrail、五层验证、审计、v5.6 兼容迁移和双宿主验收。
**不做：** Core 内调用 LLM；复制宿主 Agent Runtime；恢复退役 CLI；实现 Init Engineering 的问答、模板或脚手架；把 archive smoke 冒充真实产品安装；修改外部参考源码。

## 当前设计决策

| ID | 决策 | 状态 |
|---|---|:---:|
| D1 | Core 只做确定性治理，Agent 在 Tick 之间推理和执行工具 | ✅ |
| D2 | Host Adapter 隔离宿主差异，Core 不感知 Claude/Codex | ✅ |
| D3 | Claude/Codex 共用规则模板、Skill 协议和 `scripts/ae-run` | ✅ |
| D4 | `FeatureManifest` 是 `AE_*` 默认值唯一事实源 | ✅ |
| D5 | archive smoke 与真实 product install 分开报告 | ✅ |
| D6 | 当前资产短小可追溯，详细历史由 Git 和 `HISTORY.md` 保留 | ✅ |
| D7 | 采用双基线：v5.7.1 是当前发布实现，v5.8 是已批准目标 | ✅ |
| D8 | v5.7 采用渐进协议内核重构，不建立双内核 | ✅ |
| D9 | 事件是事实源，EngineState 是可重建投影 | ✅ |
| D10 | Prompt Contract 采用兼容式编译，不改变 Action/Result v1.1 核心语义 | ✅ |
| D11 | 多 Agent 必须逐 Worker 交付上下文并提供独立完成回执 | ✅ |
| D12 | Thread 与 ExecutionSession 分离；聊天历史、BEACON 和自动摘要不是状态事实源 | ✅ |
| D13 | 宿主自动 compaction；固定 Tick 不换会话；Capsule 仅用于异常恢复 | ✅ |
| D14 | 修复计划使用 PlanPatch；完成事实不可由普通计划更新重新激活 | ✅ |
| D15 | runner 错配、零测试、空快照和证据失配全部 fail-closed | ✅ |
| D16 | Core 以 ProjectProfile 消费项目能力；本地确定性探测为默认 Provider，Init Engineering 仅是可选兼容 Provider | ✅ |
| D17 | Core 保持单 Tick；宿主按 Execution Control 在一次启动内连续驱动 | ✅ |
| D18 | Prompt/Policy 等运行时变化只在 Action 边界激活，活动 Action 不可变 | ✅ |
| D19 | 新状态事实使用显式领域事件；完整 state patch 只作 legacy 读取 | ✅ |
| D20 | ActionCompiler 纯化，TickOrchestrator 按 Stage 绞杀，不建立第二内核 | ✅ |
| D21 | Legacy 兼容按 payload 能力适配全部旧事件类型；新写入在 EventStore 边界拒绝 `state_patch` | ✅ |
| D22 | Baseline、PlanPatch、contracts、obligations 只物化一次 Architecture Candidate，校验与激活共享 | ✅ |
| D23 | SemVer 表示发布版本，内容寻址 Build Identity 区分同版本的不同制品和源码 | ✅ |
| D24 | 显式设计文档与旧状态冲突时先由用户选择重新初始化或修复续作；旧状态保留审计 | ✅ |
| D25 | Gap 决策由 Core 单项持久化；batch 展示标题与多组件路由键分离；Git 仅是可选证据源 | ✅ |
| D26 | 本机产品安装只注册开发目录之外的内容寻址 Release；运行时来源不得反向访问源码工作区 | ✅ |
| D27 | Host Runtime 属于插件产品层；Core 保持单 Tick，用户不承担 continue/supervisor 管理命令 | ✅ |
| D28 | Worker outcome 由宿主 Assembler 原子固化为 receipt、attestation、total proof 和 Result | ✅ |
| D29 | partial 设计权威只允许保守执行原设计；advisory 架构变化必须显式用户批准 | ✅ |
| D30 | 宿主临时交接文件按 Action identity 隔离；固定根目录文件不得跨 Tick 复用 | ✅ |
| D31 | Core 状态目录必须从宿主工作区 diff 隔离，但不得隐藏业务源码或改写用户根忽略策略 | ✅ |
| D32-D36 | Tick 后清理临时交接并有界等待；自动 Gap 决策双重重绑；已批准 Fill 保持 binding；Gate 使用独立 Result 契约 | ✅ |
| D37 | Worker 失败写 `worker_failed` 尝试并由 Core 返回 WAIT_RESOURCE；只有成功 journal 才禁止重复 spawn | ✅ |
| D38 | Finalizer 以 active Action 的工作文件为唯一事实源；宿主传入陈旧路径时自动续接当前文件，禁止跨 Action 误提交 | ✅ |
| D39 | 系统审计覆盖维度固定、执行 fan-out 按 Core 计算的项目规模伸缩；小项目不重复发送五份上下文 | ✅ |
| D40 | ProjectProfile 只声明期望能力；项目锚点删除判断只依据 Core 已持久化见证的目录事实，不从未来目录声明反推历史存在 | ✅ |
| D41 | Canonical Action 与宿主控制视图分离；产品宿主只接收内容寻址的 compact envelope，完整 Prompt 不进入每 Tick stdout | ✅ |

## 当前状态

- Phase 1-79 的功能与自动门禁历史见 Tracker/HISTORY；v5.8.0-rc.5 仍未通过真实产品长跑门禁。
- Phase 80-82 已关闭旧可变 Stage 分支、显式设计与隐藏状态冲突、严格 Host 合同、Worker 证明、事件恢复和安装来源隔离。
- 当前候选的自动门禁、双宿主 frozen/offline L2 和内容寻址安装可验证；这些证据不替代真实产品 L3/L4 长跑。
- 双宿主 L3 均已到 TERMINAL；L4 揭示的 Gap 恢复、运行时激活、自动决策、补充权威、Gate 校验与在途迁移缺口已由 T505-T511 闭合。
- T512-T523 已闭合跨会话恢复、陈旧路径重绑、未提交 outcome 复用和审计 fan-out 伸缩；2519/1、Ruff、mypy 通过。完整 L3/L4 终态仍未完成。
- T529 已将小项目 Worker 4→2 并闭合三类验收；2533/1 通过，但固定宿主历史仍使成本失败，L4/发布阻断。
## 最近演进
| 日期 | 变更 |
|---|---|
| 2026-08-21 | T512-T518 关闭重复 spawn、错误恢复、计划校验终止、Worker 超时伪成功与无限重启链路 |
| 2026-08-21 | T519-T523 关闭旧路径误提交、未提交 outcome 重跑与小项目固定 5×xhigh 审计成本 |
| 2026-08-22 | T524 关闭未来目录误报；双宿主 L3 暴露百万级 cache read，启动 T525-T526 |
| 2026-08-22 | T525-T528 关闭正文重复、journal 漂移与 Worker Prompt 复制；定位为四个 fresh Worker 重复加载宿主基线 |
## 待解决问题
- T530 待审批：以 Action-scoped fresh host context 翻转 D13 固定模型上下文；用户仍只启动一次。

## 引用文件

`design/v5.8-Host-Runtime-Convergence-Analysis.md` · `design/v5.8-Host-Runtime-Convergence-Design.md` · `design/v5.8-Host-Runtime-Convergence-PLAN.md` · `design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
