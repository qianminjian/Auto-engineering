# 2026-09-28 私有 Worker 产物损坏导致恢复死锁

## 结论

这次故障不是 Worker 没有完成，也不是 Core 需要重新设计一套循环。真实业务结果已经由 native Worker 返回，但私有 `outcome_path` 只有半个 envelope。原实现把私有文件当成唯一业务权威：Collector 看到它不完整就报 `HOST_WORKER_ATTESTATION_MISSING`，`record-worker-outcome` 又拒绝用同一 Action 已绑定的 native result 修复；恢复投影因此要求“再次回写同一个无法被当前路径接受的结果”，同时禁止 respawn，形成不可达状态。

## 根因链

1. Worker 业务 payload 与 Host attestation 字段混在一个 envelope 中，私有文件缺 `worker_id/summary` 被误当成 Worker 交付失败。
2. `execution_assembler.py` 的直接回写路径只允许“私有文件完整”或“私有文件完全缺失”两种输入，没有第三种“私有文件损坏但 native 结果有效”。
3. 恢复投影只有 `worker_attestation_pending`，没有显式的 artifact repair 状态，因此无法表达“不要重跑，修复序列化”。
4. 旧 native 探测只检查文件存在/JSON 可读，不能证明业务对象唯一有效；若简单放宽，会重新引入猜测式恢复风险。

## 修复后的唯一状态路径

```text
private artifact valid
  -> record-worker-outcome -> finalize -> validate -> submit

private artifact missing
  -> bound native result valid -> record-worker-outcome -> finalize -> validate -> submit

private artifact malformed + bound native result valid
  -> worker_artifact_repair (quarantine, no spawn)
  -> record-worker-outcome -> finalize -> validate -> submit

private artifact malformed + native invalid/unbound
  -> structured host protocol failure, same Action, no respawn
```

这里仍然只有一个 Python Tick、一个 Main Agent Coordinator、一个 Host Assembler 和一个 native business parser。`worker_artifact_repair` 是恢复投影，不是第二套循环，也不写入 Core 的另一份状态事实。

## 不变量与验收

- 原私有文件不覆盖，只写入 Action/Worker/代际/围栏/摘要哈希的 quarantine metadata。
- native result 必须来自当前 Action 声明的 `native_result_path`，并由同一个 canonical parser 唯一解析。
- repair 重复执行结果相同，quarantine 文件和共享 outcome 不重复增长。
- `spawn_permitted=false`，不会消费 Worker 失败预算，不会创建新 generation。
- native 无效、路径漂移、身份/状态不一致仍 fail-closed；不能用 `unreported` 伪造 completed。

实现与回归覆盖：`HostExecutionAssembler` 直接回写、Collector 恢复分类、CLI recovery projection、幂等 quarantine。后续加固已让恢复探测直接复用 canonical native parser；非空但不完整、嵌套歧义或含宿主字段的 native 文档不会再被误投影为 `worker_attestation_pending`。外部 Voice Clone 报告仅作为只读故障证据，本文件和代码均不修改外部项目。
