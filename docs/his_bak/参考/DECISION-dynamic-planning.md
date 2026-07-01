# 动态规划方案：Round 后重新生成 Plan

> 决策文档 | 2026-06-20

## 问题

当前设计是**静态规划**：Orchestrator 在项目开始时一次性生成全部 Rounds + Tasks（plan_output.json），run-round.sh 逐 Round 执行。

**实际开发中发现**：每轮执行后，新的信息会让后续任务变得更清晰、更细化、甚至新增。静态规划会在 Round 2 之后就与实际需求脱节。

```
静态规划（当前）:
  plan_output.json (Round 1-5)
  → Round 1 → Round 2 → Round 3 → ...
  后续 Round 不会更新，越来越不准

动态规划（需要）:
  生成 Round 1
  → Round 1 + Post-Round 审计 → 发现新 Tasks + 细化剩余
  → 生成 Round 2（基于最新状态）
  → Round 2 + Post-Round 审计 → 继续发现
  → 生成 Round 3
  ...
  → 退出条件满足 → 停止
```

## 方案

### 核心思路：Rolling Plan

```
Phase 2: 规划（Orchestrator，改为每轮执行）

Round 1:
  1. Orchestrator 读 specs + BEACON + goal.yaml
  2. 生成 Round 1 plan（仅当前轮，不预测后续）
  3. Round 1 执行 → Post-Round 审计
  4. 审计产出:
     - P0/P1 → Round 1-add（修复）
     - P2 建议 → extract_new_tasks()
     - 从执行结果中细化的后续任务

Round 2:
  1. Orchestrator 重新规划:
     输入: specs + BEACON + goal.yaml
           + Round 1 执行结果
           + Round 1 审计发现的新 Tasks
           + carryover-issues
     输出: Round 2 plan

  2. Round 2 执行 → Post-Round 审计 → 同上

Round N:
  1. Orchestrator 重新规划（与 Round 2 同理）
  2. 检查退出条件 → 继续 or 停止
```

### 退出机制

三个条件，满足任一即退出：

| 条件 | 判定 | 说明 |
|------|------|------|
| **Goal 达成** | 对照 goal.yaml criteria，全部满足 | 主要退出条件 |
| **停滞检测** | 连续 2 轮无新增 P0/P1 任务 AND 无新增 Task 生成 | 避免空转 |
| **硬上限** | 总 Round 数 ≥ `max_rounds`（默认 50） | 安全网 |

```
Orchestrator 在每轮规划前检查:

  if goal.check_all_criteria():
    → ✅ Goal 达成，项目完成
  elif consecutive_no_progress >= 2:
    → ⚠️ 停滞，建议人工审查或结束
  elif total_rounds >= max_rounds:
    → 🛑 达上限，强制人工决策
  else:
    → 继续生成下一 Round plan
```

### plan_output.json 格式更新

从"全部 Rounds"变为"当前 Round + 剩余队列"：

```json
{
  "meta": {
    "mode": "rolling",
    "max_rounds": 8,
    "total_completed": 2,
    "goal": { "criteria": [...], "completed": [...] }
  },
  "current_round": {
    "id": 3,
    "goal": "增强功能",
    "tasks": [
      { "id": "S17", "desc": "--dry-run 模式", "source": "plan_original" },
      { "id": "S18", "desc": "--revert 回退", "source": "plan_original" },
      { "id": "N01", "desc": "补充 user 模块文档", "source": "audit_round2" },
      { "id": "N02", "desc": "auth API 契约增加 rate-limit", "source": "audit_round2" }
    ]
  },
  "remaining": [
    { "id": "S15", "desc": "Monorepo 子项目初始化", "priority": "P1" }
  ]
}
```

**字段变化**：
- 新增 `source` 字段：标注 Task 来源（`plan_original` 原始规划 / `audit_roundN` 审计发现）
- `current_round` 替代 `rounds[]` 数组——只包含当前轮
- `remaining` 替代预定义的后几轮——待 Orchestrator 重新规划时再分配

### 与 Post-Round 审计的联动

```
Round N Close
  ├─ Post-Round 审计 → audit-report.md
  │   ├─ P0/P1 → create_fix_tasks() → Round N-add
  │   └─ P2 → extract_new_tasks() → 新 Task 候选
  │
  ├─ 收集执行结果:
  │   - 哪些原始 Task 完成了？
  │   - 哪些原始 Task 比预期复杂，需要拆分？
  │   - carryover-issues 新增了什么？
  │
  ├─ Orchestrator 重新规划:
  │   输入: 原始 remaining Tasks
  │         + extract_new_tasks() 的新增
  │         + 执行中细化的子任务
  │   输出: Round N+1 plan
  │
  └─ 退出检查 → 继续 or 停止
```

### 与静态规划对比

| 维度 | 静态规划 | 动态规划 |
|------|---------|---------|
| 规划时机 | 项目开始时一次性 | 每轮结束后 |
| 输出 | 全部 Rounds 预定义 | 仅当前 Round + remaining |
| 适应性 | 后续 Round 越来越不准 | 每轮基于最新状态重新评估 |
| 复杂度 | 低 | 中（需要退出条件） |
| 适用场景 | 需求完全明确的短期项目 | 需求渐进清晰的中长期项目 |

### 实施影响

| 文件 | 变更 |
|------|------|
| `specs/agent-collaboration-layer.md` | Orchestrator 规划从一次性→滚动式 |
| `specs/quality-gate-upgrade.md` | Post-Round 审计增加重新规划触发 |
| `skills/agent-orchestrator/SKILL.md`（原 `runtime-agent/agent-orchestrator/SKILL.md`，已迁入 project-engineering-init） | start-round 改为滚动规划模式 |
| `multi-agent-runtime/references/` | 同步更新 |
| `TRAINING.md` | 更新 Plan-to-Loop 专题为动态规划 |

### 退出机制详细设计

```
退出检查（Orchestrator 在每轮规划前执行）:

check_exit():
  1. 检查 goal.yaml criteria:
     for c in goal.criteria:
       if not c.verified: return CONTINUE
     return GOAL_ACHIEVED                    ← ✅ 主要退出点

  2. 检测停滞:
     new_tasks_this_round = count(source="audit_roundN")
     if new_tasks_this_round == 0:
       consecutive_no_progress++
     else:
       consecutive_no_progress = 0
     if consecutive_no_progress >= 2:
       return STAGNANT                         ← ⚠️ 停滞退出

  3. 硬上限:
     if total_rounds >= max_rounds:
       return MAX_ROUNDS                       ← 🛑 安全网

  4. 正常继续:
     return CONTINUE
```
