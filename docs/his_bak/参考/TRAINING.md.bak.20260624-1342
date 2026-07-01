# project-engineering-init 培训材料

> v2.0.0 | 2026-06-21

---

## 前言：这套工具解决什么问题

AI 编码进入生产，四个核心问题：

| 问题 | 现象 | 解决方式 |
|------|------|---------|
| **质量不可控** | AI 写的代码有时对有时错 | TDD 纪律（prompt）+ CI 7 道门 |
| **协作混乱** | 多人+AI 并行，代码互相覆盖 | Architect 角色 + Worktree 隔离 + 契约文件 |
| **迭代退化** | AI 越改越差，不知道什么时候停 | 停滞检测（3 次失败→停）+ 硬上限 |
| **安全盲区** | 硬编码密钥、SQL 注入 | Lefthook gitleaks + CI semgrep |

---

## 第一板块：/init 工程化 — 5 分钟搭建项目骨架

### 解决的问题

"每次开新项目都要手动创建目录、配置测试框架、写 CI、配 Hook。"

### 使用方式

```bash
cd my-project
/init 工程化
# → 选择项目类型（A-H）→ 确认 → 完成
```

### 一次交互，全部生成

```
请选择项目类型:

  A. Application/Service — REST API、前端、后端、全栈
  B. Library/SDK — 可发布的库/包
  C. CLI Tool — 命令行工具
  D. Skill — Claude Code Skill
  E. Hook — Claude Code Hook
  F. MCP Server — MCP 服务端
  G. Spec/Doc — 规范文档仓库
  H. Monorepo — 多子项目仓库
```

确认后一键生成：

```
my-project/
├── src/                   业务代码
├── tests/
│   ├── unit/              单元测试（镜像 src/）
│   ├── integration/       集成测试
│   └── __support__/       测试基础设施
├── docs/                  项目文档
├── design/contracts/      契约文件
├── _scratch/              临时产物（gitignore）
├── .claude/               Claude Code 配置
│   └── agents/            三角色 prompt（Spec/Doc 类型不生成）
├── package.json           统一命令入口
├── lefthook.yml           本地门禁（已激活）
├── justfile               命令别名
├── .github/workflows/
│   └── ci.yml             7 道门 CI
├── .gitignore
└── CLAUDE.md              项目信息 + AI 引导
```

### 存量项目：只增不改

```
检测到存量项目:
  已有: src/、package.json
  缺失: tests/、docs/、design/、lefthook.yml、.claude/
  冲突: 无
  → 只创建缺失内容，不修改已有文件
```

### 三个子命令

| 命令 | 用途 | 示例 |
|------|------|------|
| `/project:ci` | 切换 CI 平台 | GitLab CI |
| `/project:lint` | 配置 Lint | Biome 替代 ESLint |
| `/project:test` | 配置测试框架 | Vitest 替代 Jest |

---

## 启动开发：五种模式

Architect 为统一入口，按输入形态分流：

```
输入      审视方式                           执行        审查

一句话 →  Architect 审视 → 切 Developer → TDD    →   Critic（必须）
Design →  Architect 深度审视 → 切 Developer → TDD    →   Critic（必须）
Plan   →  Architect 确认可测试性 → 切 Developer → TDD    →   Critic（必须）
需求   →  /dev-loop（Architect→Dev→Critic 全自动）      ✓
Plan   →  /atdo --tdd（Phase 序列自动化）              ✓
```

### 模式 1：自然语言一句话

```bash
cd my-project
claude "给登录页加邮箱验证，输错 3 次锁定 15 分钟"
```

Agent 读 CLAUDE.md → 加载 Architect 角色 → 审视可测试性 → 追问澄清 → 切 Developer TDD → 完成。

Architect 是统一入口，简单需求在入口处审视后直接分流到 Developer，不需要单独启动 Architect 流程。

**适用**：bug fix、单功能、探索性开发。**零配置，三重纪律**（审视 + TDD + Critic）。

### 模式 2：Design 文档驱动

```bash
claude "读 design/specs/user-auth.md，按其中验收标准逐条实现"
```

人先写了完整设计文档。Architect 深度审视结构完整性（缺口、矛盾、边界条件），审视通过后切 Developer TDD。Architect 是统一入口，不再需要 Developer 拒绝后手动调 Architect。

**流转**：设计文档 → Architect 深度审视 → Developer TDD → Critic

**适用**：人想清楚了"要什么"，但不想拆 task。

**与 /atdo 的关键差异**：Design 文档是非结构化的，Agent 自己从文档提取可执行项——atdo 做不到这一点，atdo 的 plan 必须提前结构化为 phase/task。

### 模式 3：Architect 分析 → Plan → 执行

```
/architect 分析用户认证模块需求
  → Architect 审视完整性 + 判断是否并行 + 产出 design/auth-PLAN.md
  ↓
claude "按 design/auth-PLAN.md 实现"
  → Developer 按 plan 执行
```

Architect 在分析阶段判断是否需要多 Agent 并行（≥2 独立模块 + 无共享文件 + >30min），并把并行策略写入 plan 文档。

**适用**：复杂架构决策，需要先讨论再动手。**比 /atdo 更具探索性**：plan 是讨论的产物，不是人预先写好的。

**与 /atdo 的关键差异**：Plan Mode 产出的 plan 是自由格式，捕捉了讨论中的决策上下文。atdo 需要严格的 `### P?-N` 格式。

### /dev-loop：三角色链式编排

```bash
/dev-loop 实现用户登录功能
```

流程：Architect 规划 → [确认] → Developer TDD → Critic 审查 → 退出。

**退出标准**：

| # | 条件 | 动作 |
|---|------|------|
| 1 | Critic APPROVE + 测试全绿 | 原始需求已满足，结束 |
| 2 | Critic 仅 P2 | P2 不阻断，结束 |
| 3 | Developer 3 种方法仍失败 | 停，解释根因 |
| 4 | Critic MAJOR ≥ 3 次 | 停，升级给人 |
| 5 | 用户 `a` | 手动中止 |
| 6 | 需求无法澄清 | 停，列出需澄清的点 |

**适用**：跨模块需求、需要独立规划+审查的功能开发。

### /atdo .plan --tdd：多阶段批量自动化

```
/atdo REPAIR-PLAN.md --tdd
  → Phase 1: RED→GREEN→commit
  → Phase 2: RED→GREEN→commit
  → ...
  → Final gate: 全量测试 + lint → push
```

**适用**：审计修复、多阶段重构、批量改造。人的思考前置到写 plan 阶段，执行阶段全自动。

### 五种模式对照

| | 模式 1 一句话 | 模式 2 Design | 模式 3 /architect | /dev-loop | /atdo --tdd |
|------|:---:|:---:|:---:|:---:|:---:|
| 输入 | 一句话 | 设计文档 | /architect 讨论 | 需求描述 | 结构化 plan |
| 谁拆任务 | Architect | Architect | Architect | Architect | 人预先拆 |
| 设计审视 | Developer 自查 | Architect → Developer | Architect → Developer | Architect + Developer | 无 |
| 多 Agent | 不触发 | Architect 判断 | Architect 判断 | Architect 判断 | 不触发 |
| 探索性 | 中 | 高 | 最高 | 中 | 低 |
| 自动化 | 中 | 中 | 中 | 高 | 最高 |
| 审查 | **必须**（Dev 请求） | **必须**（Dev 请求） | **必须**（Dev 请求） | Critic | Phase gate |
| 退出判定 | Agent 自主 | Agent 自主 | Agent 自主 | 6 条标准 | Phase gate |
| 适用 | 简单需求 | 已有设计文档 | 架构决策 | 跨模块功能 | 批量修复 |

**设计审视**：不同输入触发不同审视方式：

| 输入 | 审视方式 |
|------|---------|
| 一句话需求 | Architect 审视可测试性+边界，追问澄清后切 Developer TDD |
| Design 文档 | Architect 深度审视结构（缺口/矛盾/边界）→ 切 Developer TDD |
| Plan Mode 产出 | Architect 确认可测试性后切 Developer TDD |

**Architect 是统一入口**：Architect 审视所有输入的结构完整性（缺什么、矛盾在哪）并进行模式分流。Developer 执行 TDD 实现（能测吗、边界够清晰吗）。

### 核心原则

**plan 在 Agent 内部，不在外部。** 人给的是"要做什么"（需求或 spec），Agent 自己决定"怎么一步步做"。不需要人写 task 清单、不需要 plan_output.json、不需要 Round 编排。

### Agent 的行为契约

```
while 还有事做:
  做一件事 → 验证（lint + type-check + test）
  if 验证失败: 修复（最多 3 次）
  if 验证通过: 继续下一件
  if 发现新工作: 自己加到列表
  if 全部完成 + CI 绿 + Critic APPROVE: 结束
  if 卡住修不好: 停下来问人
```

### 什么需要，什么不需要

| 需要 | 不需要 |
|------|--------|
| CLAUDE.md（项目上下文） | task 清单 |
| `prompts/`（Agent 人格纪律） | plan_output.json |
| `lefthook.yml`（硬约束） | Round 编排 |
| CI（最终防线） | goal.yaml |
| 需求/spec 文档（做什么） | 外部检查器 |

---

## 开发循环：从短到长

五种模式映射到三个层级的开发循环：

### 短循环：模式 1/2/3（单人 + Design/Plan 驱动）

```
改代码前先写测试 → npm test（RED）→ 改代码 → npm test（GREEN）
→ 重构 → git commit → git push
                ↑           ↑
           Lefthook      CI 7 道门
         lint+test-unit   自动跑
```

Lefthook 和 CI 是自动挡。模式 2/3 的区别在于 Agent 的输入源（Design 文档 / Plan Mode 讨论），循环节奏相同。

### 中循环：/dev-loop（三角色链式协作）

```
Architect 规划 → [确认] → Developer TDD 实现 → Critic 审查 → 结果
                                          ↑                    │
                                          └── MAJOR ≤ 3 次 ────┘
```

退出标准：APPROVE（结束）/ 3 次 MAJOR（升级）/ 3 次失败（停止）/ 用户中止。

### 长循环：/atdo --tdd（批量自动化）

```
/atdo REPAIR-PLAN.md --tdd
  → Phase 1: RED→GREEN→commit
  → Phase 2: RED→GREEN→commit
  → Final gate: 全量测试 + lint → push
```

### 三层对照

| | 短循环 | 中循环 | 长循环 |
|------|:---:|:---:|:---:|
| 对应模式 | 模式 1/2/3 | /dev-loop | /atdo --tdd |
| 启动 | 自然对话 | `/dev-loop` | `/atdo .plan --tdd` |
| 角色 | Developer | Architect+Developer+Critic | atdo executor |
| 退出 | Agent 自主 | 6 条退出标准 | Phase gate |
| 周期 | 分钟 | 小时 | 小时～天 |

---

## 第二板块：TDD 编码纪律 — Agent 不乱写代码

### 解决的问题

"AI 经常跳过测试直接写实现，或者测试和代码一起输出。"

### 如何生效

Agent 启动时读取 `prompts/developer.md`，自动遵循 TDD 三步循环。

### RED → GREEN → REFACTOR

```
RED:       写测试 → 运行确认 FAIL（不红=测试写错）
GREEN:     最小实现 → 运行确认 PASS（不做推测功能）
REFACTOR:  改结构不改行为 → 测试保持绿
```

### 合规保障：不靠自查，靠 CI

```
Agent prompt（软约束）: "先写测试，确认失败"
  → Lefthook（硬约束）: commit 前 lint + test
    → CI Gate 5（最终防线）: 覆盖率 < 80% → 🛑 阻断合并
```

### 测试覆盖要求

- CI 覆盖率门禁：全局 ≥80%
- 测试镜像源码结构：`tests/unit/` 对应 `src/`
- 测试不在 `src/` 下

### 何时启动 Critic 审查

Critic 审查是所有模式的必需要求。Developer 完成实现后必须主动请求。

| 场景 | 要求 |
|------|:--:|
| 任何需求的实现 | **必须** — 未审查不视为交付完成 |

Critic 以独立 Agent 启动，**只看 git diff + 验收标准 + CI 结果 + 契约文件**。
不看 Developer 的对话历史和推理过程（Fresh Context）——这确保审查不受 Developer 的假设和判断影响，是真正的独立挑刺。

---

## 第三板块：本地门禁 — 提交前自动检查

### 解决的问题

"经常 `git commit --no-verify` 跳过检查，忘了跑测试就提交。"

### Lefthook 自动拦截

```yaml
pre-commit（并行，<30 秒）:
  lint:       npm run lint
  test-unit:  npm run test:unit

pre-push（<2 分钟）:
  type-check:  npm run type-check
  test:        npm test
  coverage:    npm run test:cov
```

Agent 跑的检查和 Lefthook 跑的检查是**同一套命令**。Agent 绿了，Lefthook 就绿。

---

## 第四板块：CI 云端门禁 — 合并前最后防线

### 解决的问题

"PR 合并没有硬性检查，不达标的代码进了主干。"

### 7 道门流水线

```
Gate 0: semgrep ci          安全红线 🛑
Gate 1: lint                代码规范 🤖
Gate 2: type-check          类型检查 🤖
Gate 3: contract-diff       契约一致性 🤖
Gate 4: test                全量测试 🤖
Gate 5: coverage ≥80%       覆盖率 🛑
Gate 6: build               构建验证 🤖
```

Gate 0-4 和 Gate 6 由确定性工具自动判定，不消耗 LLM Token。

### 防御纵深

```
Agent prompt（软约束）
  → Lefthook（硬约束，本地）
    → CI 7 道门（最终防线，云端，不可绕过）
```

---

## 第五板块：多 Agent 并行 — 不乱踩

### 解决的问题

"前端改了个字段名，后端不知道，API 炸了。"

### 三角色分工

| 角色 | 职责 | 何时启动 |
|------|------|---------|
| Developer | TDD 开发，写代码 | 始终 |
| Critic | 只读审查，找 bug | Developer 完成后 |
| Architect | 需求分析，多 Agent 协调 | 任务涉及多模块时 |

### 何时派生并行 Agent

Architect 判断：任务涉及 ≥2 个独立模块 + 无共享文件 + 工作量 >30 分钟 → 派生并行。

否则自己直接开发。

### 并行流程

```
Architect 分析需求
  → 创建契约文件 design/contracts/{module}-api.yaml
  → 派生 Developer-Agent（FE，worktree 隔离）
  → 派生 Developer-Agent（BE，worktree 隔离）
  → 两者并行开发，按契约实现
  → 完成后 Architect 收集结果 → 集成测试 → 验证契约一致性
  → 发现问题 → 派生 Critic 审查 → 修复 → 重验
  → 全部通过 → 完成
```

---

## 第六板块：安全红线 — 低级安全问题不过夜

### 解决的问题

"AI 写的代码里硬编码了 API Key，SQL 查询用了字符串拼接。"

### 6 条红线

| 红线 | 检测 |
|------|------|
| R1: 密钥不进代码 | gitleaks |
| R2: SQL 拼接 | semgrep |
| R3: XSS（innerHTML） | semgrep |
| R4: 命令注入（exec 拼接） | semgrep |
| R5: 路径穿越 | semgrep |
| R6: 硬编码凭据 | gitleaks |

### 双重拦截

- **Lefthook pre-commit**：本地提交前扫描（本地即可拦截）
- **CI Gate 0**：云端最终防线（不可绕过）

---

## 三类项目使用示例

### 简单项目：单人 CLI 小工具

```
/init 工程化 → 选 CLI Tool → 生成骨架
开发功能 → TDD RED→GREEN→REFACTOR
git commit → Lefthook 自动检查
git push → CI 自动检查 → 通过 → 发布
```

使用功能：/init、TDD 纪律、Lefthook、CI。

不使用：多 Agent 并行（一个人不需要）。

### 中等项目：前后端分离

```
/init 工程化 → 选 Application/Service
Architect 分析需求 → 判定前后端可并行
  → 派生 FE Agent（worktree=feat-login-fe）
  → 派生 BE Agent（worktree=feat-login-be）
  → 创建契约 design/contracts/auth-api.yaml
  → 两者并行 TDD + CI
  → Architect 收集 → 集成测试 → 完成
```

使用功能：全部。

### 复杂项目：多模块平台 + 多 Agent

```
/init 工程化 → 选 Monorepo
  → packages/core/（Python 引擎）
  → packages/dashboard/（React 前端）
  → packages/cli/（CLI 工具）

Architect 分析 → 3 个 Agent 并行
  Core Agent: TDD + pytest + ruff
  Dashboard Agent: TDD + Jest + ESLint
  CLI Agent: TDD + Jest + ESLint
  → 各自完成 → Critic 审查 → 集成验证 → 交付
```

使用功能：全部。
