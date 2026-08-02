# Claude Code 146-Tick 真实运行事故分析

> 事故日期：2026-07-28 至 2026-07-29
> 记录日期：2026-07-29
> 状态：根因修复已实施，真实产品长跑复验待完成
> 严重度：P0（验证可信度与长流程可用性）
> 关联设计：`../v5.8-Session-Decoupling-Design.md`
> 关联计划：`../v5.8-Session-Decoupling-PLAN.md`

## 1. 摘要

Auto-Engineering v5.7.1 在 Claude Code 中驱动一个 TypeScript/Vitest 真实项目，
持续约 3 小时 20 分钟、推进至 Tick 146 后，被模型服务以输入长度超限拒绝。

事故同时暴露四类 P0 问题：

1. 长工程线程与单个宿主会话耦合，历史上下文被持续重放。
2. Architect 修复计划整体替换后，已完成任务状态与新计划失配，执行指针回到 B1。
3. TypeScript/Vitest 项目错误进入 pytest 路径，零测试和非零退出仍被判为通过。
4. 非空项目的 Gate 使用空内容 SHA-256 作为文件快照，仍记录通过。

代码成果可能大部分可保留，但本次“已完成并验证”的系统结论不可信。Phase 64
完成前，不得将中等规模无人值守真跑作为发布证据。

## 2. 运行范围

| 项目 | 值 |
|---|---|
| 宿主 | Claude Code |
| 目标项目 | `voice_clone_for_auto_CC_Design` |
| 项目类型 | React 19 + TypeScript + Vite + Vitest |
| 运行入口 | Auto-Engineering `dev-loop` |
| 运行时长 | 约 3h 19m 49s |
| 最后 Tick | 146 |
| 原始批次 | B1-B20，另有修复批次 |
| 中断前计划 | 追加 B27-B32 |
| 事故证据目录 | 目标项目 `_scratch/` 与 `.ae-state/`，保留在用户物理备份和原项目 |

本报告不复制目标项目源码、完整 Prompt、Worker transcript 或可能含用户数据的日志。

## 3. 已观察事实

以下内容来自用户提供的账单/终端信息和对目标项目只读检查。

### 3.1 成本与规模

| 指标 | 观察值 |
|---|---:|
| Input tokens | 约 58m |
| Cache tokens | 约 341m |
| Output tokens | 约 1m |
| Input credits | 约 25,000 |
| Output credits | 约 800 |
| Prompt JSON | 153 份，约 3.7 MB |
| Spawn proof | 152 份 |
| Checkpoint DB | 约 60 MB |

Prompt 阶段分布：

| Stage | 次数 |
|---|---:|
| developer | 48 |
| critic | 41 |
| component_verifier | 40 |
| plate_deep_audit | 15 |
| architect | 5 |
| system_deep_audit | 1 |
| system_verifier | 1 |
| gap_scan / gap_review | 2 |

Tick 144 的 `system_deep_audit` rendered JSON 约 117 KB，其中 `spawn` 结构约
76 KB。Prompt Log 只证明 Core 渲染内容，不等于模型服务收到的完整会话输入。

### 3.2 终止错误

模型服务返回：

```text
InvalidParameter
Range of input length should be [1, 983616]
```

错误发生在 Tick 146 的 Developer 工作继续前，属于宿主请求进入模型推理前的输入
校验失败，不是目标 TypeScript 应用异常。

### 3.3 计划与状态异常

Architect 生成包含 27 个 batch 的计划：

```text
B1-B21 + B27-B32
```

后继 Action 却显示：

```text
tick=146
stage=developer
batch_id=B1
done_tasks=85
total_tasks=0
completion_pct=0.0
```

这组状态违反基本不变量：

- 已完成任务数不得大于总任务数。
- 已完成 B1 不得被普通修复计划重新激活。
- active batch 必须是当前计划中未完成且依赖满足的工作。

### 3.4 验证假通过

最终 Test Gate 同时记录：

```text
vitest 未收集到测试 (exit=5)
plugins: anyio, asyncio
collected 0 items
no tests ran
```

内容实际是 pytest 输出，但 Gate 标记 `passed=true`。这证明至少存在：

- runner 选择或输出标注错误；
- 非零退出被错误接受；
- 零测试未 fail-closed；
- Gate message 与真实执行工具不一致。

### 3.5 空文件快照

最终全部 Gate 的 `files_snapshot_sha` 为：

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

该值是空内容 SHA-256。对于已有源码和测试的非空项目，空快照不能作为通过证据。

### 3.6 上下文漂移

- 目标项目 BEACON 仍停留在初始化阶段，与 B1-B26 已完成的实际进度冲突。
- Tick 146 `session_summary` 重复记录多次 lint/audit 失败，但同一 Action 的 Gate
  summary 又显示通过。
- 当前 `llm-calls.jsonl` 仅包含 event、gate_results、stage、tick、timestamp，
  没有 input/cache/output 字段，不能支持 Token 归因。

## 4. 已确认结论与待验证推断

### 4.1 已确认

| 结论 | 证据 |
|---|---|
| 请求因输入长度超限被服务拒绝 | API 400 原始错误 |
| 新计划后 active batch 回到 B1 | Tick 146 Action |
| 进度投影非法 | done=85、total=0 |
| 验证存在假通过 | pytest 0 tests/exit=5 与 passed=true 同时出现 |
| 快照证据为空 | 全部 Gate 使用空内容 hash |
| 当前审计无法归因 Token | audit schema 无 usage 字段 |

### 4.2 高可信推断，需由 T303/T318 验证

| 推断 | 依据 | 验证任务 |
|---|---|---|
| 单会话历史反复重放是 Input/Cache 膨胀主因 | 146 Tick、341m cache、Prompt Log 仅 3.7 MB | T303、T318 |
| 多 Agent 和深审计大正文进一步放大主会话 | 152 proof、117 KB system audit Action | T315、T318 |
| 全量计划替换丢失完成状态 | 新计划包含旧 batch，后继指针回 B1 | T303、T306 |
| Checkpoint 反复保存重复副本 | 小型项目 DB 达约 60 MB | T317 |

不得在实现前把这些推断写成已经通过实验确定的成本比例。

## 5. 根因模型

```text
长期 EngineeringThread
        │
        ├─被绑定到单一宿主会话
        │      └─历史、工具输出、Worker 结果持续重放
        │              └─输入/缓存膨胀 → API 输入超限
        │
        ├─修复计划使用整体替换
        │      └─完成集合与新 revision 失配 → B1 回退
        │
        ├─验证证据缺少工具链和文件快照强绑定
        │      └─pytest/0 tests/空 hash 仍通过
        │
        └─自由文本摘要与 BEACON 参与认知恢复
               └─状态漂移、重复失败信息和错误续接风险
```

系统层根因不是“单个 Prompt 太长”，而是长期业务状态、宿主会话、计划版本、验证
证据和大产物之间缺少确定性边界。

## 6. 影响评估

| 影响 | 严重度 | 说明 |
|---|:---:|---|
| 成本不可控 | P0 | Input/Cache 远高于 Output，无法逐 Tick 归因 |
| 长流程不可完成 | P0 | 达服务输入上限后被动终止 |
| 重复修改风险 | P0 | 已完成批次可能重新执行 |
| 验证可信度丢失 | P0 | 零测试、错误 runner、空快照仍可通过 |
| 恢复不确定 | P1 | recap/BEACON 与事件状态矛盾 |
| 存储膨胀 | P1 | Checkpoint DB 与项目规模不相称 |

## 7. 问题—任务追踪矩阵

| 问题 | 任务 | 完成出口 |
|---|---|---|
| 事故证据可能随会话丢失 | T322 | 永久报告、脱敏证据索引和任务矩阵可供新会话读取 |
| 故障不可稳定复现 | T303 | 146-Tick 抽象 fixture 由 RED 转 GREEN |
| runner 错配、零测试、exit 非零假通过 | T304 | 工具链匹配且全部错误 fail-closed |
| 空快照和证据失配 | T305 | Gate 与非空文件 manifest/hash 强绑定 |
| B1 回退、done/total 非法 | T306 | PlanPatch、revision 和投影不变量生效 |
| 长线程绑定单会话 | T308-T313 | 三个以上 session 等价完成 150+ Tick |
| 完整历史进入 Prompt | T314 | Stage Context Selector 有界选择 |
| Worker/审计正文回灌 | T315 | ArtifactRef + 有界 receipt |
| Token 无法归因 | T316 | thread/session/tick/stage/worker Usage Ledger |
| Checkpoint/Prompt 存储膨胀 | T317 | 永久事实与可重建副本分层 |
| recap/BEACON 漂移 | T323 | 摘要仅信息性，状态锚点漂移显式告警 |
| 修复循环、Worker、Deep Audit 无上限 | T324/T342 | 达预算后停止扩张并诊断，不用换会话绕过 |
| 成本改善无法证明 | T318、T320 | 单/多会话对照和可归因成本报告 |
| 双宿主真实链路风险 | T319-T321 | Claude/Codex 真实项目门禁通过 |

## 8. 补充治理要求

### 8.1 状态锚点和自动摘要

- Event Store/Projector 是业务进度唯一事实源。
- BEACON 是人工设计锚点，过期时告警，但不得覆盖投影。
- 自动 recap/session summary 只作信息展示，不参与路由、计数、完成判定或恢复。
- 摘要与 Gate/投影矛盾时展示 drift，不得静默选择摘要。
- Capsule 从结构化投影构建，禁止从聊天历史自由概括状态。

### 8.2 修复循环和 Agent 预算

版本化策略至少声明：

- 单 thread、stage 和 finding source 的最大修复轮次；
- 每个 Stage 的 Worker 数量上限及总 Worker 预算；
- Plate/System Deep Audit 的触发频率和重跑条件；
- 单次 Worker receipt、Artifact 和 Prompt 字节上限；
- 达流程 hard limit 后停止扩张并生成不收敛诊断；正常上下文交由宿主自动 compaction；
- 禁止 Architect 无上限追加修复批次。

达到上限必须产生结构化事件和原因，不得静默降低验证标准。

## 9. 当前处置与禁止事项

### 9.1 当前处置

- 保留目标项目 `_scratch`、`.ae-state` 和账单摘要作为外部原始证据。
- 本报告只保存脱敏摘要、证据指针和任务映射。
- v5.8 采用单内核渐进扩展，不恢复 Core 内 LLM Runtime。

### 9.2 Phase 64 完成前禁止

- 不将中等规模无人值守真跑作为发布通过证据。
- 不从 Tick 146 的 B1 Action 直接继续。
- 不把现有 Test Gate 的 passed 当作真实 Vitest 验收。
- 不通过减少安全、Gate、Guardrail 或五层验证规避成本。
- 不删除原始事故证据；物理清理必须另行授权。

## 10. 安全恢复建议

1. 冻结并备份现有事故状态。
2. 通过 T303 fixture 固化 B1 回退、非法计数和验证假通过。
3. 完成 T304-T306 后重新确认 B1-B26 的真实完成集合。
4. 将 B27-B32 转为基于明确 revision 的 PlanPatch。
5. 在新宿主会话中从受校验 Capsule/active Action 恢复。
6. 使用正确 Vitest、lint、type-check、build 和非空文件快照重新验收。
7. Phase 65-67 完成后再执行完整中等规模双宿主真跑。

## 11. 关闭标准

本事故只有在以下条件全部满足后才能关闭：

- T303-T321 与 T323-T324 全部完成；
- 146-Tick 故障 fixture 全部通过；
- Claude Code 与 Codex 的真实项目均在宿主自动 compaction 下无人工交接完成；
- input/cache read-write/output、活动窗口和 Core payload 分项可归因，测量不得缺失；
- 没有批次回退、非法进度、错误 runner、零测试或空快照假通过；
- 成本报告可以解释至少 95% 的宿主已报告 usage；
- 自动摘要和过期 BEACON 的负向测试证明不会影响 Core 状态；
- 修复、Worker 和 Deep Audit 达预算后确定性停止扩张；
- 全量测试、覆盖率、静态检查和发布门禁通过。
