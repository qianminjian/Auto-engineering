# rc.5 Plan Refine 批次冲突事故

> 日期：2026-08-06｜状态：自动修复完成，待真实复验｜外部证据：`ae-loop-real-run-report-2026-08-06.md`

## 1. 影响

真实运行在 Tick 19 接受 Architect 架构细化结果后抛出
`PLAN_BATCH_CONFLICT: B1`，无法继续 B1 修复及 B2-B5 开发。此前 18 Tick 的研究、开发、
Critic 与 Verifier 事实仍在，但执行线程被非协议化异常终止。

## 2. 已证实故障链

1. Component Verifier 对 B1 返回 3 项 MISSING、4 项 DIVERGED，Core 正确进入
   `PLAN_REFINE`。
2. Tick 19 Prompt 的角色说明和 Expected Format 仍要求完整 `batch_plan`，没有要求
   `plan_patch`。
3. Architect 因而重发 B1-B5 的整棵计划，并修改 B1 task payload。
4. `_apply_result_to_state` 将完整计划写入 `state.batch_plan`；
   `_initialize_architecture` 仅凭 `plan_refine_count > 0` 把它当作 `add_batches`。
5. `BatchState.apply_plan_patch` 正确检测同 ID 不同 payload，并 fail-closed；异常未被前置
   Result 校验转换为可重试的 Architect 反馈，最终表现为引擎崩溃。

根因是 Prompt、Result schema 和 PlanPatch 应用语义分裂，不是 BatchState 的冲突规则过严。

## 3. 关联问题判断

- Contract gate 提前触发属实：当前每个 Developer batch 都收到 ArchitectureBaseline 的
  全量 contracts；B1 因而被要求证明 B2 才实现的 BFF route。
- DTO 漂移属语义覆盖问题，但本次 Critic/Verifier 已发现；Core 无法确定性解析任意 Markdown
  并生成业务 DTO，不能以脆弱 schema 生成器替代义务矩阵和语义验证。
- component 名称保持稳定身份是治理要求。Phase 76 已支持章节编号映射；不得增加静默模糊
  匹配，只应继续提供规范化标识与明确错误。
- rc.5 已将 spawn receipt 缩减为 Core challenge + Host completion receipt，不再要求
  thread/message 手工回填；本次不再增加 proof 管理层。

## 4. 修复不变量

1. PLAN_REFINE 只能接受带 `base_revision` 的增量 `plan_patch`；完整 `batch_plan` 必须在
   状态变更前被拒绝并返回可操作错误。
2. PlanPatch 只能新增 revision 唯一 batch；不得修改或重新打开既有 batch，修复批次使用
   新 ID 并通过依赖关系续接。
3. Contract 只有在引用它的全部实现义务到达当前/已完成 batch 后才进入 required Gate；
   未绑定 obligation 的 legacy contract 保持立即验证兼容语义。
4. ArchitectureBaseline revision、完成事实与 ProgressTree 历史必须在 patch 后保持可重放。

## 5. 关闭标准

- 重放“B1 approved → verifier gap → architect full plan”时，Core 不崩溃并拒绝错误 Result。
- 合法 `plan_patch` 新增修复 batch 后，游标定位到首个新增未完成 batch。
- B1 不验证仅由 B2 才完整实现的 contract；B2 完成时该 contract 必须验证。
- 专项、全量、覆盖率、Ruff、mypy、规则同步与双宿主制品验收通过后，才进入真实复验。

## 6. 自动验证证据

- 回归与全量：2194 passed、1 skipped；覆盖率 90%。
- Ruff、mypy（136 files）、Agent/Prompt 同步、项目元数据与双宿主包结构检查通过。
- Claude Code/Codex archive smoke 均通过 package、隔离安装、doctor、minimal tick、
  manifest-free profile、status 与 resume；真实产品复验尚未执行，事故不标记为关闭。
