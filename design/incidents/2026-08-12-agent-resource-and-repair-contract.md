# 2026-08-12 Agent 资源与 Repair 契约真跑事故

## 事实

- 外部只读报告：`voice_clone_for_auto_CC_Design/.ae-state/reports/loop-real-run-issue-report.md`。
- Thread `79cfa2db-d707-4c95-9e68-f5f691884c8a` 在 Tick 14 后进入 Critic；宿主原生
  `spawn_agent` 返回 `agent thread limit reached`，随后 `spawned=false` 被拒绝为
  `SPAWN_REQUIRED`。活动 Critic Action 和 checkpoint 均未丢失。
- 两次 Critic refine 分别要求 Architect 回显 `base_revision=1/2`，同时填写新增 batch、
  精确 `plate_keys`、task 结构和 obligation 增量，造成多次格式修正。

## 边界判断

| 问题 | 归属 | 本次处理 |
|---|---|---|
| Agent 线程上限 | Loop 宿主协议 + Core 恢复语义 | 修复 |
| Repair revision/模板脆弱 | Loop Architect Result 契约 | 修复 |
| `/api/voice-clone` 服务端路由 | Voice Clone 业务实现 | 不修改 |
| Hook/MediaRecorder 测试深度 | Voice Clone 业务验证 | 不修改 |

## 根因

1. 宿主规则只区分 spawn 成功和能力不可用，没有区分瞬时资源耗尽，也没有规定完成 Agent
   的回收、有限等待和重试顺序。
2. Core 将自身权威的 active revision 作为 Result 必填回显字段，错误地把确定性状态复制给
   LLM；Repair Action 也没有提供可直接填写的 batch/task 模板对象。

## 不变量与关闭标准

- 瞬时资源不足不得伪造 Worker、不得消费 active Action、不得丢 checkpoint。
- 宿主先回收已完成 Worker，再有限等待/重试；重试仍失败时返回可恢复资源等待 Action。
- `base_revision` 由 Core 注入；显式错误 revision 仍 fail-closed，防止旧 Result 覆盖新计划。
- Repair Action 明示当前 revision、继承 obligation、合法路由键和完整 task 模板。
- 真实 EventStore 恢复、协议校验、双宿主规则和 archive smoke 均有新鲜证据。

## 关闭结果

- `HOST_AGENT_CAPACITY` 被分类为可恢复 `resource_wait / WAIT_RESOURCE`；失败 Result 不被
  记为已接受，active Action、Stage 和 Tick 保持不变。
- Host Skill/Command 规定先等待/回收、重试一次，再提交标准容量错误；禁止 inline 或伪造。
- Architect repair Action 已携带 Core-owned revision、继承义务和 batch/task 模板；
  `base_revision` 缺失由 Core 注入，显式过期值继续 fail-closed。
- 证据：定向 279 passed；全量 2327 passed/1 skipped；coverage 90%；Ruff、mypy、
  规则同步和双宿主 archive smoke 通过。真实产品长跑不在本事故关闭中冒充完成。
