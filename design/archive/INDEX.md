# design/archive 历史资产索引

> 创建：2026-07-27｜用途：只读审计与决策追溯

## Phase 50 重构前完整快照

| 归档文件 | 原路径 | 内容 |
|---|---|---|
| `legacy/BEACON-pre-phase50.md` | `design/BEACON.md` | 101+ 项历史决策、演进日志与待办 |
| `legacy/IMPLEMENTATION-TRACKER-pre-phase50.md` | `design/IMPLEMENTATION-TRACKER.md` | Phase 1-50、T-task 与验证历史 |
| `legacy/v5.6-Design-Loop-full-history.md` | `design/v5.6-Design-Loop.md` | 10k+ 行完整演进规格 |
| `legacy/INDEX-pre-phase50.md` | `design/INDEX.md` | 旧索引、合并日志与 his_bak 清单 |

## 既有历史

`design/his_bak/` 与 `docs/his_bak/` 是早期版本归档；其细目见
`legacy/INDEX-pre-phase50.md`。Phase 50 不改写这些历史文件。

## 使用规则

1. 历史内容不可直接覆盖当前 BEACON 或当前设计。
2. 引用历史决策时同时给出归档路径与当前替代项。
3. 恢复被退役能力属于设计状态翻转，必须先获用户批准。
4. 归档文件只读；勘误写入当前索引，不回写历史正文。
