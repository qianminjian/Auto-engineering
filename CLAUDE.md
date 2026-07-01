# CLAUDE.md

## ⚠️ 硬禁令（2026-06-24 96GB 内存爆炸事故后确立）

**核心风险**：96GB 内存爆炸事故 — 3 个 subagent 并行扫描 `references/` 全量建立 file tree index，触发 macOS `vm-compressor-space-shortage` → 系统强制重启。

**参考源码已迁出项目根**（路径：`~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/`，下文 `$AE_REFS_DIR/`）。

**禁止：批量 / 并行加载（事故根因）：**

- ❌ 禁止并行启动多个 subagent 同时扫描 `$AE_REFS_DIR/`
- ❌ 禁止一次性 Read 整个框架（如 Read `$AE_REFS_DIR/langgraph/` 全部文件）
- ❌ 禁止 `ls -R $AE_REFS_DIR/` 递归列出全部文件（等同批量索引）
- ❌ 禁止 `find $AE_REFS_DIR/` 不带过滤列出所有文件
- ❌ 禁止 `grep -r $AE_REFS_DIR/` 后批量 Read 多个匹配文件

**允许的探索方式（单次 / 小批量 — 不触发内存爆炸）：**

- ✅ `ls $AE_REFS_DIR/` 顶层（只 6 个子目录名，轻量）
- ✅ `find $AE_REFS_DIR/ -name "目标.py" -type f`（定位单个文件）
- ✅ `grep -n "符号" $AE_REFS_DIR/特定路径`（只输出匹配行）
- ✅ Read 单个文件 50-200 行片段（用 `offset`/`limit`，绝不整文件 Read）
- ✅ 一次只探索一个组件（如只探索 `langgraph/pregel/_loop.py`）
- ✅ 探索后立即总结要点 + 丢弃 context，不缓存

**纪律：**

- 探索 ≠ 批量：可以探索，但限制单次 / 并行量级
- 优先 Grep 定位 → 50-200 行 Read → 立即丢弃（三步法）
- 不并行触发多 subagent 全量扫描 `$AE_REFS_DIR/`（事故根因）

**已迁出项目根**（`.gitignore` 保留防御行 + `pyrightconfig.json` 已移除 exclude）。

**Why：** 2026-06-24 16:10 atdo Phase 02 spawn 3 个 subagent，每个 claude code 进程启动时扫描项目根建立 file tree index（含 references/），3 个进程叠加吃掉 96 GB 物理内存，触发 macOS `vm-compressor-space-shortage` → 系统强制重启。

**How to apply：** 任何需要参考实现的场景，必须先 Grep 定位 50-200 行片段，绝不批量 Read。

---

## 项目信息

- 名称：Init-Engineering
- 类型：**Agent Skill** — 在 Claude Code agent 里以 skill 模式运行的项目环境初始化工具
- 版本：v5.0（聚焦 Init Engineering，Loop 已裁剪）
- 创建日期：2026-06-23
- 更新日期：2026-06-30

## 项目性质

本项目为 **Claude Code Skill**，在 agent 里调用，为 agent 工作流提供项目环境初始化能力。

两种初始化模式：
1. **存量项目**：通过代码分析自动识别项目类型、依赖、配置，自动化初始化
2. **新项目**：向导式询问确认方向，生成定制化项目骨架

核心依赖：`click`、`pydantic`、`asyncio`、`jinja2`、`pathspec`

## 架构

```
Init-Engineering
├── init/                          # 初始化引擎核心
│   ├── answers.py                 # AnswersMap（答案持久化）
│   ├── config_loader.py          # 配置加载器
│   ├── config_types.py           # 配置类型定义
│   ├── config.py                 # InitConfig 配置
│   ├── detector.py               # 项目类型检测器
│   ├── errors.py                 # init 专用错误
│   ├── hooks.py                  # 钩子执行器
│   ├── prompts.py                # 交互式问答 prompts
│   ├── renderer.py               # 模板渲染器
│   ├── scaffold_hooks.py         # 脚手架钩子
│   ├── scaffold_phases.py       # 脚手架阶段
│   ├── scaffold_render.py        # 脚手架渲染
│   ├── scaffold.py               # 脚手架生成器
│   └── templates/                 # 模板文件（43 个）
├── config/                        # 共享配置
│   ├── environment.py            # ProjectEnvironment（.ae-answers.yml 解析）
│   └── settings.py               # Settings（环境变量）
├── cli/                          # CLI 入口
│   └── __init__.py              # Click 命令（init/status）
├── skill.py                     # Agent Skill 入口
├── errors.py                     # 共享错误定义（AEError/ErrorCode）
└── __init__.py                   # 包入口
```

**参考框架：**

| 框架 | 路径 | 核心文件 | 用途 |
|------|------|---------|------|
| Copier | `$AE_REFS_DIR/copier/` | `_main.py`(Worker), `_user_data.py`(Question/AnswersMap) | init 脚手架参考 |
| Cookiecutter | `$AE_REFS_DIR/cookiecutter/` | `generate.py`, `prompt.py`, `main.py` | init 模板渲染参考 |
| Yeoman | `$AE_REFS_DIR/yeoman/` | `lib/routes/` | init 组合模式参考 |

## 设计文档

| 文档 | 内容 | 读取条件 |
|------|------|---------|
| `design/BEACON.md` | 设计基线（目标/范围/决策/当前状态） | 任何设计讨论时先读 |
| `design/INDEX.md` | 文档索引（含合并日志/归档清单） | 检索文档时 |
| `design/v5.0-Design-Init.md` | v5.0 Init Engineering 完整设计 | 开发 init 子系统时 |
| `design/v1.0-Design-Init.md` | v1.0 init 子系统设计 + 实现偏差审计 | 开发 `ae init` 时 |
| `design/v1.0-Design-Templates.md` | 43 个模板文件 + 8 个 ae-template.yml | 实现 `init/templates/` 时 |
| `design/his_bak/v1.0-Design-Shared.md` | 共享架构、CLI 设计、共享契约 | Init/Loop 共享契约参考 |

## 核心命令

```bash
# Agent Skill 模式
ae init                              # 新项目：向导式初始化
ae init --analyze <path>            # 存量项目：代码分析 + 自动初始化

# CLI 模式
ae init <project> --type <type>     # 项目类型：app-service/cli/library/package
ae init --list-types                # 列出支持的项目类型
ae init --list-templates            # 列出可用模板

# 配置
ae init-config                      # 查看/编辑初始化配置
```

## atdo 开发过程基本要求（2026-06-30 用户确立）

**核心约束**：atdo 自动化开发过程中，所有进展必须反馈到前台（Claude Code 会话），不得静默在后台开发。每次会话、每次 atdo 启动都生效。

**Why**：用户期望开发过程透明可见，避免长时间无反馈导致的"卡死焦虑"与"信任流失"。

**强制要求**：

- ✅ **Progress Display**：每 Phase / Step 开始前输出 `[Auto-Phase] Phase N/M: <name> | Step X/Y: <description]`（atdo 协议默认行为，不可省略）
- ✅ **Heartbeat 协议**：agent spawn 后每 5/10/15 分钟输出心跳（atdo agent-spawn-timeout.md 默认行为）
- ✅ **关键决策显式化**：阶段切换 / gate 通过 / 失败 / manual gate 触发 / 用户介入点必须显式输出
- ✅ **失败升级前台**：失败时不静默重试，立即告诉用户"已失败 + 当前状态 + 选项"
- ✅ **ALERT.md 写入路径**：`.phase-execution/ALERT.md` 必须前台摘要（不只是写文件）
- ✅ **CronCreate 唤醒后**：下次会话第一行输出 `atdo auto-resume for phase X/M` 让用户知道是续跑

**禁止**：

- ❌ 禁止用 Bash `run_in_background: true` 跑 atdo 相关命令（应前台执行，每步可见）
- ❌ 禁止 agent 输出超 10 分钟无 ProgressDisplay（违反 agent-spawn-timeout.md 心跳协议）
- ❌ 禁止 Step 间静默跳过（即使相同 Phase 必须显示状态变化）
- ❌ 禁止 push / force push / reset --hard / rm 等破坏性操作无前台确认

**B 级 hybrid gate 特殊规则**：

- ✅ **B 级 hybrid gate auto-pass**: atdo 推进遇到 B 级 hybrid gate（Phase 04/09/11 等）直接 auto-pass，不调 AskUserQuestion 等用户签字。跨会话规则已持久化至 memory `feedback-atdo-b-gate-auto-pass.md`。
- ✅ **Gate Code Review 强制 (atdo Step 7.5, atdo-GCR-01)**：每个 gate phase 完成后必须执行 /code review。auto-pass 仅跳过用户签字，**不跳过自动 code review**。BLOCKER 必须修复，WARNING 仅记录。v5.0 Phase 04/09/11 开发时因曲解 auto-pass 语义而漏执行（已记录到 final report）。

**How to apply**：

- 任何 `/atdo` 命令启动时，先在响应中显示 `[Auto-Phase] Phase N/M: ...` 进度条，再执行协议
- CronCreate 唤醒后第一时间输出 `atdo auto-resume for Phase N/M`，避免用户疑惑"这是新 run 还是续跑"
- Manual gate / AskUserQuestion 时显式标注"需要用户介入"
- 失败时不绕路，立即升级 ALERT 并给用户选项

---

## 管理约束

- tests/ 下测试，覆盖率 ≥ 80%
- 测试运行遵守 `@.claude/rules/pytest-memory-management.md`（16G 内存约束）
- 参考源码（`$AE_REFS_DIR/`）为只读，不修改
- 模板从 project-engineering-init 迁移，保持模板变量兼容
