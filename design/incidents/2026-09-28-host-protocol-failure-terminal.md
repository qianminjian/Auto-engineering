# 宿主 Worker 交接协议失败终态记录

日期：2026-09-28
范围：仅 Auto-Engineering Loop 宿主交接与恢复边界。

## 触发问题

私有 Worker artifact 或 native result 无法证明一个合法业务结果时，旧路径把协议错误写成
`HOST_WORKER_OUTPUT_INVALID`，随后 `WorkerFailureService` 又把它转换为
`HOST_WORKER_FAILED`。Core 因此把“宿主没有完成交接”误认为“Worker 业务失败”，进入
`resource_wait` 和 Worker 失败预算，重复恢复时会持续产生相同错误。

## 定型规则

1. 私有 artifact 损坏、但同一 Action 绑定的 native result 可由唯一 parser 解析：走
   `worker_artifact_repair`，隔离原文件，复用 native 结果，不重新 spawn。
2. native 缺失、不可解析、歧义、路径漂移或代际不匹配：记录
   `HOST_PROTOCOL_FAILURE`，保留同一 Action 和原始证据，不消费 Worker 业务失败预算，
   不重新 spawn。
3. Core 收到协议失败 Result 后返回有界 `HOST_PROTOCOL_RETRY_EXHAUSTED`，不再生成
   `resource_wait`。修复只能由宿主在同一 Action 上重新提交合法交接事实。
4. 协议 outcome 的诊断只包含 Action/Worker/generation、相对来源路径、存在性和截断
   SHA-256，不包含 native/private 原始业务正文。

## 验证证据

- Host/CLI/Tick 核心回归：333 passed。
- 业务回归（排除 macOS Xcode license 依赖的 Git guardrail 与 host-process 测试）：
  2726 passed，1 skipped。
- Ruff、mypy（244 个源码文件）、silent-except、line-count、git diff check 通过。
- 覆盖率：89%；项目要求的 90% 全量门禁仍受系统 Git/Xcode license 环境阻断，未将
  89% 虚报为 90%。

本轮补强后，当前采集器的无效交接中间分类也统一使用
`HOST_PROTOCOL_FAILURE`；`HOST_WORKER_OUTPUT_INVALID` 仅保留在历史 journal
迁移兼容边界，不再作为当前生产采集路径的协议名称。

续驱动边界也已补强：当 Outcome Journal 为 `protocol_failed`、协议失败类型，
或结果携带 `HOST_PROTOCOL_FAILURE` 时，即使退出顺序暂时保留 `CONTINUE` lease，
`continuation_driver` 也必须返回 `stop`，不得重复恢复同一 Action。

## 不变量

`HOST_PROTOCOL_FAILURE` 不得被映射为 `HOST_WORKER_FAILED`；有效 native repair 不得
退回协议失败；任一分支都不得创建第二套 Loop、第二个事实源或重复 Worker Action。
