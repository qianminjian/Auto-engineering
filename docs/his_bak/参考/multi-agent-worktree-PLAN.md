# 多 Agent 并行方案设计

> 2026-06-21 | 调研 → 讨论 → 结论

---

## 一、问题起点

### 原始需求

BEACON.md 遗留问题：

> 多 Agent worktree 并行专题 — Agent 并行写入冲突、文件写入锁机制、
> Agent 输出目录隔离（_scratch/<agent-id>/）、coverage 临时目录冲突。

### 初始假设

"多 Agent 并行开发需要 worktree 做文件系统隔离，防止互相覆盖。"

### 初始假设中的混淆

事后复盘发现，初始假设把两个不同的问题混在了一起：

| 问题 | 属于谁 | 场景 |
|------|--------|------|
| "我在 feature 分支，线上出了 bug，要切到 main 修" | **人**的分支管理 | 跨分支、多目标 |
| "这个需求太大，拆成几个模块让 subagent 分别做" | **Loop**的任务分解 | 单分支内、同一目标 |

两者都需要"隔离"，但隔离的是不同的东西：人需要的是**分支隔离**（不同目标之间不要互相污染），Loop 需要的是**文件集隔离**（同一目标的不同模块不要互相覆盖）。Worktree 解决的是前者，文件集预检解决的是后者。初始假设把 Loop 的问题当成了人的问题来解。

---

## 二、调研过程

### 2.1 业界调研

并行调研三个方向：

**Claude Code Agent SDK（context7 + WebSearch）**

| 发现 | 影响 |
|------|------|
| `isolation: "worktree"` 创建独立 git worktree，位于 `.claude/worktrees/<name>/` | 文件系统隔离可用 |
| worktree 始终从 **origin/main** 分支，不是当前 HEAD | 如果用户在 feature 分支上工作，Agent 从 main 开始，看不到已有改动 |
| Claude Code **不做自动合并**——Agent 返回后 worktree 分支留在原地 | 合并需要人工处理 |
| 无 `--worktree-base` 参数（GitHub Issue #23622，未实现） | 无法指定基准分支 |
| Subagent 通过 task result 返回，不是通过 git merge | 依赖 Claude Code 内部通信，不由我们控制 |

**Git Worktree 底层机制（WebSearch + git 社区文档）**

| 发现 | 影响 |
|------|------|
| 每个 worktree 有独立分支 + 独立工作目录 + 独立暂存区 | 编辑层面隔离完整 |
| 两个 worktree 改同一文件完全允许，git 不阻止 | 隔离不防止语义冲突 |
| 合并时同一文件有冲突 → git 标记冲突，需要人工解决 | 冲突推迟到合并阶段，未消除 |
| **所有 worktree 共享同一个 `.git/` 对象数据库** | 关键发现 |
| `git commit` + `git commit`（同时）可能**静默损坏 `.git/objects/`** | 并发写入不安全 |
| `git gc` + 任何写操作（同时）可能删除正在写入的对象 | 自动 gc 特别危险 |
| git 的 `.lock` 文件只保护 ref 级别，不保护对象数据库 | git 社区公认限制 |

**多 Agent 协调模式（WebSearch + 社区经验）**

| 发现 | 影响 |
|------|------|
| 业界最简有效方案：空间隔离（让 Agent 文件集不重叠） | 预防优于修复 |
| 文件级租约（agentlocks）需要额外工具 | 增加依赖 |
| 结构化合并（tree-sitter merge）仅 10+ Agent 规模需要 | 过度设计 |
| 2-3 Agent 场景：契约 + 不重叠文件集就够了 | 对齐本项目规模 |

### 2.2 关键决策链

调研中每一步都在收窄选择空间：

```
起点: "多 Agent 并行 → 需要 worktree 隔离"
  ↓
发现 1: Claude Code worktree 始终从 origin/main 分支
  → 如果当前在 feature 分支，Agent 基于错误的起点工作
  → 要么在接受限制前先合并到 main，要么绕过 Claude Code 手动 git worktree
  ↓
发现 2: Claude Code 不做自动合并
  → Agent 返回后，分支留在那等人合并
  → 每次派生都产生新的合并负担
  ↓
发现 3: 多个 worktree 同时 git commit 可能损坏 .git
  → 并发安全性需要额外机制保障
  → 要么串行化 git 操作，要么接受静默损坏风险
  ↓
问自己: worktree 到底解决了什么问题？
  → 防止 Agent A 和 Agent B 互相覆盖对方的文件修改
  → 这个问题有更简单的解法吗？
  ↓
答案: 如果 Architect 在派发前保证文件集无交集，就不存在"互相覆盖"的问题。
      文件集预检 = 最强的隔离。Worktree = 给不需要隔离的场景加了隔离成本。
```

---

## 三、分析

### 3.1 Worktree 的成本-收益分析

**Worktree 解决的问题（收益）**：
- 多个 Agent 同时编辑同一工作目录时，中间的半成品文件互相可见 → 可能被误读或覆盖

**Worktree 引入的问题（成本）**：
- 基准分支限制（origin/main）→ Agent 可能基于错误的代码起点
- 无自动合并 → 每次派生产生人工合并负担
- 并发 git 写入风险 → 需要额外安全机制
- 合并冲突 → 把冲突从"编辑时暴露"推迟到"合并时爆发"，未消除
- `.worktreeinclude` 配置 → 需要额外模板文件
- Worktree 清理失败 → 磁盘残留
- 子 Agent 依赖安装（每个 worktree 独立 `npm install`）→ 时间成本

**关键洞察**：Worktree 解决的是"同一个文件被两个 Agent 改"的问题。但如果 Architect 在派发前保证了文件集无交集，这个问题根本不会出现。Worktree 就成了**为一类已经被消除的风险而支付的保险成本**。

### 3.2 文件集预检 vs Worktree 隔离

| 维度 | 文件集预检 | Worktree 隔离 |
|------|----------|-------------|
| 机制 | Architect 规划时检查 | 创建独立文件系统副本 |
| 时间复杂度 | O(1) 检查 | O(n) 依赖文件复制 |
| 合并不一致风险 | 无（各自改独立文件） | 有（同一文件两边都改了） |
| 并发 git 风险 | 无（串行执行） | 有（多个 worktree 并行 git 操作） |
| 引入新机制 | 0 | `.worktreeinclude`、合并流程、清理策略 |
| 失败模式 | Architect 判断错误（人工纠正） | git 损坏（工具修复）、合并冲突（人工解决） |

### 3.3 "并行"的重新定义

两种意义上的"并行"：

| | 运行时并行 | 规划层并行 |
|------|----------|----------|
| 含义 | 多个 Agent 同时执行 | 工作分解为可独立验证的包 |
| 用户感知 | 更快（如果 Agent 无依赖） | plan 更清晰、每个包自包含 |
| 需要 worktree？ | 是 | 否 |
| 需要文件集预检？ | 是 | 是 |

**决策**：本项目追求规划层并行，不追求运行时并行。理由：
- 规划层并行已经带来了全部的设计收益（清晰的模块边界、可独立验证、可分工）
- 运行时并行带来的速度收益在本项目规模（2-3 Agent）下有限
- 运行时并行的成本（worktree、合并、并发安全）远超收益

### 3.4 两层模型：人的分支管理 vs Loop 的任务分解

在分析 worktree 的适用场景时，发现需要区分两个层面：

```
Layer 1: 人的分支管理（worktree 生效）
────────────────────────────────────
场景:
  "修一下 main 上的 bug"              → 当前在 feature 分支，需要 hotfix
  "这个先放一下，先做…"                → 当前分支有未完成工作，不想 stash
  "对比一下 {branch} 的代码"           → 跨分支查看
  "同时开发 v1 和 v2"                 → 多版本并行维护
  "review 一下 PR #42"               → 切到 PR 分支

工具: claude --worktree hotfix
      git worktree add -b review-pr42 origin/pr/42
      git merge / git worktree remove

Loop 视角: 我只是在某个目录下的某个会话上运行，不知道也不关心外面是不是 worktree
```

```
Layer 2: Loop 内部的 Agent 协作（worktree 不生效）
────────────────────────────────────
场景:
  "这个需求太大，前端和后端可以分开做"   → 同一分支内、同一目标下的任务分解
  Architect 拆分 plan → 子任务 A / 子任务 B

工具: 文件集预检 + 规划层并行 + 串行执行

Loop 视角: 我在一个会话里串行推进子任务，文件不重叠就不冲突
```

**这个区分解释了之前分析中的根本混淆**：我们把 Layer 2 的问题（Loop 内部的任务分解）当成了 Layer 1 的问题（人的分支管理）来解决。Architect 派发 subagent 时，所有 subagent 都在**同一个分支的同一个目标**下工作——它们之间需要的是文件集协调，不是分支隔离。分支隔离是**人**在不同目标之间切换时用的。

**各自的责任边界**：

| | 人（Layer 1） | Loop / Architect（Layer 2） |
|------|------|------|
| 管什么 | 多分支、多版本、跨分支操作 | 单分支内的任务分解与执行 |
| 工具 | `claude --worktree`、`git worktree add/remove`、`git merge` | 文件集预检、plan + 子任务、串行推进 |
| 看到 worktree 吗 | 是，主动创建和管理 | 否，只看到当前目录和当前分支 |
| 决定什么 | 什么时候切分支、什么时候合并、什么时候销毁 | 什么时候拆分、拆成几个子任务、什么时候串行 |

**Loop 不需要知道 worktree 的存在。** 对 Loop 来说，它永远运行在"某个目录的某个 git 仓库"里，做的是单分支内的开发工作。人是否在旁边开了另一个 worktree 做 hotfix，Loop 完全不用关心——那是另一个 Claude Code 会话的事。

### 3.5 两层模型的实践意义

**恢复 `.worktreeinclude` 到模板中**。

之前取消了 `.worktreeinclude.tmpl`，理由是"Layer 2 不启用 worktree"。现在纠正：`.worktreeinclude` 是**给 Layer 1（人）用的**。当人执行 `claude --worktree hotfix` 时，Claude Code 会自动把 `.worktreeinclude` 中列出的文件（如 `.env`）复制到新 worktree 目录。这是 Claude Code 原生能力，模板应该预置，让人在分支管理中开箱即用。

**不在 Architect prompt 中提及 worktree**。

Architect 是 Layer 2 的入口。对它来说，工作目录就是一个普通的 git 仓库，不需要知道是否嵌套在 worktree 中。文件集预检逻辑与 worktree 无关，增加 worktree 概念只会引入噪音。

---

## 四、结论

### 最终方案

```
Architect 分析需求/Design/Plan
    │
    ├─ 文件集可无交集拆分？
    │   ├─ YES → 产出 plan + 拆分子任务（每个子任务独立文件范围 + 独立验收标准）
    │   │         执行：串行推进子任务（每个子任务内走 Developer → Critic）
    │   │         串行原因：共享 git 对象库不支持并发写入；文件不重叠时串行无冲突
    │   │
    │   └─ NO  → 产出 plan → 单人 Developer → Critic（标准串行开发）
    │
    └─ 整体完成后 → Critic 跨模块审查
```

### 不启用 Worktree

不是"暂时不启用"，而是**判定不需要**。理由三重：

1. **文件集预检已消除 worktree 要解决的问题**。如果两个 Agent 改的文件无交集，在同一工作目录下串行执行也不会互相干扰。worktree 的文件系统隔离是多余的。

2. **Worktree 引入了比它解决的问题更多的复杂性**。基准分支限制、手动合并、并发 git 风险、清理策略——每一个都是新增的失败点。

3. **与自动化第一性原理冲突**。本项目的核心原则是"Agent 自己决定怎么做，自己知道做没做完"。Worktree 的合并流程需要人工介入——违反了这个原则。

### 唯一需要保留的

Agent 输出目录隔离（`_scratch/<agent-id>/`）。即使串行执行，临时产物仍需要按 Agent 分目录，便于定位问题来源。这是纯目录约定，零机制成本。

### 契约确认机制：两绿才通过

**问题**：Architect 能在架构层面定义接口规范，但它对 FE/BE 各自的实现约束理解有限——它定义的 API 字段可能前端无法渲染、后端无法产出。如果等各 Agent 实现完到集成测试时才发现契约问题，返工成本是双方都要改。

**方案**：将契约确认作为每个 Agent 执行的第一步。双方均确认后，方可进入实现。

```
Agent A (FE) 启动                     Agent B (BE) 启动
    │                                      │
Step 0: 读契约                            Step 0: 读契约
    │                                      │
逐条确认：                                逐条确认：
  - 我能渲染这个 response 字段吗？          - 我能产出这个 response 字段吗？
  - 我需要的 request 字段都定义了吗？       - 我需要的 request 字段都定义了吗？
  - 错误码覆盖我的边界场景了吗？           - 我能返回这个错误码吗？
  - 类型与我使用的组件/库兼容吗？          - 类型与我使用的 ORM/中间件兼容吗？
    │                                      │
输出 CONFIRM / BLOCK（含具体理由）         输出 CONFIRM / BLOCK（含具体理由）

               双方结果合并:
            ┌──────────────────────┐
            │ A ✓ + B ✓            │ → 双方并行推进实现（自动）
            │ A ✗ + B ✓            │ → 升级给人（A 的理由 + 契约原文）
            │ A ✓ + B ✗            │ → 升级给人（B 的理由 + 契约原文）
            │ A ✗ + B ✗            │ → 升级给人（双方理由 + 契约原文）
            └──────────────────────┘
```

**人收到升级时看到的信息**：哪个 Agent 反对 + 具体理由（哪个字段/错误码不可行、为什么）+ Architect 的原始契约和设计理由。人不需要从头理解需求，只需要在已知分歧点上做决策——是改契约（A 对 B 也改）还是驳回（B 必须支持）。

**设计理由**：

1. **确认者即实现者，信息对称**。Agent A 知道自己要用的组件库、状态管理、路由结构——它能判断"这个 response 字段我渲染得了吗"，这是通用 Critic 做不到的。

2. **两绿才通过 = 死锁预防**。任何一方没确认，双方都不动。避免了"一方确认后先跑了、另一方发现契约有坑、已跑的要返工"。

3. **事前拦截，修复成本最低**。人在动手之前就收到分歧，改一行契约文件。vs 事后发现（两个 Agent 都要改 + 重跑集成测试）。

4. **不增加独立 Phase**。契约确认融入 Agent 启动（Step 0），不是 plan 中的一个额外阶段。不需要编排层面的改动。

5. **与现有 plan 确认流程融合**。如果两个 Agent 都对契约无异议，自动推进。如果人对契约有疑虑（看到契约后觉得不对），在确认 plan 时自然提出来——不增加人的额外负担。

### Coverage 目录冲突分析

**问题来源**：BEACON.md 原始遗留问题中的"coverage 临时目录冲突"——在 worktree 并行假设下提出。

**在当前串行执行设计下，不会出现 OS 级文件冲突**（两个进程同时写同一文件），但存在**逻辑冲突**：

Jest `--coverage` 每次运行在 `coverage/` 下写入大量文件：

```
coverage/
├── clover.xml
├── coverage-final.json
├── lcov.info
├── lcov-report/
│   ├── index.html
│   ├── src/auth/login.ts.html
│   ├── src/payment/checkout.ts.html
│   └── ...（每个源文件一个 html）
```

Agent B 的 `npm run test:cov` **全量重写**整个 `coverage/` 目录，Agent A 的 coverage 文件全部被覆盖。

**这不是数据丢失**：Agent B 跑全量测试（含 Agent A 的测试），最终 coverage 报告包含双方覆盖率。数据层面没问题。

**但存在四个设计问题**：

| 问题 | 详情 |
|------|------|
| Agent 报告不可追溯 | 无法回答"Agent A 负责的模块覆盖率是多少"，只能看到合并全量数字 |
| 覆盖率回退不可定位 | Agent B 引入未测试代码路径拉低整体覆盖率，无法定位是哪个 Agent 的提交 |
| CI Gate 5 盲区 | CI 全量覆盖率 >80%，但 Agent A 的模块可能只有 40% 被 Agent B 全量测试顺带覆盖，不是 A 自己的测试 |
| `coverage/` 不在 `.gitignore` | 模板只排除 `_scratch/`，`coverage/` 可能被误提交 |

**解决**：

- Agent 运行时指定隔离输出：`jest --coverage --coverageDirectory=_scratch/<agent-id>/coverage`
- 模板 `.gitignore.tmpl` 增加 `coverage/` 排除（当前缺失）
- CI 全量测试不指定 `--coverageDirectory`，使用默认路径
- 各 Agent 独立 report 保留在 `_scratch/` 下，CI 全量报告为最终权威数据

---

## 五、方案演进记录

| 阶段 | 方案 | 触发 |
|------|------|------|
| BEACON.md 遗留问题 | Worktree + 文件锁 + 输出隔离 + coverage 隔离 | 初始需求 |
| 第一版方案 | Worktree 隔离 + 文件集预检 + 5 项改动 | 调研业界实践 |
| 第二版方案 | 统一 Architect 入口 + plan + 派发表 | 讨论模式合并 |
| 第三版方案 | 文件集预检 + 串行执行 + 规划层并行，不启用 worktree | 分析 worktree 成本-收益 |
| 第四版方案 | 两层模型：Layer 1（人）worktree 分支管理 + Layer 2（Loop）文件集预检 + 串行执行 | 区分人的分支管理和 Loop 的任务分解 |
| **最终方案** | **两层模型 + 契约确认机制 + coverage 隔离（`_scratch/<agent-id>/coverage/`）** | 契约作为共享依赖的前置确认 + 串行执行下 coverage 全量重写问题 |

---

## 六、具体改动

P0 改动（核心）：

| 文件 | 改动 | 目的 |
|------|------|------|
| `prompts/architect.md` | 增加文件集拆分判断 + 契约确认机制：识别跨模块接口依赖时，要求各 Agent 启动时先确认契约可实现性，双方确认后才可进入实现。不提及 worktree。 | Layer 2 统一入口 + 契约 Gate |
| `docs/multi-agent-guide.md` | 重写：两层模型、方案演进、文件集预检、规划层并行 vs 运行时并行、worktree 的真正适用场景（人用 `claude --worktree`） | 用户可见文档 |

P1 改动（配套）：

| 文件 | 改动 | 目的 |
|------|------|------|
| `templates/app-service/.worktreeinclude.tmpl` | 新增模板文件（`.env.example` `.env` `.gitignore`） | 人用——`claude --worktree` 时自动复制配置到新 worktree |
| `templates/app-service/.gitignore.tmpl` | 增加 `coverage/` 排除（当前缺失） | 防止构建产物误提交 |
| `templates/app-service/STRUCTURE.md` | `_scratch/<agent-id>/coverage/` + `_scratch/<agent-id>/test-output/` 子目录约定 | Layer 2 临时产物隔离 + 各 Agent 独立 coverage 报告 |
| `templates/app-service/package.json.tmpl` | 增加 `test:cov:agent` 脚本（`jest --coverage --coverageDirectory=_scratch/<agent-id>/coverage`） | Agent 独立覆盖率输出 |

无需额外改动：

| 项 | 理由 |
|------|------|
| `prompts/critic.md` | 已有 P1 契约不一致检查，单次 Critic 审查已覆盖 |
| Architect prompt 提及 worktree | Layer 2 不需要知道 worktree 概念，增加只会引入噪音 |

---

## 七、未讨论问题与建议方案

> 2026-06-21 全面复盘，11 项未讨论问题。每项含业界实践 + 建议方案。

### A. 执行机制（4 项）

#### 7. Agent 派发机制

**业界实践**：标准四段式 prompt 模板（角色 + 上下文 + 目标 + 约束 + 输出格式）。Subagent 启动时 Fresh Context，父 Agent 对话历史不继承。共识——"文件即协议"：chat transcript 不是协调层，文件系统产物（diff、测试结果、覆盖率报告）才是。

**建议**：复用 `prompts/developer.md`，不创建新 prompt 文件或 subagent_type。Architect 在 dispatch prompt 中追加本次任务范围。

```
Agent({
  subagent_type: "general-purpose",
  name: "feat-auth-fe",
  prompt: "
[角色]: 软件开发者。按 developer.md 纪律执行 TDD 实现。
[目标]: 实现前端登录页面。验收标准：plan §3.1-3.3。
[文件范围]: 只修改 src/pages/auth/ tests/unit/auth/
[禁止修改]: src/api/ src/types/ design/contracts/
[契约]: 读 design/contracts/auth-api.yaml，按契约实现。
[输出]: 改动文件列表 + 测试结果(PASS/FAIL) + 覆盖率数字
"
})
```

Agent 返回后，Architect 验证：① `git diff --name-only` 文件列表 vs 白名单；② 测试是否全绿。

#### 8. 串行执行顺序

**业界实践**：静态边（固定 pipeline）、条件路由（supervisor 动态决策）、DAG 任务声明（每 task 声明依赖）、延迟节点（等上游完成）。已知工作流用静态边最简单。

**建议**：Architect 在拆分时检查子任务间依赖。派发表增加 `依赖` 列：

```
| Agent | 依赖 | 文件范围 |
|-------|------|---------|
| feat-auth-be | 无 | src/api/auth/ |
| feat-auth-fe | feat-auth-be（需 API 类型） | src/pages/auth/ |
```

Architect 按拓扑序串行调度。不引入 DAG 引擎——只标注"等谁"。

#### 9. 文件集预检漏检

**业界实践**：三层防线——prompt 级约束（减少 60-80% 越界）→ 返回后 `git diff --name-only` 检测 → 自动 revert 越界文件。共识：prompt 约束不能信任，返回后 diff 检查是可靠兜底。

**建议**：两层防线。
- Layer 1（预防）：prompt 中的 `[禁止修改]:` 清单
- Layer 2（检测）：Agent 返回后 `git diff --name-only`，逐文件对白名单。越界文件 → `git checkout -- <file>` 自动 revert → 记录到派发表

#### 10. Agent 需要改范围外文件

**业界实践**：单写者规则——每个文件只有一个 Agent 可以修改。共享文件由编排者所有，worker 只读。worker 需类型变更时通过契约文件通信。

**建议**：设计上消除问题——Architect 派发前识别共享文件，明确分配所有权。Agent 执行中确实需要改共享文件时：
- 暂停 → 报告 Architect → 判定
- 小改动（加字段）→ 更新契约 + 通知对方
- 大改动（改接口结构）→ 升级给人

### B. 集成与验证（3 项）

#### 11. 集成测试谁写

**业界实践**：各 Agent 写自己的单元测试；专门的 test_writer 或编排者写跨模块集成测试。期望各 Agent 测试自己与其他模块的交互是反模式。

**建议**：
- 各 Agent 写自己模块的单元测试 + 模块内集成测试（TDD 纪律已有）
- **Architect 写跨模块集成测试**——唯一有全局视角的角色

Architect 写的集成测试不分发，自己跑、自己修。暴露某 Agent 缺陷时通知该 Agent 修复。

#### 12. Critic 审什么

**业界实践**：两步审查——先审各 Agent 独立 diff（捕获特定角度），再聚合辩论（捕获跨模块不一致）。

**建议**：审**合并后的全量 diff** + 契约一致性检查（P1）。不审各 Agent 独立 diff。

理由：Critic 核心原则是 Fresh Context（不看开发者推理）。审合并结果不违反此原则。需追溯时 Architect 按 Agent commit 定位。

#### 13. CI 验证策略

**业界实践**：Agent 内门控 + Agent 间验证。每 Agent 将质量门控作为执行循环一部分，仅全部通过后才触发集成阶段的全量测试。

**建议**：两层验证。
- **Agent 内**：`npm run lint && npx jest --testPathPattern=<module>` —— 只跑自己模块，快
- **集成后**：`npm run ci:local` —— 全量 lint+type-check+test+coverage，准

### C. 失败与恢复（3 项）

#### 14. 单个 Agent 失败（3 strikes）

**业界实践**：保留已完成 Agent 结果（沉没成本不丢弃）。LangGraph checkpoint 只重试失败 Agent。H-RePlan 先局部修复，失败才升级全局。

**建议**：失败 Agent 不触发其他 Agent 回滚。
- 不影响接口 → 其他结果保留，单独处理
- 影响接口 → 标记受影响方，一并升级给人
- 3 次仍失败 → 升级给人，附带原因 + 已完成 Agent 结果清单

#### 15. 契约运行时变更

**业界实践**：ALAS 框架——共享状态 schema，所有 Agent 链接到同一中间表示。LangGraph——checkpoint 边界保存完整状态，下游 Agent 读取最新 checkpoint 获得上游变更。

**建议**：Agent 发现契约不完整 → 暂停 → 报告 Architect → 更新契约 → 通知对方重走 Step 0。
- 对方未做到相关部分 → 无影响
- 对方已做 → 增量调整
变更记录到派发表。改字段类型需对方调整；只加字段不影响已有实现。

#### 16. 回退策略

**业界实践**：保形错误归因——精准回退到失败步骤。COCO——只回退失败上下文片段。

**建议**：不引入自定义回退机制——Git 已足够。
- 每个 Agent 完成后，Architect 创建 checkpoint commit 作为回退锚点
- 粒度 1：`git revert <agent-commit>` —— 单 Agent 重做
- 粒度 2：`git reset --hard <dispatch-commit>` —— 全部重做
触发条件：集成测试失败 + 无法局部修复 → 升档回退。

### D. 与现有系统衔接（1 项）

#### 17. 与 /dev-loop 的关系

**业界实践**：条件路由——supervisor 读状态，动态决定下一个 Agent。同一工作流内分支。

**建议**：多 Agent 是 /dev-loop 的**内部变体**，不创建新命令。

```
/dev-loop Step 1（Architect 规划）
    → 判断多 Agent？YES → 产出 plan + 派发表 → 用户确认

Step 2（Developer 实现）—— 扩展为子循环：
    for each agent in dispatch_table（按依赖序）:
        → 启动 Agent（prompt 含文件范围 + 契约 + 验收标准）
        → 收集结果 → git diff 白名单检查 → 不通过则 revert
        → 创建 checkpoint commit → 下一个

Step 3（Critic 审查）→ 审合并全量 diff + 契约一致性
```

`.planning/dev-loop-state.json` 增加字段：

```json
{
  "stage": "developer",
  "mode": "multi-agent",
  "dispatch_table": [
    {
      "agent_id": "feat-auth-be",
      "status": "completed",
      "commit": "abc123",
      "summary": "实现认证 API，测试 12/12 PASS"
    },
    {
      "agent_id": "feat-auth-fe",
      "status": "in_progress",
      "depends_on": ["feat-auth-be"]
    }
  ]
}
```

---

## 八、细化讨论（7 项建议方案）

> 2026-06-23 在 §七 11 项基础上进一步细化。每项含建议 + 理由。

### 8.1 派发表格式规范

**建议**：Markdown 表格（人看，写入 plan）+ JSON 状态（状态跟踪，在 `.planning/dev-loop-state.json` 中），双格式各司其职。

Plan 中输出 Markdown 表格：

```markdown
## 并行派发

| # | Agent 名称 | 文件范围 | 禁止修改 | 契约 | 依赖 | Plan 章节 |
|---|-----------|---------|---------|------|------|----------|
| 1 | feat-auth-be | src/api/auth/ tests/unit/auth/ | src/pages/ src/types/ | design/contracts/auth-api.yaml | 无 | §3.1-3.3 |
| 2 | feat-auth-fe | src/pages/auth/ tests/unit/auth/ | src/api/ src/types/ | design/contracts/auth-api.yaml | feat-auth-be | §3.4-3.6 |

共享文件：package.json — Architect 集成阶段统一更新
```

状态文件 `.planning/dev-loop-state.json` 在执行时从派发表派生，增加运行时字段（status、commit、summary）。

**理由**：Plan 是人确认的入口，Markdown 可读性最高。状态文件是执行期产物，JSON 便于程序化更新。两份 90% 字段重叠但不合并——plan 是静态声明，状态文件是动态跟踪。

### 8.2 Architect prompt 具体改动

**建议**：三处增量追加，不重写现有流程。

**改动 1**：在"何时派生并行 Agent"段落后增加文件集预检输出要求：

```
派生并行 Agent 前，必须输出文件集检查表，确认各 Agent 的修改文件无交集：

  Agent A: [文件列表]    ← 逐个列出
  Agent B: [文件列表]    ← 逐个列出
  共享文件: [文件列表]   ← 明确标注谁有权修改

有交集 → 不派生，调整边界或改为串行。
```

**改动 2**：在"派生 Agent 时"段落中增加契约确认步骤：

```
4. Agent 启动后第一步：读契约文件 → 逐条确认可实现性 → 输出 CONFIRM 或 BLOCK（含具体理由）
5. 双方均 CONFIRM → 各自进入实现。任一方 BLOCK → 暂停，升级给人。
```

**改动 3**：在"Agent 返回后"段落中增加范围检查和 checkpoint：

```
7. Agent 返回后：git diff --name-only → 逐文件对白名单 → 越界文件 git checkout 回退 → 记录越界清单
8. 范围检查通过 → git add -A && git commit -m "checkpoint(<agent-name>): <subtask-summary>（N/N tests PASS）"
9. 全部 Agent 完成 → 全量 CI（lint+type-check+test+coverage）→ Critic 审查
```

**理由**：三处都是对已有 6 步流程的补充而非重写。文件集预检从 prose 升级为必须输出的检查表——不输出 = 跳过检查。契约确认从"创建契约文件"升级为"Agent 确认契约"。范围检查和 checkpoint 是新增兜底机制。

### 8.3 Subagent 如何获取 developer.md

**建议**：dispatch prompt 第一步指示 Agent 读取项目文件，不 inline 全文。

```
[启动]: 首先 Read prompts/developer.md（TDD 纪律），
        然后 Read design/contracts/auth-api.yaml（契约），
        确认可实现性后输出 CONFIRM，再进入 TDD 实现。
```

**理由**：Subagent 是 Fresh Context 但有 Read 工具，可以读项目文件。Inline 全文会让 dispatch prompt 膨胀到 500+ 行。多一次 Read tool call（~1s）换取 prompt 精炼。读完契约后能正确 CONFIRM/BLOCK 本身就是对 Agent 理解任务的第一道检验。

### 8.4 用户确认派发表的时机

**建议**：一次确认。Architect 输出 plan + 派发表后停下，人确认整体方案后自动推进。

```
Architect: 这是 plan + 派发表。可行吗？
人: c  ← 一次确认，plan 和派发表同时通过
```

**理由**：派发表是 plan 的一个章节，不是独立文件。拆开确认 = 同一份文档分两次审批。人对派发表有疑虑时会在确认 plan 时自然提出。如果执行中发现派发问题，契约确认机制（两绿才通过）已兜底——会升级给人。

### 8.5 Agent 返回值的解析协议

**建议**：Architect 不解析 Agent 文本返回，检查文件系统产物。

```
Agent 返回后 Architect 执行:

1. git diff --name-only HEAD..   → 改动文件列表
2. 逐文件对白名单                  → 范围检查
3. npm run lint                   → lint 结果
4. npx jest --testPathPattern=<module>  → 测试结果
5. 读 _scratch/<agent-id>/coverage/coverage-summary.json  → 覆盖率
```

**理由**："文件即协议"——业界共识。Agent 的 chat transcript 是不可靠的协调层。Agent 可能说"测试全绿"但实际有失败。文件系统产物是可验证事实，Agent 文本返回是声明。Architect 不信任声明，只信任事实——与 Critic Fresh Context 同一原则。

### 8.6 契约文件模板与来源决策

**建议**：三层兜底逻辑。

```
契约来源决策:

  1. 设计文档 / 人已提供接口规范？
      → YES → 锚定引用，写入 source 字段指向权威来源
      → NO  → 继续

  2. Architect 判断：此处是否存在跨模块接口依赖？
      → YES → Architect 提议契约（内容按最小模板输出，人确认后生效）
      → NO  → 不需要契约文件
```

契约文件的唯一作用：**告诉两个 Agent "接口规范在这里，按这个实现，不要偏离"**。它不是 Architect 的创作，是已有规范的锚点。

格式上优先引用：

```yaml
# design/contracts/auth-api.yaml
# 双方 Agent 以此为准。

# 情况 1: 已有规范 → 引用
source: design/specs/user-auth.md#api-specification

# 情况 2: Architect 提议（兜底，人确认后生效）
endpoint: POST /api/auth/login
request:
  username: string   # 必填，3-50 字符
  password: string   # 必填，8-128 字符
response:
  token: string
  expires_in: number
errors:
  401: "Invalid credentials"
  429: "Too many attempts"
```

**理由**：企业级系统的接口规范通常在设计文档中已明确定义（OpenAPI、Proto、PRD 接口章节），Architect 不应重复定义。兜底的最小模板在 2-3 Agent、简单 REST API 场景够用。字段名+类型+错误码是跨模块不一致的 90% 来源。未来需要更复杂契约时升档到 OpenAPI fragment。

### 8.7 Checkpoint commit 自动化

**建议**：Architect 执行 checkpoint commit，Agent 不负责。

```
Agent 返回 → 范围检查通过 → 测试通过 →
  Architect: git add -A && git commit -m "checkpoint(<agent-name>): <subtask-summary>（N/N tests PASS）"
```

**理由**：Agent 内部有自己的 commit 节奏（TDD: RED→GREEN→commit），但 Architect 的 checkpoint commit 是集成层面的锚点——标记"这个 Agent 的工作已验证、已接受"。范围检查必须在 commit 之前——如果 Agent 自己 commit 了越界文件，Architect 需先 revert。Author 是 Architect 会话，明确责任归属。回退粒度精准：`git revert <checkpoint-commit>`。

---

## 九、验证方法

1. `prompts/architect.md` 含文件集拆分判断 + 子任务输出格式，不出现 worktree 字样
2. `docs/multi-agent-guide.md` 含两层模型 + 完整分析过程 + worktree 真正适用场景
3. `templates/app-service/.worktreeinclude.tmpl` 存在且内容正确
4. `templates/app-service/STRUCTURE.md` 含 `_scratch/<agent-id>/` 约定
5. `npm test` + `npm run lint` 通过
