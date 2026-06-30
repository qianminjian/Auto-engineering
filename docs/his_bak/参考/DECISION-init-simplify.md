# /init 工作流精简方案（详细版）

> 决策文档 | 2026-06-20

---

## 一、当前问题

### 1.1 现状：12 步交互

当前 `/init 工程化` 执行 12 个步骤，用户需要做 9 次选择：

```
Step 0: 前置检测               ← 自动
Step 1: 源码结构判定            ← 自动
Step 2: 项目类型判定            ← 用户选择（A-H，8 选 1）
Step 3: 对照模板输出 diff 预览  ← 用户确认（Y/n）
Step 4: 执行创建                ← 自动
Step 5: TDD 模式选择            ← 用户选择（A/B/C，3 选 1）
Step 5.5: Worktree 支持         ← 用户选择（A/B，2 选 1）
Step 5.6: Agent 协作            ← 用户选择（A/B，2 选 1）
Step 6: 本地约束（Lefthook）    ← 用户选择（A/B，2 选 1）
Step 7: CI 平台                 ← 用户选择（A/B/C/D，4 选 1）
Step 7.5: Token 预算            ← 用户选择（A/B，2 选 1）
Step 8: 输出指引                ← 自动
```

**问题**：

1. **决策疲劳**：用户在 Step 2 已经做了 8 选 1，到 Step 5 时还要连续 3 次做技术决策（TDD模式/Worktree/Agent）——这是三个大部分新用户不理解的概念
2. **顺序不合理**：Step 5（TDD）和 Step 6（Lefthook）都是"质量保障"但一个在中间一个在后面，用户需要在不同阶段思考同一类问题
3. **业界对比**：`npx create-next-app` 只有 1 个交互（"Use TypeScript? Yes/No"），`npm init` 也是 1 个交互。业界最佳实践是：初始化工具 = 快速进入可工作状态，配置 = 后续按需进行
4. **存量项目更糟糕**：存量项目多出 Step 0-1 的检测和 Step 3 的 diff 预览——但 TDD/Lefthook/CI 这些高级功能对于存量项目同样适用，用户同样需要走完 12 步

### 1.2 哪些决策必须初始化时做，哪些可以延后？

| 决策 | 初始化时必须？ | 原因 |
|------|:---:|------|
| 项目类型（8 选 1） | ✅ 是 | 决定目录骨架，无法延后 |
| 源码根 | ✅ 是 | 决定 src/ 的命名，无法延后 |
| diff 预览 + 确认 | ✅ 是 | 安全：用户必须确认改动 |
| TDD 模式 | ❌ 否 | 项目开始编码时才需要 |
| Worktree | ❌ 否 | 只有在需要并行开发时才需要 |
| Agent 协作 | ❌ 否 | 只有在需要多 Agent 时才需要 |
| Lefthook 配置 | ❌ 否 | 可以默认生成（生成了不安装不影响） |
| CI 平台选择 | ❌ 否 | 可以默认生成 GitHub Actions（业界主流） |
| Token 预算 | ❌ 否 | 只有在需要控制成本时才需要 |

**结论**：只有项目类型和源码根必须在初始化时确定。其余全部可以延后——要么默认生成（零成本），要么按需启用。

---

## 二、新方案：2 步交互 + 7 个子命令

### 2.1 第一步：`/init 工程化`

```
用户打开终端 → cd my-project → 启动 Claude Code

用户: /init 工程化

AI: 检测到空目录（或存量项目）
    请选择项目类型:
      A. Application/Service  — REST API、前端、后端
      B. Library/SDK          — 可发布的 npm/pip 包
      C. CLI Tool             — 命令行工具
      D. Skill                — Claude Code 技能
      E. Hook                 — Claude Code 钩子
      F. MCP Server           — MCP 服务端
      G. Spec/Doc             — 规范文档仓库
      H. Monorepo             — 多子项目

用户: A

AI: ┌─────────────────────────────────────────────┐
    │ 将创建以下内容:                              │
    │                                              │
    │ my-project/                                  │
    │ ├── src/                  ← 业务代码         │
    │ ├── tests/unit/           ← 镜像 src/        │
    │ ├── tests/integration/                       │
    │ ├── tests/__support__/    ← fixtures/mocks/..│
    │ ├── scripts/              ← 5 个测试脚本      │
    │ ├── docs/                                    │
    │ ├── design/                                  │
    │ ├── .claude/              ← rules/           │
    │ ├── lefthook.yml          ← 6 道门 Hook      │
    │ ├── justfile              ← 命令入口         │
    │ ├── .github/workflows/    ← CI 7 道门        │
    │ ├── package.json          ← 5 个统一 scripts │
    │ ├── .gitignore                               │
    │ └── CLAUDE.md             ← AI 引导           │
    │                                              │
    │ 不会修改任何已有文件（如果是存量项目）         │
    │ 确认创建？[Y/n]                              │
    └─────────────────────────────────────────────┘

用户: Y

AI: ✅ 项目骨架已生成。
    
    下一步:
      1. 开始编码
      2. 按需启用高级功能:
         /project:tdd      → 启用 TDD 模式
         /project:worktree → 启用多分支 Worktree
         /project:agent    → 启用多 Agent 协作
         /project:ci       → 切换 CI 平台
         /project:token    → 启用 Token 预算
         /project:lint     → 配置 Lint 工具
         /project:test     → 配置测试框架
      3. lefthook install（激活 Git Hook）
```

**关键变化**：

| 项目 | 旧方案 | 新方案 |
|------|--------|--------|
| 交互次数 | 9 次选择 | 1 次选择 + 1 次确认 |
| Lefthook | 询问是否启用 | **默认生成**（生成了不安装不影响） |
| CI | 询问选平台 | **默认生成 GitHub Actions**（主流平台） |
| TDD/Worktree/Agent/Token | 初始化时问 | **按需启用**（通过子命令） |
| Lint/Test 配置 | 不生成 | **按需启用**（通过子命令） |

### 2.2 第二步：子命令（7 个，每个 1 步）

#### `/project:tdd` — 启用 TDD 模式

```
用户: /project:tdd

AI: 选择 TDD 模式:
      A: Strict — Red→Green→Refactor + 边界值/空值/异常全覆盖
      B: Base   — Red→Green→Refactor
      C: 不启用

用户: A

AI: 执行:
  1. 复制 ~/.claude/skills/tdd/ → .claude/skills/tdd/
  2. 在 CLAUDE.md 中写入:
     
     ## TDD 模式
     - 模式: strict
     - 覆盖率阈值: 80%
     - 启用日期: 2026-06-20

  3. 输出: "TDD Strict 模式已启用。编码时将自动遵循 Red→Green→Refactor。
           合规由 CI 覆盖率门禁（Gate 5: ≥80%）保障。"
```

#### `/project:worktree` — 启用多分支 Worktree

```
用户: /project:worktree

AI: 确认启用 Git Worktree 多分支支持？[Y/n]

用户: Y

AI: 执行:
  1. 生成 scripts/worktree-add.sh（参数化创建脚本）
  2. 生成 scripts/worktree-cleanup.sh（清理脚本）
  3. 复制 ~/.claude/skills/worktree/ → .claude/skills/worktree/
  4. 在 CLAUDE.md 中写入:

     ## Worktree 约定
     - 目录命名: {project}-[{boundary}-]{type}-{desc}
     - 创建: scripts/worktree-add.sh
     - 清理: scripts/worktree-cleanup.sh

  5. 输出: "Worktree 已启用。使用 /worktree 命令创建并行开发环境。"
```

#### `/project:agent` — 启用多 Agent 协作

```
用户: /project:agent

AI: 确认启用多 Agent 协作？[Y/n]
    注意: 当前 Claude Code 不支持自动启动 Agent 会话，
    Round 执行需要人在各 Worktree 中手动操作。
    推荐熟悉 Worktree 后再使用。

用户: Y

AI: 执行:
  1. 复制 ~/.claude/skills/agent-dev/ → .claude/skills/agent-dev/
  2. 复制 ~/.claude/skills/agent-critic/ → .claude/skills/agent-critic/
  3. 复制 ~/.claude/skills/agent-orchestrator/ → .claude/skills/agent-orchestrator/
  4. 创建 design/contracts/ + artifacts/ 目录
  5. 在 CLAUDE.md 中写入:

     ## Agent 协作声明
     - 角色: 待分配（使用 /agent-orchestrator start-round）
     - 关联角色: 待分配
     - 共享契约: design/contracts/

  6. 输出: "Agent 协作已启用。使用 /agent-orchestrator start-round 开始。"
```

#### `/project:ci` — 配置 CI 平台

```
用户: /project:ci

AI: 当前 CI 配置: GitHub Actions（默认）
    选择:
      A: 保持 GitHub Actions（已生成）
      B: 切换为 GitLab CI（生成 .gitlab-ci.yml，移除 .github/）
      C: 两者都保留
      D: 移除 CI 配置

用户: B

AI: 执行:
  1. 生成 .gitlab-ci.yml（7 道门）
  2. 移除 .github/workflows/tdd-check.yml（可选）
  3. 输出: "CI 已切换为 GitLab CI。"
```

#### `/project:token` — 启用 Token 预算

```
用户: /project:token

AI: 选择 Round Token 预算上限:
      A: 不启用（默认）
      B: $5.00 / Round（推荐）
      C: 自定义金额: ___

用户: B

AI: 执行:
  1. 在 CLAUDE.md 中写入:

     ## Token 预算
     - 模式: on
     - 单 Round 上限: 5.00  # 美元
     - 入口: claude -p --max-budget-usd 5.00

  2. 输出: "Token 预算已启用: $5.00/Round。仅在 -p 模式生效。"
```

#### `/project:lint` — 配置 Lint 工具

```
用户: /project:lint

AI: 检测到 {language} 项目。选择 Lint 工具:
      A: ESLint (JavaScript/TypeScript)
      B: Ruff (Python)
      C: golangci-lint (Go)
      D: 其他: ___
      E: 跳过

用户: A

AI: 执行:
  1. 生成 .eslintrc.json（默认配置）
  2. 更新 lefthook.yml pre-commit 的 lint 命令（从占位符改为 npx eslint）
  3. 更新 justfile gate-lint 命令
  4. 输出: "ESLint 已配置。运行 just gate-lint 检查。"
```

#### `/project:test` — 配置测试框架

```
用户: /project:test

AI: 检测到 {language} 项目。选择测试框架:
      A: Jest (JavaScript/TypeScript)
      B: pytest (Python)
      C: go test (Go)
      D: 已有框架，仅更新脚本
      E: 跳过

用户: B

AI: 执行:
  1. 更新 scripts/test.sh: npx jest → pytest tests/ -v
  2. 更新 scripts/test-unit.sh
  3. 更新 scripts/test-integration.sh
  4. 更新 scripts/test-cov.sh: npx jest --coverage → pytest tests/ --cov
  5. 生成 pytest.ini（默认配置）
  6. 更新 justfile
  7. 输出: "pytest 已配置。运行 just test 验证。"
```

---

## 三、完整示例：从零到完整项目

### 场景：Python 项目，需要 Strict TDD + Worktree + GitHub Actions

```
# 第一次会话
用户: mkdir my-api && cd my-api && claude
     /init 工程化
     → 选 A (Application/Service) → 确认 → 生成骨架

# 第二次会话（可能是一周后）
用户: cd my-api && claude
     /project:tdd → 选 A (Strict) → TDD 已启用
     /project:worktree → Y → Worktree 已启用

# 第三次会话（团队有需求时）
用户: cd my-api && claude
     /project:agent → Y → Agent 已启用
     /project:token → 选 B ($5) → Token 已启用
```

对比旧方案：用户第一次就要在 9 个选择中做出 7 个技术决策（包括还不理解的 Worktree 和 Agent）。新方案中按实际需求渐进启用。

---

## 四、存量项目兼容

```
用户: cd existing-project && claude
     /init 工程化

AI: 检测到存量项目:
    已有: src/、package.json
    缺失: tests/、scripts/、docs/、design/、.claude/、lefthook.yml、justfile

    将创建（增量补充）:
      tests/unit/ + tests/integration/ + tests/__support__/
      scripts/test*.sh ×5
      docs/tdd-rules.md + review-checklist.md
      design/BEACON.md + decisions/
      .claude/rules/
      lefthook.yml + justfile
      .github/workflows/tdd-check.yml
      CLAUDE.md（合并已有）

    不会修改:
      src/ 下的任何文件
      package.json 仅追加 5 个 scripts（不覆盖已有）

用户: Y → 生成完成
     /project:tdd → 选 A → TDD 已启用
```

---

## 五、实施清单

| # | 任务 | 影响文件 |
|---|------|---------|
| 1 | 重写 specs/init-workflow.md | 全篇：旧 12 步 → 新 2 步 + 7 子命令 |
| 2 | 更新 project-engineering-init/SKILL.md | 触发词 + 工作流描述 |
| 3 | 更新 project-engineering-init/scaffold.sh | Step 0-8 → Step 0-2 + 子命令实现 |
| 4 | 更新 project-engineering-init/design/task-backlog.md | 任务拆分（S01-S08 简化为 S01-S02 + S27-S33） |
| 5 | 更新 TRAINING.md 第一板块 | 两步交互示例 |
| 6 | 更新 DESIGN-OVERVIEW.md | /init 描述 |
