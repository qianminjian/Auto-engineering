# 2026-08-29 真跑报告的系统性根因与修复规格

## 结论

本次停止不是 Architect 业务计划失败，而是宿主执行链的三个合同层没有形成同一条可验证
事务：初始化能力声明、Result 终结顺序、Worker 失败重试预算。报告中的“旧 tick 用法、
Research 类型错误、Prompt hash 错误、300 秒超时、晚到通知”属于同一链路上不同边界的表现，
不能分别靠提示词补丁处理。

## 根因

1. `project_setup` 只接受模型提交的 artifacts，能力探测要等提交后才重新执行；空项目因此
   必须先由宿主搭建工程，不能把“设计文档存在”误报成可运行工程。
2. 宿主仍可能绕过 Action 下发的 finalize→validate→tick 操作顺序。Core 拒绝旧 Result 是
   正确的 fail-closed，但执行包应把这条顺序作为唯一可消费接口，而不是让宿主自行拼接。
3. Research 的人类说明写 `search_error: string|null`，运行时与 JSON Schema 却只允许 string，
   造成同一 Result 在提示词和门禁之间漂移。
4. Worker hash/能力/启动错误和真正的 timeout 共用 `failure_attempt`，且
   `HOST_WORKER_FAILED` 原先直接返回错误而不是 `WAIT_RESOURCE`。前一次非超时错误会消耗
   超时预算，导致第一次真实 timeout 被错误升级为 `HOST_WORKER_TIMEOUT_EXHAUSTED`，并把本可
   自动修复的宿主合同错误暴露给前台。
5. 原生 Worker 的晚到通知没有对应已接受的 outcomes 事务时不能改变 Core；它必须被记录为
   stale evidence，而不是再次提交或覆盖当前 Action。
6. Component Verifier 的 Action 只提供了组件级设计摘要，没有把当前 batch 的设计条目范围
   绑定到机器合同；Worker 因而按组件或全文审计，未来批次被错误报告为当前缺口。

## 报告问题到闭环证据

| 优先级 | 报告问题 | 处理结果 | 自动证据 | 真实宿主边界 |
|---|---|---|---|---|
| P0 | `STATE_PROJECTION_MISMATCH (coverage_map)` | Component Verifier 回源同时投影 `coverage_map` 与 `audit_findings`，EventStore 回放与内存状态保持一致 | `test_event_store_plan_refine_projects_coverage_map` | 新 Build 的 Claude/Codex L3/L4 仍需实跑 |
| P0 | GAP-1/2 决议在 Architect 修复轮丢失 | Architect Action 有界注入已接受 Gap 决议；Research 完成后先回 Gap Review，不得绕过用户确认 | `test_architect_prompt_carries_persisted_gap_decisions`、Gap Research 回归 | 真实宿主需确认最终计划保留决议 |
| P1 | GAP-4/5/6 未完成 Review | Research 只提供证据，未决 Gap 必须回到同一 Review 游标 | `test_research_success_returns_to_same_gap_for_user_review` | 真实宿主需验证前台逐项呈现 |
| P1 | Verifier 审计未来批次 | Architect 声明 `design_item_refs`；Action 携带 `verification_scope`；Core 要求 coverage 集合精确相等 | Verifier 范围正/负轨迹回归 | 新 Build L4 需验证不再误报未来批次 |
| P2 | `§` 前缀导致重复 Architect 重写 | EngineeringModel 按稳定章节编号归一化展示前缀与文件后缀 | `test_engineering_model` 章节身份回归 | 真实宿主需确认不再触发格式修复 |
| P1 | Host 重复 Tick、Finalize 参数错位、污染 journal | Result/Outcome 事务保持同一 Action；重复、迟到和失败按机器合同恢复或 fail-closed | Host trajectory、OutcomeJournal、ExecutionAssembler 回归 | 真实宿主需完成一次异常恢复 |
| P1 | Timeout 与 Worker 合同失败混计 | 按 `failure_kind` 分离预算，首次同类失败自动等待/重试 | Host failure budget 回归 | 真实宿主需提供一次 timeout 证据 |
| P2 | 主会话输入重复、审计范围过大 | compact Action、PromptRef/ArtifactRef、范围白名单和有界 Gap/研究上下文已落地；固定 Tick 不再作为产品门槛 | 全量轨迹与 prompt contract 回归 | 需用真实 usage ledger 验证成本基线 |
| P1 | Architect 语义校验失败时的重复计划 | 已消除本报告中的章节格式类重复重写；语义候选未被 Core 接受，仍要求完整重提以避免对未认证计划做隐式合并 | 章节编号归一化与 Architect 负向回归 | 若产品成本基线仍超预算，再单独设计并审批候选补丁协议，不在本轮引入隐式合并 |
| P2 | Stop Hook 反复阻断 | 归属 Claude Code 宿主配置，不由 Loop Core 修改 | 无 Loop 代码变更 | 宿主侧需关闭/修正 hook 后再做 L3/L4 |

本表中的“自动证据”只证明 Core、协议和离线轨迹；它不能替代真实 Claude Code/Codex
安装后的 L3/L4。后者仍是发布门禁，不得用测试数量或 archive smoke 冒充完成。

## 目标规格

- `ProjectProfile` 是 setup 完成后的机器事实；没有可执行 test 命令时保持 `SETUP_REQUIRED`，
  不让 Architect 误以为项目已准备好。
- 所有宿主执行统一消费 Action 的 `operations.finalize/validate/submit`，Core 身份和结果由
  Finalizer 生成；直接 `--tick` 只能提交已经由 Finalizer 生成的完整 Result。
- 每个 Result 字段必须在 `expected_format`、`result_contract`、运行时验证和 JSON Schema 四处
  使用相同类型；可选字段的 `null` 语义必须显式一致。
- Worker 失败预算按 `failure_kind` 隔离（`timeout` 与 `worker`），只对同类连续失败计数；
  timeout 与合同失败各最多一次自动重试，其他合同错误不得伪装为 timeout；首次
  `HOST_WORKER_FAILED` 必须返回 `WAIT_RESOURCE`，不能直接结束 Loop。
- 晚到 outcome 仅当仍绑定同一 active Action、同一 invocation 和同一 prompt hash 时才可进入
  当前 outcomes 事务；否则写入有界 stale 证据并保持 Core 状态不变。
- 有设计条目的 batch 必须声明 `design_item_refs`；Verifier prompt 和 Action 的
  `verification_scope` 使用同一白名单，Core 要求 coverage_map 与白名单集合完全相等。

## 验收

- Research `search_error=null` 同时通过 JSON Schema 和运行时校验。
- 先发生 hash/启动失败、再发生第一次 timeout 时，Result 为 `HOST_WORKER_TIMEOUT` 且
  `spawn_retry_attempt=1`；连续第二次同类 timeout 才为 exhausted。
- 真跑回放必须覆盖 setup→finalize→validate→tick、错误修复、超时重试、晚到 outcome，
  不能只测试单个函数返回值。
- 多批次组件回放必须证明第一批不接收第二批条目，且缺项/越界/重复覆盖均在提交前拒绝。
- 历史多批次计划若没有范围声明必须 fail-closed，不得退化成全组件审计。
