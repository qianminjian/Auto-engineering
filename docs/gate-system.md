# Gate System — 两体系说明 (v2.5 后 v1.0 退役)

> 创建：2026-06-26 | 更新：2026-06-28 | 位置：永久资产
> 决策依据：`design/BEACON.md` 决策 19/27

## v1.0 Guardrail（builtin.py）— v2.5 P0-FINAL 已退役

- 5 个内置 Guardrail：Requirement/PlanExists/GitClean/TestsPass/GitDiffExists
- 4 态结果：pass / block / drop / retry
- 用于 Phase 1 LoopEngine（`gates/gates.py` 旧路径）
- **v2.5 P0-FINAL 状态**：`gates/builtin.py` + `gates/guardrail.py` 已删除（commit 2994c7e），
  Guardrail 体系整体退役（BEACON 决策 27）。仅作历史参考保留本文档。

## v2.0 Gate（safety/lint/type_check/test/coverage/build/contract）

- 7 道 Gate：safety / lint / type_check / contract / test / coverage / build
- 返回 Verdict（passed / message / gate_name）
- 用于 v2.0 Orchestrator（`loop/orchestrator.py`）
- 每 Round 后自动执行（传入 gates 列表）
- **唯一保留的 Gate 体系**（v2.5 起）

## 关系

| 维度 | Guardrail (v1.0, 已退役) | Gate (v2.0, 唯一) |
|------|-------------------------|------------------|
| 位置 | `gates/builtin.py` (v2.5 已删) | `gates/{safety,lint,...}.py` |
| 调用者 | `GuardrailChain` (v2.5 已删) | `Orchestrator` |
| 结果类型 | `GuardrailResult` (4 态) | `Verdict` (2 态) |
| 收敛判定 | GuardrailResult.action | Verdict.passed + Verdict.message |
| 生命周期 | Phase 1 — v2.5 P0-FINAL 终止 | Phase 04 (v2.0) — 当前生产 |

## 未来

v2.5 起 v1.0 Guardrail 体系已退役，仅保留 v2.0 Gate 体系。无需"未来清理" — 已完成。
（如需扩展 Gate 体系，加新文件到 `gates/{safety,lint,type_check,contract,test,coverage,build}.py` 之外即可。）