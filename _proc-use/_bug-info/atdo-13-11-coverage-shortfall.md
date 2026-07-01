# atdo-13-11 — Coverage Shortfall (用户硬指标未达成)

> 创建: 2026-07-01 09:55 | 状态: open | 等级: 用户硬指标未达成，非项目 bug

## 现象

Phase 12.11 验证 v2.0/v5.0 全量覆盖率，期望 ≥90%（用户硬指标），实测 **89%**。

差距：1pp（约 39 行未覆盖）

## 实测数据

- **TOTAL**: 3887 statements, 429 missed, **89%** coverage
- **Tests**: 1103 passed, 2 skipped, **0 failed**
- **Acceptance**: 20/20 PASS
- **Smoke**: 5/5 PASS
- **方法论**: real（真实 pytest + 真实 acceptance + 真实 smoke 三套独立验证）

## Top 10 低覆盖模块（决定 89→90 的关键）

| % | 模块 | stmts | miss | 主要未覆盖区域 |
|---|------|------|------|--------------|
| 64 | `tools/test_tools.py` | 39 | 14 | 67-74, 79-88 (集成测试工具，外部依赖) |
| 74 | `cli/helpers.py` | 80 | 21 | 145-155 (错误路径分支) |
| 74 | `gates/coverage.py` | 58 | 15 | 152-158, 174-189 (覆盖率读取失败分支) |
| 77 | `cli/status.py` | 77 | 18 | 67-72, 148-149, 153-163 (JSON 边缘 case) |
| 77 | `config/environment.py` | 118 | 27 | 109-122, 231-235 (env var 缺失分支) |
| 77 | `loop/orchestrator.py` | 253 | 57 | 472-485, 711-745, 760-772 (早期退出 + 中断路径) |
| 78 | `tools/git_tools.py` | 64 | 14 | 118-121 (git error 分支) |
| 79 | `gates/contract.py` | 100 | 21 | 100-102, 261-262 (契约违规分支) |
| 80 | `gates/safety.py` | 65 | 13 | 208-215 (规则拒绝路径) |
| 80 | `gates/test.py` | 70 | 14 | 157-163, 193-195 (测试失败路径) |

**Top 5 重点修复目标**:
1. `tools/test_tools.py` 64% — 单模块差 5 行就能贡献 0.13pp
2. `cli/helpers.py` 74% — 21 行未覆盖，主要 145-155
3. `gates/coverage.py` 74% — 15 行未覆盖
4. `loop/orchestrator.py` 77% — **关键模块**，253 stmts × 57 miss，影响最大
5. `cli/status.py` 77% — 18 行未覆盖

## 根本原因分析

**为什么从 96%（Phase 12.8 loop/round.py）→ 89%（全量）**:
- Phase 12.8 只测了 loop/round.py 模块（96%）
- 全量加入所有模块后，包括 CLI/工具/外部依赖类代码天然偏低
- `tools/test_tools.py` (64%) 等与外部进程交互的工具行覆盖率低

**89% ≠ 89.x%**: 实测 89% 整数字符串显示，可能为 89.4-89.9，需更细粒度报告

## atdo 降级建议

按优先级评估（KISS/YAGNI）：

### 方案 A: 加测试刷到 ≥90% (推荐, ~30-60min)
针对 Top 5 加 ~40 行测试：
- test_tools.py: 加外部命令失败分支 mock
- cli/helpers.py: 加 145-155 错误路径用例
- gates/coverage.py: 加 coverage.xml 不存在分支
- orchestrator.py: 加 472-485 提前退出分支 (取消耗时最长)
- cli/status.py: 加 edge JSON case

**预期**: 89% → 90-91%，commit 后可达标

### 方案 B: 维持 89% 现状诚实交付
按 atdo 任务说明 "如覆盖率 <90% 仍 commit，标注 '用户硬指标未达成' + 列出 top 5 低覆盖模块 + atdo 降级建议"

本次采用方案 B（按 atdo 协议指示），但保留方案 A 作为 v5.0.x patch 路线图

## 决策

按 atdo Phase 12.11 指令：
1. ✅ 收集了真实覆盖率报告（`coverage.txt` 730 行）
2. ✅ 确认 acceptance 20/20 全 PASS
3. ✅ 确认 smoke 5/5 全 PASS
4. ✅ 1103 测试全 PASS，0 regression
5. ⚠️ 覆盖率 89%，未达 ≥90% 用户硬指标 — 诚实记录
6. ✅ 列 Top 5 低覆盖模块 + atdo 降级建议（方案 A 路线图）

## 后续行动

| 优先级 | 行动 | 预计 |
|--------|------|------|
| P1 | Phase 13 准备方案 A 测试增量（针对 Top 5 加 ~40 行） | ~30-60min |
| P2 | 评估 `tools/test_tools.py` (64%) 是否需要 mock 重写 | TBD |
| P3 | orchestrator.py 472-485 提前退出路径分解为可测小函数 | TBD |

## 不伪造原则

按 atdo 协议与 CLAUDE.md 红线，本次拒绝伪造或"调过门槛"。89% 即 89%，不做向上四舍五入到 90%，不在 commit message 写"≥90% achieved"。
