# 开发流程颗粒度与机制总览

> 创建：2026-06-23 | 来源：多轮 Loop 开发流程讨论整合
> 涵盖：Plan / Round / Task / Loop / Commit / Push / PR / Review / CI 的层次、颗粒度、自动化机制

---

## 架构总图

```
plan_output.json          ◀── 项目全量任务计划，跨所有 Round
│
├─ Round N ─────────────────────────────────────────▶ PR（1:1）─────▶ [CI 7门全量]
│   │                                                    │
│   ├─ Task A (FE) ──── feat/T{round}-{seq} ──────────▶ push（1:1）─▶ [pre-push: type+test+cov]
│   │   │
│   │   ├─ L1 Loop #1
│   │   │   ├─ RED    → commit ──▶ [pre-commit: safety+lint+unit]
│   │   │   ├─ GREEN  → commit ──▶ [pre-commit]
│   │   │   └─ REFINE → commit ──▶ [pre-commit]
│   │   │                   │
│   │   │        ┌──────────┘
│   │   │        ▼
│   │   │   ① Critic 单审（Task 级 diff，6 维度）
│   │   │      ├─ APPROVE → Task 完成
│   │   │      ├─ MINOR   → 修复自动通过
│   │   │      └─ MAJOR   → 下一轮 Loop
│   │   │
│   │   ├─ L1 Loop #2（MAJOR 重做时）
│   │   │   └─ fix → commit ──▶ [pre-commit]
│   │   │        → ① Critic 单审 → APPROVE
│   │   │
│   │   └─ APPROVE → git push → [pre-push]
│   │
│   ├─ Task B (BE) ──── feat/T{round}-{seq} ────────▶ push
│   │   └─ L1 #1 → ... → APPROVE → push
│   │
│   └─ close-round ◀── Review 汇聚点 ──────────────▶ 收敛判定
│       ├─ ② Critic 交叉审（Round 级，跨 Task 冲突检测）
│       ├─ ③ @Review 全局审（Round 级，架构一致性）
│       └─ ④ 设计完整性审计（宣称 vs 实际实现逐条对照）
│
├─ Round N+1 ...
```

---

## 九层颗粒度对照

| 层次 | 包含关系 | 产出物 | Git 操作 | CI 触发 | Review |
|------|:------:|--------|:------:|:------:|:------:|
| **Plan** | N 个 Round | `plan_output.json` | — | — | — |
| **Round** | N 个 Task | 1 个 PR | 集成分支合并 | PR 级 7 门全量 | ②③④ |
| **Task** | 1~3 个 Loop | 1 次 push | `feat/T{N}-{seq}` | push 级 3 门 | ① |
| **L1 Loop** | N 个 Commit | 0~3 轮 Dev-Critic | — | — | ① 每轮触发 |
| **Commit** | 1 个原子变更 | 1 个 git commit | — | commit 级 3 门 | — |

---

## 各层详解

### Plan — 项目全量计划

- **定义**：`plan_output.json`，项目的完整任务规划，跨所有 Round
- **颗粒度**：1 个 Plan = N 个 Round
- **产出**：Task DAG，含优先级、依赖关系、角色分配
- **触发**：Orchestrator 首次 `start-round` 时创建
- **更新**：每轮 `close-round` 后重新评估 remaining Tasks

### Round — 交付单元

- **定义**：一次完整交付周期，包含 N 个并行 Task
- **颗粒度**：1 Round = 1 PR = N 个 Task
- **进入**：`start-round` — 动态规划，拆分 Task，写入 `plan.yaml`
- **退出**：`close-round` — 收集证据链 → Review 交叉检查 → 收敛判定
- **收敛条件**：P0 验收全过 AND Review APPROVE AND 质量门全绿 AND 无新增 P1+ 风险
- **超时**：>2h 强制检查，未完成 Task 降级到下一 Round
- **拆分例外**：若 Round 内 Task 间耦合度为 0，可标注 `merge_mode: independent`，允许拆成多个独立 PR

#### Round 内的 Task 并行条件（五原则）

| 原则 | 规则 |
|------|------|
| 文件隔离 | 模块间文件不重叠 → 可并行 |
| 契约优先 | 跨模块协作前先定义接口 |
| 依赖最小化 | 每 Task ≤2 个前置依赖 |
| 粒度均衡 | 每 Task 20-45 分钟 |
| 闭环 | 每 Task 可独立验证 |

### Task — 开发单元

- **定义**：一个 Agent 角色的完整开发任务
- **颗粒度**：1 Task = 1 次 push = 1~3 个 L1 Loop
- **输入**：四段式指令（目标 / 边界 / 验收标准 / 禁止项）
- **分支**：`feat/T{round}-{seq}`，如 `feat/T1-2`
- **完成条件**：Critic APPROVE + 证据链四件套齐全
- **阻塞**：3 轮 Dev-Critic 未 APPROVE → Orchestrator 介入

### L1 Loop — 迭代单元

- **定义**：一次完整的 PROPOSE→EXECUTE→VERIFY→REFINE 循环
- **颗粒度**：1 Loop = N 个 Commit（RED/GREEN/REFINE 各一个）
- **TDD 映射**：RED=PROPOSE, GREEN=EXECUTE+VERIFY, REFACTOR=REFINE
- **循环上限**：同一 Task 最多 3 轮（Dev-Critic 循环限制）
- **触发下一轮**：Critic 返回 MAJOR → Dev 修复 → 重新提交审查

### Commit — 原子变更

- **定义**：一个 git commit，只做一件事
- **颗粒度**：TDD 每步一个（RED/GREEN/REFINE 分阶段提交）
- **格式**：`<type>(<scope>): <subject>`（Angular 规范）
- **Hook**：Lefthook pre-commit 自动跑 Gate 0(safety) + Gate 1(lint) + 单元测试
- **失败处理**：任一 Gate 不通过 → commit 被拒，修复后重试

### Push — Task 完成时

- **定义**：Task 内所有 commit 累积推送到远程分支
- **触发时机**：Critic APPROVE 后，Agent-dev 执行 `git push`
- **颗粒度**：1 Task = 1 次 push
- **Hook**：Lefthook pre-push 自动跑 Gate 2(type) + Gate 4(test-all) + Gate 5(coverage≥80%)
- **红线**：`git push --force` 必须人工确认

### PR — Round 交付入口

- **定义**：Round 收敛后创建，将该 Round 所有 Task 分支合并到集成分支再 PR→main
- **颗粒度**：1 Round = 1 PR
- **触发**：Orchestrator close-round 收敛判定通过后
- **CI**：PR 触发 GitHub Actions 全 7 道门
- **合并条件**：CI 全绿 + Review 通过（分支保护规则）

---

## Review 机制（三层四审）

### ① Critic 单审 — Task 级

| 维度 | 说明 |
|------|------|
| **触发** | Dev 完成 L1 Loop，在对话中 `@critic REQUEST: REVIEW` |
| **范围** | 当前 Task 的 `git diff`（全部 commit 累积差异） |
| **实现** | agent-critic SKILL.md，LLM Agent 独立会话执行 |
| **协议** | Fresh Context — 只看 diff + 契约 + 机器验证结果，不看 Dev 推理过程 |
| **六维检查** | 验收覆盖 / 文件隔离 / 契约一致 / 证据链 / 测试覆盖 / 代码安全 |
| **结论** | APPROVE→完成 / MINOR→修复自动过 / MAJOR→重做+重审 |
| **循环上限** | 同一 Task 最多 3 轮，超限 → Orchestrator 介入 |

### ② Critic 交叉审 — Round 级

| 维度 | 说明 |
|------|------|
| **触发** | Orchestrator close-round Phase 2 |
| **范围** | Round 内全部 Task 的变更文件列表 |
| **检测项** | 同文件冲突 / 契约字段冲突 / 角色越界 |
| **结论** | 有交集/冲突 → MAJOR，退回修复 |

### ③ @Review 全局审 — Round 级

| 维度 | 说明 |
|------|------|
| **触发** | Orchestrator close-round Phase 1 |
| **范围** | Round 全部产出 |
| **深度** | 架构级（全局一致性），不同于 Critic 的代码级 |
| **结论** | PASS/FAIL + 风险报告 |

#### Critic vs @Review 分工

| | agent-critic | @Review |
|------|:---:|:---:|
| 范围 | 单个 Task | Round 全部 Task |
| 深度 | 代码级（diff 逐行） | 架构级（全局一致性） |
| 契约 | 单 Task 与契约一致性 | 跨 Task 契约一致性 |
| 证据链 | 检查四件套格式 | 检查证据链逻辑一致性 |
| 结论 | APPROVE/MINOR/MAJOR | PASS/FAIL + 风险报告 |

### ④ 设计完整性审计 — Round 级

- 逐条对照 `skills/SKILL.md` 每项宣称 → 已实现/未实现
- 逐条对照 `design/BEACON.md` 每项目标 → 已实现/未实现
- 逐条对照 `specs/` 组件清单 → backlog 是否有对应任务
- 产出 `design-completeness.md`

### ⑤ CI AI Review — PR 级（占位符）

- 两层：快速 Sonnet（每个 PR）+ 深度 Opus（pr→main）
- **不阻断合并**
- 当前状态：等待 `claude-code-action` 发布

---

## CI 门禁（7 道确定性门 + 三层触发）

### 七道门

```
Gate 0: 安全红线     safety-check    — Semgrep + Gitleaks
Gate 1: Lint         lint            — shellcheck + shfmt
Gate 2: 类型检查     type-check      — bash -n 语法检查
Gate 3: 契约检查     contract-diff   — 仅 Agent 协作启用
Gate 4: 测试         test            — unit + integration
Gate 5: 覆盖率       coverage        — ≥ 80% (strict: ≥85%)
Gate 6: 构建验证     build           — 打包/安装验证
```

### 三层触发

| 层 | 时机 | 跑什么 | 工具 |
|------|------|------|------|
| **Commit 级** | `git commit` | Gate 0 + 1 + unit test | Lefthook pre-commit |
| **Push 级** | `git push` | Gate 2 + 4(all) + 5(cov) | Lefthook pre-push |
| **PR 级** | PR→main / push→main | 全 7 门 + AI Review | GitHub Actions |

---

## 自动化 vs 人工总览

| 阶段 | 操作 | 自动/人工 |
|------|------|:---:|
| 规划 | 需求拆解 → Task 分配 | 🤖 Orchestrator 自动 |
| 开发 | TDD RED→GREEN→REFACTOR | 🤖 Agent-dev 自动 |
| 开发 | 四段式指令（目标/边界）定义 | 👁️ 人工 |
| 测试 | unit/int/cov 执行 | 🤖 CI 自动 |
| 测试 | `/tdd cover` 补充覆盖 | 👁️ 人工触发 |
| Commit | Agent 提交 + Hook 阻断 | 🤖 自动 |
| Push | Agent 推送 + Hook 阻断 | 🤖 自动 |
| Push | `--force` 强制推送 | 🛑 强制人工 |
| Review | Critic 单审 + 交叉审 | 🤖 Agent 自动 |
| Review | 降级 L3（系统性分歧） | 🛑 强制人工 |
| CI | 7 道门全流程 | 🤖 自动 |
| Merge | PR 合并按钮 | 🤖/👁️ 取决于配置 |
| Merge | 生产发布审批 | 🛑 强制人工 |

---

## 降级处理

| 级别 | 场景 | 动作 |
|:---:|------|------|
| L0 | 单域内自愈 | Dev-Critic 循环修复 |
| L1 | 跨角色契约不一致 | 两方陈述 → 人工裁决 |
| L2 | Review MAJOR 争议 | Review 结论为最终判定 |
| L3 | 系统性分歧 | 暂停相关 Round，强制人工介入 |
| L4 | 全盘阻塞 | 串行化所有任务 |

---

## 对应关系速查

```
Plan    : Round   = 1 : N      一个 Plan 拆成 N 个 Round
Round   : PR      = 1 : 1      一个 Round 收敛后出一个 PR
Round   : Task    = 1 : N      一个 Round 包含 N 个并行 Task
Task    : Push    = 1 : 1      APPROVE 后 push 一次
Task    : Loop    = 1 : 1~3    最多 3 轮 Dev-Critic
Loop    : Commit  = 1 : N      RED/GREEN/REFINE 各自一个 commit
Commit  : CI      = 1 : 3门    pre-commit hook 自动跑
Push    : CI      = 1 : 3门    pre-push hook 自动跑
PR      : CI      = 1 : 7门    GitHub Actions 自动跑
Task    : Review  = 1 : 0~3    每轮 Loop 完 Critic 单审一次
Round   : Review  = 1 : 3      Critic 交叉 + @Review 全局 + 设计完整性
```

---

## 关键设计决策

| # | 决策 | 来源 |
|:--|------|------|
| 1 | PR 颗粒度为 Round 级，非 Task 级。Round 是完整交付单元，拆分破坏原子性 | 2026-06-23 讨论 |
| 2 | TDD 合规由 CI Gate 5（覆盖率门禁）确定性验证，不由 AI 自查自罚 | ADR #24 |
| 3 | AI 生成的测试必须经过人的审查才能进代码库，不做自动补全 | ADR #24 |
| 4 | Critic 使用 Fresh Context 协议：只看 diff + 机器验证，不看 Dev 推理过程 | agent-critic SKILL.md |
| 5 | Dev-Critic 循环上限 3 轮，连续 2 次 MINOR 自动升级 MAJOR | agent-dev SKILL.md |
| 6 | 质量门优先于 Review 判定（机器 > LLM），质量门不通过但 Review APPROVE → 退回 | Orchestrator SKILL.md |
| 7 | PR 内的 Round 可标注 `merge_mode: independent` 允许拆分 PR（耦合度 0 时） | Round 拆分例外 |

---

## 引用文件

- `skills/agent-orchestrator/SKILL.md` — Round 管理、收敛判定、降级处理
- `skills/agent-dev/SKILL.md` — L1 Loop、四段式指令、Critic 交互
- `skills/agent-critic/SKILL.md` — Fresh Context 协议、六维审查
- `skills/tdd/SKILL.md` — TDD 三步循环、Strict 模式
- `skills/worktree/SKILL.md` — 多分支并行开发
- `scripts/ci/ci-local.sh` — 本地 CI 7 道门编排
- `lefthook.yml` — pre-commit / pre-push Hook 配置
- `design/BEACON.md` — 42 条 ADR 设计决策
- `design/ROUND-AUTOMATION.md` — Round 自动化执行方案（v2 规划）
