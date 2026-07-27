# design/ 当前资产索引

> 更新：2026-07-27｜当前与历史严格分层

## 当前权威资产

| 文件 | 用途 |
|---|---|
| `BEACON.md` | 北方之星、范围、当前决策与下一步（≤80 行） |
| `v5.6-Design-Loop.md` | 当前 Tick、Host Adapter、验证、配置与 Release 契约 |
| `IMPLEMENTATION-TRACKER.md` | 当前里程碑与验证证据 |
| `phase50-codex-migration-closure-design.md` | Phase 50 已批准定型设计 |
| `phase50-codex-migration-closure-PLAN.md` | Phase 50 实施步骤 |

## 辅助资产

- `discussion/`：设计推理和对标记录，不作为当前运行契约。
- `reference/`：小型示例规格。
- `2026-07-26-真跑验证-PLAN.md`：已执行真跑计划，待随 Phase 50 收口归档。

## 历史资产

统一入口：`design/archive/INDEX.md`。

历史文件不得作为新增能力的唯一依据；如需恢复历史设计，必须先与当前 BEACON、
代码和测试核对，涉及决策翻转时取得用户批准。

## 维护规则

1. 当前行为只写入当前权威资产。
2. 完成态计划和被替代规格迁入 `design/archive/`，保留追溯关系。
3. 不在当前文档中宣称退役 CLI、standalone driver 或真实产品安装已经可用。
4. 设计与代码不一致时默认补齐代码，不通过降低设计标准消除差异。
