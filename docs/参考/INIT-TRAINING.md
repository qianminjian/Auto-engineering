# Auto-Engineering init 子系统 — 培训材料

> v1.0.0 | 2026-06-24

---

## 前言：init 子系统解决什么问题

AI 编码进入生产，init 子系统针对**新项目启动**和**存量项目接入**两类高频场景，解决四个核心问题：

| 问题 | 现象 | 解决方式 |
|------|------|---------|
| **质量不可控** | AI 写的代码有时对有时错 | TDD 纪律（prompt）+ CI 7 道门 |
| **协作混乱** | 多人+AI 并行，代码互相覆盖 | Architect 角色 + Worktree 隔离 + 契约文件 |
| **迭代退化** | AI 越改越差，不知道什么时候停 | 停滞检测（3 次失败→停）+ 硬上限 |
| **安全盲区** | 硬编码密钥、SQL 注入 | Lefthook gitleaks + CI semgrep |

---

## 第一板块：`ae init` 工程化 — 5 分钟搭建项目骨架

### 解决的问题

"每次开新项目都要手动创建目录、配置测试框架、写 CI、配 Hook。"

### 使用方式

```bash
cd my-project
ae init . --type app-service
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

### 常用选项

| 选项 | 用途 | 示例 |
|------|------|------|
| `--type` | 指定项目类型（A-H） | `--type app-service` |
| `--defaults` | 非交互模式，全部用默认值 | `--defaults` |
| `--force` | 允许覆盖非空目录 | `--force` |
| `--from-answers` | 从 `.ae-answers.yml` 恢复答案 | `--from-answers ./previous.yml` |
| `--pretend` | 干跑模式，只显示不写盘 | `--pretend` |
| `--skip-tasks` | 跳过钩子任务（git init/install） | `--skip-tasks` |
| `--no-cleanup` | 失败时保留产物（用于调试） | `--no-cleanup` |

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
  → Lefthook（硬约束）: commit 前 lint + test-unit
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
ae init . --type CLI Tool → 生成骨架
开发功能 → TDD RED→GREEN→REFACTOR
git commit → Lefthook 自动检查
git push → CI 自动检查 → 通过 → 发布
```

使用功能：init、TDD 纪律、Lefthook、CI。

不使用：多 Agent 并行（一个人不需要）。

### 中等项目：前后端分离

```
ae init . --type Application/Service
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
ae init . --type Monorepo
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