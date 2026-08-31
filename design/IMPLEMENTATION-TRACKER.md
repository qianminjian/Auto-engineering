# Auto-Engineering 当前实施跟踪表

> 更新：2026-08-31｜唯一产品任务：P0-E2E 单命令运行到 TERMINAL｜状态：`☐` 未开始／`◐` 进行中／`✅` 已验证

## 导航

- 当前权威设计：[`v5.8-Main-Agent-Coordinator-Recovery-Design.md`](v5.8-Main-Agent-Coordinator-Recovery-Design.md)
- 当前决策：[`BEACON.md`](BEACON.md)
- 历史任务：[`IMPLEMENTATION-TRACKER-HIS.md`](IMPLEMENTATION-TRACKER-HIS.md)
- 项目里程碑：[`HISTORY.md`](HISTORY.md)

## 唯一 P0：端到端产品闭环

| 优先级 | ID | 唯一交付任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | P0-E2E | 独立安装后的单命令设计开发闭环 | While 同一 Build 分别安装到 Codex 与 Claude Code, when 用户在空项目执行一次设计驱动命令, both hosts shall 自动完成设计扫描、规划、开发、审查、修复和验证并到达等价 `TERMINAL`，零非预期人工续接、零手工协议修复 | ◐ Phase 85 第一批已实现；自动回归不能替代当前 Build 双宿主 L4，继续阻断发布 |

### 当前工作面

| 工作面 | 当前判断 |
|---|---|
| 设计工程模型 | ✅ section 身份、设计权威和任务追溯已有基础 |
| Core 确定性协议 | ✅ Action/Result、EventStore、Finalizer、Journal 和 Gate 已有基础 |
| 主 Agent 持续协调 | ◐ 默认入口已切回主 Agent；真实宿主连续运行待验收 |
| Worker 生命周期 | ◐ generation/fencing 与等待语义已落地；原生 liveness 待真实宿主验收 |
| 预算 soft | ✅ 默认不硬停；显式 hard 仍可用 |
| 真实异步验收 | ☐ Fake Host 不能关闭；Codex/Claude 同 Build L3/L4 待执行 |

### 完成纪律

- 每次真跑故障先归属完整工作面，禁止只修最终错误码。
- P2 整洁任务不得阻塞 P0 主链。
- 只有 T609–T620 和 P0-E2E 全部取得新鲜证据时才允许发布。

## Phase 85：主 Agent 协调权恢复与宿主生命周期纠偏

> 风险列表示决策对产品架构的影响。设计已批准并进入实施；旧 Supervisor 先旁路，双宿主 L4 通过后再退役。

### 设计与迁移合同

| 优先级 | ID | 风险 | 任务 | 状态 |
|---:|---|:---:|---|:---:|
| P0 | T603 | R4 | 保留 D13 授权争议并由 D53–D56 取代 | ✅ 已登记 |
| P0 | T604 | R4 | 定版当前主 Agent 唯一 Coordinator 边界 | ✅ 已定版 |
| P0 | T605 | R3 | 定版 Worker 所有权、liveness、generation 与 Artifact 恢复 | ✅ 已定版 |
| P0 | T606 | R3 | 定版 Codex/Claude 宿主差异合同 | ✅ 已定版 |
| P0 | T607 | R2 | 预算默认 soft、外部限流分离 | ✅ 已定版 |
| P0 | T608 | R3 | Supervisor 先旁路后退役迁移合同 | ✅ 已定版 |

### 恢复正确主链

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T609 | R4 | Skill/Command 恢复主 Agent 持续 Action 循环 | 一次命令连续到合法退出，不默认调用 `--supervise` | ◐ L1 通过；L3/L4 待验收 |
| P0 | T610 | R3 | 接入现有 work files、Collector、Finalizer、Journal 和机器 argv | 不回滚到手工拼装机器事实 | ◐ L1 通过；L2/L3 待验收 |
| P0 | T611 | R3 | 等待观察、liveness 探测和所有权不确定分流 | wait 不等于失败；无法确认终止时禁止并发重跑 | ◐ 等待语义已统一；L2/L3 待验收 |
| P0 | T612 | R3 | Worker 私有 outcome 先行与有界主会话摘要 | Worker 先原子落盘，主 Agent 只保留引用、摘要和 handle | ◐ L1 通过；L3 待验收 |
| P0 | T613 | R3 | OWNER_LOST、generation、lease 和 fencing 防双写 | Collector 只接受 active generation，旧结果只审计 | ◐ generation/fencing 已落地；跨会话 L2/L3 待验收 |
| P0 | T614 | R3 | Coordinator-only repair 全链复用 | Assembler/Core 拒绝不重跑 Worker | ◐ L1 通过；L3 待验收 |
| P0 | T615 | R2 | 删除默认预算硬停机 | 缺省/soft 模式只记录指标并继续 | ◐ L1 通过；显式 hard 兼容，L3 待验收 |

### 真实验收与退役

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T616 | R3 | 建立真实异步纵向宿主模拟器 | 第一次 wait 结束后 Worker 继续运行并最终推进 Tick | ◐ `test_public_cli_async_worker_trajectory_uses_current_action_artifacts` 与异步子进程回归通过；真实宿主待验收 |
| P0 | T617 | R3 | 历史真跑事故回放矩阵 | 覆盖 wait、owner 丢失、迟到、重复、部分成功和 Core 拒绝 | ◐ 回放矩阵通过；真实宿主待验收 |
| P0 | T618 | R3 | 安装制品公开入口契约测试 | 最新工作树 release archive 在 Codex/Claude Code 两种宿主模式均通过 package、隔离安装、doctor、Worker 回写入口、minimal tick、status、resume、runtime identity 和 design authority smoke；真实产品安装待验收 | ◐ |
| P0 | T619 | R3 | Codex L3/L4 单命令终态 | 覆盖多角色、wait、repair、零人工续接和 TERMINAL | ☐ 待真实验收 |
| P0 | T620 | R3 | Claude Code L3/L4 等价终态 | 不嵌套 `claude -p`，语义与 Codex 等价 | ☐ 待真实验收 |
| P1 | T621 | R3 | 双宿主通过后退役旧 Supervisor | T619–T620 通过后删除旧默认主控，永久保留历史设计 | ☐ 前置未满足 |

## 2026-08-30 架构审计修复批次

| 优先级 | ID | 风险 | 任务 | 验证证据 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T622 | R4 | 统一 Action generation 绑定映射入口，修复 prepare/finalize/status/cleanup 路径分叉 | `test_prepare_and_finalize_mapping_share_the_same_worker_artifact_generation`、`test_status_uses_bound_host_mapping_for_active_action`、`test_cleanup_removes_generation_bound_worker_artifact` | ✅ |
| P0 | T623 | R4 | EventStore 优先且冲突 fail-closed，禁止 checkpoint 与事件快照拼接 | `test_active_action_rejects_event_and_checkpoint_identity_conflict`、`test_active_event_action_is_authoritative_without_checkpoint_splicing` | ✅ |
| P1 | T624 | R3 | Tick 事务失败清理未提交命名 JSON effect，保留内容寻址 prompt | `test_discard_removes_only_uncommitted_named_json_artifacts` | ✅ |
| P1 | T625 | R3 | 产品验收 artifact 增加 machine claims 并交叉校验外层声明 | `test_machine_claims_reject_outer_usage_declaration_drift`、产品证据回归 | ✅ |
| P0 | T626 | R3 | EventStore/checkpoint 状态分叉在 init/tick/finalize/status/supervisor 入口统一归一为 `STATE_SOURCE_CONFLICT` 协议错误，禁止宿主收到 Python traceback | `test_state_source_conflict_is_returned_as_protocol_error_action`、`test_status_reports_recovery_required_on_state_source_conflict`、`test_finalize_stops_with_stable_error_on_state_source_conflict`、`test_supervisor_stops_with_stable_error_on_state_source_conflict`；历史批次全量 2820 passed/1 skipped，覆盖率严格 90% | ✅ |
| P1 | T627 | R2 | 跟踪表状态必须与证据层级一致：L1/L2 或 archive smoke 不能标记为产品完成 | 本表将未完成真实 L3/L4 的任务统一标为 `◐/☐`，保持发布门禁可见 | ✅ |
| P0 | T628 | R4 | L2 异步纵向测试必须经过公开 CLI，不得只调用 Adapter/Assembler/Core 内部接口 | `test_public_cli_async_worker_trajectory_uses_current_action_artifacts` 覆盖 init→异步 Worker→finalize→validate→tick；目标是防止单测绕过真实衔接 | ✅ |
| P1 | T629 | R2 | 安装验收文档命令必须显式传入受控 wheel 缓存，避免启动即因 `HERMETIC_CACHE_REQUIRED` 失败 | `test_documented_archive_acceptance_is_hermetic`、双宿主 archive smoke 通过 | ✅ |
| P1 | T630 | R2 | 规则同步命令统一使用项目锁定解释器，避免宿主 Python 版本导致 `tomllib` 等基础依赖缺失 | `test_documented_archive_acceptance_is_hermetic`、`sync_agent_instructions.py --check` 通过 | ✅ |
| P1 | T631 | R3 | 用户指南必须与 D16 保持一致：Init Engineering 为可选兼容 Provider，不得作为运行时硬前置 | `test_user_guide_does_not_reintroduce_init_runtime_dependency`、ProjectProfile 无 manifest 回归 | ✅ |
| P1 | T632 | R3 | 生成规则、EARS 基线和培训指南统一标注 Init manifest 为可选兼容输入，消除跨文档运行时口径冲突 | `test_user_guide_does_not_reintroduce_init_runtime_dependency`、规则同步检查、全量回归 | ✅ |
| P1 | T633 | R3 | 损坏宿主 receipt 与空事件流恢复必须稳定 fail-closed，禁止裸 `ValueError/IndexError` 破坏诊断链 | `test_receipt_journal_rejects_invalid_tick_without_raw_value_error`、`test_rebuild_projection_rejects_empty_event_stream`、全量 2820 passed/1 skipped | ✅ |

> 本批次历史全量回归：`2820 passed, 1 skipped`；真实双宿主 L3/L4 仍属于 T619/T620，未因自动测试通过而宣称发布。

## 2026-08-30 真跑首个 Architect 阻断（系统性修复）

> 证据：Voice Clone 真跑中 Worker 已生成 `status=completed` 的私有 Architect 产物，
> 但宿主写入路径与 Action 声明路径不一致；随后等待/关闭被误归类为失败，重试又复用旧
> Result 路径。以下任务按一条完整交接链修复，不以增加等待时间或增加 fallback 路径代替。

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T634 | R4 | 定版唯一 Worker Artifact 身份与路径：Core 生成，Host 原样转发，Collector 原样读取 | Action、Host 映射、Prompt、Collector、cleanup、retry 对同一 invocation 得到同一路径；路径漂移被明确拒绝 | ✅ 定向回归通过 |
| P0 | T635 | R4 | 分离 Worker 业务 Artifact 与 Host Attestation | Worker 不再填写 handle/model/isolation 等宿主事实；Host 负责生成并校验 Attestation，completed 必须显式提交实际隔离证据且状态必须与业务产物一致，禁止 `unreported` 冒充真实事实 | ◐ 已改提示词/收集器/`--record-worker-outcome`；待真实宿主 |
| P0 | T636 | R4 | 建立结果优先的完成/失败协调事务 | 失败提交前必重扫当前 generation 的 Artifact；合法完成结果优先，失败不能覆盖已提交成功 | ✅ 定向回归通过 |
| P0 | T637 | R4 | 重试重新物化执行身份和工作文件 | 每次重试生成新 generation、invocation、outcome/result/receipt/fencing；禁止复用旧路径或旧 handle | ✅ generation/fencing 回归通过 |
| P0 | T638 | R4 | 真实宿主公开入口 L3/L4 轨迹测试 | 原生 spawn/wait/close、迟到结果、宿主关闭、失败重试和最终 Tick 均经过 Codex/Claude 实际入口验证 | ☐ |

## 2026-08-31 Worker 回写机器合同补强

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T639 | R3 | 将逐 Worker `record-worker-outcome` 纳入 Host Action 机器操作模板 | 每个严格 invocation 都携带唯一回写 argv 模板；宿主只替换原生运行时事实，不能凭提示词重新拼装；模板与当前 Action/generation/path 绑定 | ✅ 已验证 |

- 验证证据：`tests/test_host_adapter.py`、公开 CLI 异步轨迹及 Host/Assembler 回归；全量串行回归 `2835 passed, 1 skipped`，覆盖率 `90%`，Ruff/mypy/规则同步通过。

### 2026-08-31 实施证据与边界

- 已统一 generation-bound Worker 路径：`.ae-state/host-runtime/worker-outcomes/<action-key>-<worker>-g<generation>.json`；旧 rc.5 目录仅按当前 Action/Worker 的确定性路径迁移，不做目录扫描。
- 私有 Worker 文件现在只允许业务字段；主 Agent 通过 `--record-worker-outcome` 把原生 handle、模型、状态和实际隔离证明交给确定性 Assembler；缺少宿主事实时返回 `HOST_WORKER_ATTESTATION_MISSING` 或 `NATIVE_ISOLATION_EVIDENCE_MISSING`，绝不把 `unreported:*` 句柄当成成功证据。
- Finalizer 在失败事务前重新采集当前 generation；单 Worker 合法完成结果优先恢复 Coordinator，失败日志不能覆盖晚到成功。
- 重试由失败 journal 驱动 `generation + 1`，重新绑定 invocation/outcome 路径和 fencing token；同一失败事实保持幂等，不靠变化错误文本消耗重试预算。
- 验证：相关 Host/CLI/Prompt 回归已扩展并通过；本批次全量串行回归 `2835 passed, 1 skipped`，覆盖率 `90%`；公开 CLI 异步轨迹已改为业务私有产物→`--record-worker-outcome`→Finalizer→validate→tick，实际隔离证据缺失会稳定拒绝，状态不一致会稳定拒绝，真实 Codex/Claude L3/L4 仍未执行。
- 安装验证：`/tmp/auto-engineering-final-release.tar.gz` 在 Codex 与 Claude Code 宿主模式下的归档 smoke 均通过；该结果只证明安装包和内部协议入口可用，不替代真实产品 L3/L4。

### 2026-08-31 Compact 宿主视图闭环补强

| 优先级 | ID | 风险 | 任务 | 验证证据 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T640 | R4 | compact Action 必须保留 Worker 完成回写所需的机器字段（结果路径、generation、fencing、回写 argv 模板和 receipt 路径），缺失时在投影阶段 fail-closed，避免为节省上下文而切断真实宿主衔接 | `test_compact_host_view_projects_only_runtime_control_and_native_launcher`、`test_compact_host_view_rejects_strict_worker_without_handoff_contract`、compact 公开 CLI 异步轨迹及全量回归 | ✅ 已验证 |

- T640 验证：compact 视图保留回写合同与身份字段，继续省略 receipt/attestation 正文；定向回归通过。

### 2026-08-31 Worker 启动身份合同补强

| 优先级 | ID | 风险 | 任务 | 验证证据 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T641 | R4 | 原生 Worker 启动合同必须显式携带规范 `worker_id`，禁止仅从结果路径或自然语言推断身份 | Host Adapter 启动合同身份回归、68 个宿主回归及全量回归 | ✅ 已验证 |

- T641 验证：启动合同显式携带规范 `worker_id`；为保持 1KB 上限压缩重复文字而非放宽提示词预算。
