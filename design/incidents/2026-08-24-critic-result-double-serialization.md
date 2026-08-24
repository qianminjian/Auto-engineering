# Critic Result 二次序列化事故

> 状态：自动门禁修复完成，待真实产品复验｜来源：2026-08-24 Voice Clone 真实产品运行

## 事实

- Loop 已完成初始化、Gap、Research、Architect、B1-B3 Developer 与 Critic Worker。
- Critic Worker 返回结构化结果，但 `coordinator-result.json` 中 `findings` 被写成 JSON 字符串。
- Finalizer 接受该业务 payload 并生成 Result；Core 在随后提交时以
  `RESULT_VALIDATION_ERROR` 拒绝：`findings` 应为数组，实际为字符串。
- Worker 超时曾按 `HOST_WORKER_TIMEOUT` 有界重试并成功，不是本次终止根因。

## 根因

1. Canonical Action 的 `expected_format` 是自然语言示例，不是可执行类型契约。
2. Host Finalizer 只检查 Coordinator 字段白名单，不在 journal/Result 写入前验证类型。
3. Invocation Backend 只以输出文件存在作为 Action 成功条件，不校验业务 payload。
4. 类型错误跨过 Action context 边界后才由 Tick Core 发现，原 context 已结束，无法原地确定性修复。

## 修复不变量

- Core 必须随 Action 下发机器可执行的业务结果字段类型。
- Finalizer 必须在写 committed journal 前完成字段集合、必填项和类型校验。
- 合同外字段必须在 inline/spawn 两条路径一致拒绝；新的展示字段未声明机器类型时，
  Action 构建必须失败，不得静默生成不完整合同。
- 对“合法 JSON 被二次字符串化”只允许一次确定性解码；解码后仍不匹配则 fail-closed。
- Finalizer 生成的 Result 必须可被当前 Stage Result validator 接受，不能把错误推迟到 submit。
- Worker timeout、重试次数、Action identity 与工作文件继续由现有状态机绑定，不允许手工路径拼接。
- 宿主操作在返回 Core Action 前抛出稳定协议异常时，也必须留下 ERROR 停止报告，
  且不得将该报告写回为业务 Result 或推进 Tick。

## 关闭标准

- Critic 的字符串化 `findings` 可被 Finalizer 恢复为原生数组并一次提交成功。
- 非 JSON 字符串、解码后类型不符、缺失必填字段在 journal 写入前被拒绝。
- Developer、Verifier、Deep Audit 的数组/对象字段覆盖相同路径。
- Architect 的普通计划、PlanPatch、Design Change 与 Plan Reconciliation 分支均有对齐的类型和语义合同。
- 自动门禁、全量测试、静态检查与真实产品重跑通过。
