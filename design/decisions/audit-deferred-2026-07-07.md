# Audit Deferred Items — 2026-07-07

> v5.5 全量代码审计 (11 P0 + 21 P1 + 11 P2) 中延后处理的 10 项。
> 每项含问题描述、延后理由、触发条件，供后续逐个消化。

---

## P1 (应短期修复)

### P1-3 — AUDIT_DIMENSIONS 常量零生产消费

- **问题**: `loop/deep_audit.py:23` 定义 `AUDIT_DIMENSIONS`（3 个审计维度描述映射），但 `DeepAuditOrchestrator` 未使用，仅在测试中验证存在
- **方案**: A) 删除，Phase 5 再加回来 B) 保留，等 Phase 5 消费
- **风险评估**: 删除无影响（当前 Phase 1 骨架用 AuditGate 本地扫描，不走 3-agent 并行）；保留零维护成本
- **延后理由**: 设计意图是供 Phase 5 DeepAuditOrchestrator 3-agent spawn 并行审计使用。当前 Phase 1 骨架尚未消费，属预留常量
- **触发条件**: Phase 5 DeepAuditOrchestrator 3-agent spawn 实现时启用；若到 v6.0 仍未消费则删除

### P1-4 — ConvergenceFacade 单消费者包装

- **问题**: convergence_facade.py (147 行) 仅 Orchestrator 一个消费者，属于单消费者 delegate
- **方案**: A) 内联到 Orchestrator（增大 ~450→~550 行）B) 保持独立模块
- **风险评估**: 内联使 Orchestrator 突破 500 行；保持独立增加 1 层间接调用
- **延后理由**: 147 行职责内聚（收敛判定），拆散后更难以理解。Orchestrator 本身 450 行核心循环是合理范围，但加 147 行后接近 600 行。等 Orchestrator 有下一轮重构需求时再评估
- **触发条件**: Orchestrator 需要下一轮架构重构时，或 convergence 逻辑需要修改时

### P1-12 — Design Doc Sync 执行力度

- **问题**: `_warn_design_docs_update` 仅 log warning 不强制执行，实际依赖 atdo Stage 4 规范约束
- **方案**: A) 在 Orchestrator 收敛判定前加硬检查（design/ 文件 mtime > 本轮开始时间）B) 保持软约束
- **风险评估**: 硬检查可能误报（设计文档未变更但代码无设计影响）→ 假阳性 block dev-loop
- **延后理由**: 当前 atdo Stage 4 规范约束在人工监督下有效。自动化强制执行需要更精准的变更检测机制
- **触发条件**: 出现因文档未同步导致的设计偏差事故时；或 DeepAuditGate 上线后

### P1-15 — ValueError → AEError 选择性升级

- **问题**: StageRouter、GuardrailChain 等模块用原生 ValueError 抛异常，不统一
- **方案**: 逐模块审查 → 判断是否应升级为 AEError → 添加对应 ErrorCode
- **风险评估**: 全量替换可能引入不必要的 ErrorCode（某些 ValueError 确实只是编程错误不应包装）
- **延后理由**: ~1-2 hr 工作，需逐处审查判断。当前所有 ValueError 都在内部路径，不会泄漏到用户
- **触发条件**: ErrorCode 体系下一轮扩展时一起处理

### P1-16 — os.environ 读取收敛

- **问题**: 5 个模块各自直接读取环境变量（`os.environ.get`），无统一 Settings 入口
- **方案**: 创建 Settings dataclass，集中管理所有 env var 读取 + 默认值
- **风险评估**: Settings 之前因 P0-1 被删除（原实现有问题）。重新设计需要确定 scope（只收敛 env var 还是包含所有配置）
- **延后理由**: 需要在设计层面确定 Settings 的 scope 和模式。当前 5 处分散读取不影响功能正确性
- **触发条件**: 新增第 6 个环境变量时强制执行收敛；或下一轮配置管理重构

---

## P2 (后续优化)

### P2-1 — Channel 子系统保留为休眠模块

- **问题**: Channel 子系统（`loop/channel.py`）当前无消费者，但设计对齐 LangGraph 参考
- **方案**: A) 删除 B) 保留为休眠模块（零维护成本）
- **延后理由**: 多 Agent 并发场景下有实际价值，对齐 LangGraph 参考设计。当前零维护成本（无 import、无运行时开销）
- **触发条件**: v6.0 架构评估时；或多 Agent 并发需求出现时
- **已记录**: memory/design-decision-channel-subsystem.md

### P2-5 — LANGUAGE_TOOLS re-export 简化

- **问题**: `_tools.py` → `registry.py` → `init_contract.py` 三层 re-export
- **方案**: 移除 `_default_tools_for` 私有函数的 re-export；`init_contract.py` 直接从 `_tools` 导入
- **延后理由**: 需要与 P1-16 (Settings 收敛) 一起考虑 — init_contract 的公开 API 可能需要重新设计
- **触发条件**: init_contract.py 公开 API 重新设计时

### P2-9 — `ae checkpoint save` 子命令文档缺失

- **问题**: `ae checkpoint save` CLI 已注册但 `docs/api-reference.md` 未记录
- **方案**: 补充 api-reference.md 中 checkpoint 子命令文档
- **延后理由**: 低优先级文档补充，不影响功能使用
- **触发条件**: 下一轮文档批量更新时

### P2-11 — BEACON.md 与代码不一致

- **问题**: BEACON.md Gate 数量 (8)、范围声明、版本号与 v5.5 实际状态不一致
- **方案**: 更新 BEACON.md: Gate 7+1、scope v5.5、版本对齐
- **延后理由**: 低优先级文档同步
- **触发条件**: 本文件创建同日已修复 (2026-07-07)

---

## 消化计划

| 优先级 | 编号 | 预估 | 触发条件 | 状态 |
|--------|------|------|---------|------|
| 中 | P1-15 | 1-2 hr | ErrorCode 扩展时 | 待处理 |
| 低 | P1-3 | 5 min | Phase 5 DeepAuditOrchestrator 3-agent spawn 时 | 待处理 |
| 低 | P1-4 | 30 min | Orchestrator 重构时 | 待处理 |
| 低 | P1-12 | 1 hr | DeepAuditGate 上线后 | 待处理 |
| 低 | P1-16 | 2 hr | 新增第 6 个 env var 时 | 待处理 |
| 低 | P2-1 | 0 | v6.0 架构评估时 | 待处理 |
| 低 | P2-9 | 15 min | 文档批量更新时 | 待处理 |
| ✅ | P1-7 | 30 min | Gate timeout 环境变量统一 | 2026-07-07 已修复 |
| ✅ | P2-5 | 15 min | LANGUAGE_TOOLS re-export 简化 | 2026-07-07 已修复 |
| ✅ | P2-11 | 15 min | BEACON.md 更新 | 2026-07-07 已修复 |

---

_创建: 2026-07-07 | 来源: v5.5 全量代码审计 (11 P0 + 21 P1 + 11 P2)_
