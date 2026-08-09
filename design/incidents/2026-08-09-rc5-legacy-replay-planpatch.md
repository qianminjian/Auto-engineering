# rc.5 旧事件重放与 PlanPatch 候选视图事故

> 日期：2026-08-09｜状态：自动门禁关闭，待真实产品长跑｜外部证据：`auto-engineering-loop-run-issue-report.md`

## 1. 影响

真实 Codex 运行恢复 thread `fa9c5495-2b78-4889-ad08-56b8446299b2` 后，Architect
refine 的合法增量计划无法进入 Developer。事件事务在全流重放时抛出
`ProjectionError`，业务源码未继续修改。

## 2. 已证实故障链

1. 旧流包含 20 条 `ResultAccepted.state_patch` 和 9 条
   `StageAdvanced.state_patch`；sequence 7 首次出现后一种形状。
2. Phase 80 严格 Reducer 只兼容前者，提交新 Tick 时全流 replay 在旧
   `StageAdvanced` 失败。
3. Architecture baseline 实际包含 B1-B5、B1-T1-B5-T2 和 8 条 obligation；状态未损坏。
4. `dry_run_architect_plan` 合并 baseline 与 additions 后，obligation 校验器因 candidate
   仍带 `plan_patch`，再次只扫描 additions，错误报告旧任务不存在。
5. 宿主为响应错误反馈而复制旧任务和 obligations，继而触发 ID/source_ref 冲突；这些
   结果是错误诊断的后果，不是根因。

## 3. 结构性根因

- Legacy 兼容按单一事件类型实现，没有以真实旧流 payload 形状建立兼容边界。
- PlanPatch 的 merge、validate、activate 和 Prompt 没有消费同一个不可变 candidate。
- 跨版本测试由当前代码生成新流，未使用脱敏历史事件 fixture。
- `engine_build_id` 等于 SemVer；同一 `5.8.0-rc.5` 的不同提交无法区分。

## 4. 修复不变量

1. 旧事件先经只读 Legacy Adapter 恢复历史语义；严格新 Reducer 不接受 `state_patch`。
2. 新写入必须在 EventStore 边界拒绝任何事件类型的 `state_patch`，legacy import 除外。
3. Baseline、PlanPatch、contracts 和 obligations 只物化一次 Candidate，验证与激活共享它。
4. refine 未提交 obligations 表示继承；更新必须使用显式增量语义，禁止隐式重复覆盖。
5. 跨版本门禁必须重放真实旧 payload 形状；版本报告必须包含不可混淆的 Build Identity。

## 5. 关闭标准

- 脱敏旧流从 seed 重放到 sequence 60，并可接受合法 PlanPatch 进入 Developer。
- 新 `StageAdvanced.state_patch` 写入被拒绝，旧同形事件只读重放且计入 legacy 指标。
- 仅新增 batch、继承旧 obligations 的 patch 通过；重复/冲突更新返回稳定错误。
- 同 SemVer 不同提交具有不同 Build Identity；制品、Action 和报告身份一致。
- 专项、故障注入、全量、覆盖率、Ruff、mypy、同步和双宿主制品门禁全部通过。

## 6. 关闭证据（2026-08-09）

- 脱敏 rc.5 事件 fixture 可重放 `ResultAccepted` 与 `StageAdvanced` 的历史
  `state_patch`；EventStore 对新写入统一 fail-closed。
- `ArchitectureCandidateBuilder` 统一 baseline、PlanPatch、contracts 与 obligations；
  投影和激活共享 candidate，并对漂移硬失败。
- refine Prompt、expected format 与 stage-result schema 同步支持受控
  `obligation_updates`；历史 obligation 自动继承。
- 隔离复制真实项目后，以 `architect-refine-result.json` 恢复原 thread，exit 0，
  从 `architect` 进入 `developer`；真实项目未写入。
- 全量：2266 passed、1 skipped；coverage 90%；Ruff、mypy、Prompt sync 通过。
- Release 使用内容寻址 Build Identity；裸 Python 构建及 Claude Code/Codex archive
  smoke 全部通过。真实产品长跑仍由 T411-T412 独立阻断发布。
