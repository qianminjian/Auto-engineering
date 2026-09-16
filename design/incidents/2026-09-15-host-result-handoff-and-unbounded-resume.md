# 2026-09-15 宿主结果交接与无界续跑事故复盘

## 结论

本次 Down 不是 Voice Clone 业务代码导致，而是宿主在 `architect` Action 的结果交接边界连续违反合同，Loop 又把“可修复协议响应”“不可修复终态”和“宿主进程退出”混成了一个控制语义。结果是：错误结果被重复提交、修复预算被耗尽、lease 仍声明 `CONTINUE`，宿主继续尝试同一条坏路径，最终报告 `HOST_RESULT_REPAIR_EXHAUSTED`。

根本原则保持不变：主 Agent 是唯一 Coordinator；Python 只执行一次 Tick；EngineState 是投影，EventStore/Reducer 是唯一 Loop 事实链；Worker 事实由宿主原子交接，不能由 Coordinator 手工伪造；旧 Supervisor、Round、Checkpoint、UsageLedger 和兼容旁路不恢复。

## 外部真跑证据

证据来源为外部 Voice Clone 项目的只读报告：`_scratch/auto-engineering-failure-report.md`。本项目只修复 Loop，不修改该报告或其项目文件。

- Build 为 `5.8.0-rc.5+sha256.887b80d3ee644188`，阶段为 `architect`，Core 中仍有一个 active Action。
- Architect Worker 实际生成完整 5 个 batch、19 个 task；Coordinator 第一次只提交 11 个 task，Core 正确拒绝 `ARCHITECT_RESULT_COVERAGE_LOSS`。
- 后续又把 Worker 外层 envelope（`worker_id/status/payload/summary`）写入 Coordinator Result 文件；当时没有按当前单 Worker 的已认证 outcome 确定性解包。
- 错误候选重复进入 finalize/validate，journal 两次记录 `HOST_EVIDENCE_INVALID`，之后 `repairable=false`，最终报告 `HOST_RESULT_REPAIR_EXHAUSTED`。
- EventStore 有 39 个事件，最后一个是 Architect `ActionIssued`，没有 Architect `ResultAccepted`；因此 active Action 本身不是 EventStore 损坏，而是没有合法 Result 被接受。
- active lease 仍为 `CONTINUE`、`continuation_required=true`、`yield_allowed=false`，与 repair 已耗尽的宿主事实冲突；续驱动缺少 journal 闸门。
- 6 份 prompt artifact 合计 129,168 bytes，只是序列化文件大小，不能换算成模型 token。报告没有 provider input/output token 或费用字段。

## 设计与实现的差异

| 设计要求 | 事故中的实现偏差 | 后果 |
|---|---|---|
| Worker 产出先落私有 outcome，Coordinator 只消费已认证事实 | Coordinator 文件接受了 Worker 外层 envelope，边界没有做确定性归一化 | 业务 payload 被错误地当成 envelope 校验，产生无意义 repair |
| 一个 Action 的结果修复必须复用同一 Action，并在预算耗尽后停止 | 续驱动只看 status/lease，不看 action-scoped OutcomeJournal | `repairable=false` 仍被重新送回宿主 |
| 可修复拒绝是合法协议控制响应；不可修复才终止 | CLI 的不同错误分支曾混用 0/1，修复响应容易被宿主误判为进程 Down | 过度收紧会中断正常 repair，过度放松会吞掉终态错误 |
| Setup 是 capability-only；Core 以文件基线和 ProjectProfile 事实校验 | 宿主先创建了业务源码/测试，且用 `--passWithNoTests` 绕过测试证明 | Setup 多耗 4 次 Action/Tick，延迟进入 Architect |
| Python 只做单 Tick，宿主负责连续驱动 | 这次没有发现第二套 Loop；问题是宿主边界的合同消费不完整，而不是应恢复 Supervisor | 不能用增加 Supervisor 或 Python 内循环解决 |

## 本次 Loop 修复

1. `finalize/validate` 的可修复 repair 保持退出码 0；`HOST_RESULT_REPAIR_EXHAUSTED` 等不可继续状态退出码 1，避免正常 repair 被误判为 Down，同时让真正终止态停止续跑。
2. `continuation_driver` 接收当前 `host-runtime/outcomes` 目录；同一 Action 的 journal 为 `rejected/assembly_rejected + repairable=false`、损坏或身份不匹配时，续驱动输出 `stop`。
3. `ae-host-run` 显式把 canonical OutcomeJournal 目录传给续驱动；不读取旧状态模型，不调用 Tick，不创建 Action。
4. 单 Worker 的 Coordinator 文件只有在 Worker ID、状态、摘要、payload 与已收集 outcome 完全一致时才解包为业务 payload；多 Worker 或任何不一致继续 fail-closed。
5. 在原生宿主工具边界拒绝 `--passWithNoTests`；Setup 新增业务文件仍由设计规定的 Core 基线/ProjectProfile 闸门判定，不用文件名猜测替代事实校验。

## 后续完成计划（不翻转设计）

### P0：新鲜双宿主产品 L4

1. 用同一新 Build 完成独立安装预检：Build Identity、项目根、设计文档 digest、canonical `scripts/ae-run` 和插件入口逐项留证。
2. 在空的真实 Voice Clone 项目分别运行 Codex 与 Claude Code 的一次设计驱动命令；只由主 Agent 按 Action 的 `finalize → validate → tick` 连续驱动，Worker 只通过原生宿主能力执行。
3. 回放并现场覆盖：Setup 越界、零测试、Architect 19-task 完整计划、Coordinator 截断、单 Worker envelope、Worker wait 超时、owner 不确定、迟到结果、重复结果、repair、repair exhaustion、跨进程 resume。
4. 每个宿主都必须形成唯一 `ActionIssued → ResultAccepted → ... → TERMINAL` EventStore 因果链；不能用 archive smoke、prompt 文件、journal 或 lease 单独宣称完成。
5. 通过真实业务 Gate：上传音频格式、录音、转换、API/设备、页面交互和浏览器 E2E；外部 API 全部使用隔离测试替身，真实设备/服务验收单独留证。

### P1：发布前质量与可观测性

1. 覆盖率保持不低于 90%，关键 Loop/Host recovery E2E 保持不低于 80%。
2. 产品验收报告明确区分 `archive_smoke`、`product_install`、`product_business_acceptance`、`recovery_canary`，任何一项缺失都不能标记 P0-E2E 完成。
3. 用量只报告 provider/宿主真实提供的 token 字段；没有字段时报告“不可得”，不得用 prompt bytes、时间或 Action 数推算 token。

## Token 与时间口径

事故报告本身没有 provider token/cost 字段，因此无法从当前项目准确得出本次外部 Loop 的模型 token 消耗。可确认的量只有 6 份 prompt artifact、129,168 bytes，以及 39 个 EventStore 事件。

此前当前 Codex 工作目标的内部 telemetry 曾出现约 29,553,774 tokens、160,020 秒（约 44.5 小时）的累计值；该值是本代理工作目标的内部工具/上下文消耗，不是 Voice Clone 宿主或模型供应商账单，不能冒充应用 token。当前目标 telemetry 已不可回查，后续报告必须分开这两种口径。
