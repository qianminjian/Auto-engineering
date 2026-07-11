## PLAN-REFINE 输入契约 (RefineRequest, §B6.10)

当 action 的 `feedback.mode == "PLAN_REFINE"` 时, `feedback.refine_request` 承载
一份归一后的重规划输入 (取代旧的散注 audit_findings)。结构:

```
refine_request:
  source: 触发回源 (component_verifier | plate_deep_audit | system_verifier | system_deep_audit)
  scope_plate / scope_component: 重规划聚焦范围 (system 级为 null = 全局)
  gaps: [ {kind, design_ref, detail, suggested_action, severity, location} ]
```

逐条 gap 按 `kind` 消费, 只重规划 `scope_*` 指向的范围, 不全量重排 batch_plan:

| kind | 动作 |
|------|------|
| `MISSING` | 产出**新 batch** (或向现有组件追加 task) 覆盖缺口, `design_section` 指向 `design_ref` |
| `DIVERGED` | 二选一并在 `plan` 说明: ① 产出修正 task (改代码回归设计)；② 若代码更优, 更新设计文档并标 `design_docs_updated` (走 C.11 同步, 不产 task) |
| `AUDIT_FINDING` | 产出修复 task, `file_targets` 取 `location` 所在文件 |

`suggested_action` 是每条 gap 的建议动作, 按需采纳。同一源第 2 次仍未解决即会被
REFINE_LIMIT 中止 —— 本轮务必产出能实质闭合 gap 的计划, 不要空转。
