# 2026-09-08 真实 Claude L4：TaskOutput 宿主信封未规范化

## 结论

这次停滞不是 Worker 没有完成，也不是 Core 把合法结果判成失败。Architect Worker 已完成并写出完整计划；Claude Hook 将 `TaskOutput` 的宿主内部包装对象原样写入 native-result，Assembler 因此正确拒绝了非业务字段，主 Agent 又没有得到可直接执行的规范化正文，最终在 Architect 原地排查。

## 真实输入形状

Claude Code 返回的是对象而不是字符串：

```json
{
  "retrieval_status": "success",
  "task": {
    "status": "completed",
    "output": "...Worker 正文..."
  }
}
```

其中 `task.output` 才是 Worker 的原生正文；`retrieval_status`、`task_id` 和 `task.status` 是宿主观察元数据，不能进入业务 Artifact。

## 影响链

1. Agent 启动成功，native launch metadata 落盘。
2. TaskOutput 观察到完成，但 Hook 仅对字符串格式做 `<output>` 提取；对象格式被原样保存。
3. Assembler 看到 `retrieval_status/task`，按 Worker 业务边界拒绝，避免把宿主字段当成业务事实。
4. 协调器得到 `HOST_EVIDENCE_INVALID` 后尝试读取不存在的内部 `coordinator-result` 文件，未回到统一 recovery contract。
5. Core 保持 `architect`，没有错误终态，但用户看到“运行后卡住/崩溃”。

## 修复边界

- Claude Hook 只在 `task.status` 为完成态且 `task.output` 为非空字符串时，写入统一 `content[0].text` 原生正文。
- running/pending/failed 等状态不生成完成结果；仍保留当前 Worker 观察事实。
- 业务 JSON 解析、Host attestation、generation/fencing、Result 组装继续由既有统一边界负责。
- 不新增 Coordinator，不让 Python 解析模型业务结果，不修改 Core 的 fail-closed 规则。

## 验证

- 新增 `test_task_output_unwraps_completed_object_envelope`，证明宿主信封不会落入 native-result。
- 真实复验必须使用重建后的同一 Build，并确认 L4 至少越过 Architect；若后续出现业务设计 Gate 或预算耗尽，须单独记录，不得与本协议缺陷混为一谈。
