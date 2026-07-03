# Auto-Engineering v5.0 用户指南

## 这是什么

Auto-Engineering 是 **Claude Code Plugin 形态的 Loop Engineering 脚手架**。在 Claude Code 会话中输入 `/dev-loop "需求描述"`，插件会调度 Python Loop Engine 执行 architect → developer → critic 三阶段 Agent 循环，自动产出代码变更、测试、审查结论。

核心特性：
- **三阶段 Agent 循环**（architect / developer / critic）
- **5 层 Guardrail 守门**（每阶段前后自动检查）
- **7 道 Gate 质量门**（safety / lint / type_check / contract / test / coverage / build）
- **SQLite checkpoint 恢复**（中断后不丢进度）
- **双层 Agent 输出解析**（schema + regex fallback）
- **Init-Loop 接口契约**（消费 Init 项目产出的 init-manifest.json）

---

## 安装（用户级一次性, 单条命令）

```bash
bash install.sh    # 1 条命令完成全部安装
```

`install.sh` 做 3 件事:
1. `git clone` 源码到 `~/.claude/plugins/auto-engineering/`
2. `uv tool install .` 全局装 Engine (`~/.local/bin/ae`)
3. 注册 plugin 到 `~/.claude/plugins/installed_plugins.json` (Claude Code 发现机制)

Claude Code 通过 `installed_plugins.json` 识别 plugin (不是目录扫描).

安装完成后**重启 Claude Code**, `/dev-loop` 在所有项目可用.

### 卸载
```bash
bash uninstall.sh
```

### 升级
```bash
cd ~/.claude/plugins/auto-engineering && git pull && bash install.sh
```

---

## 使用方式

### 方式 A: Plugin 模式（推荐，Claude Code 内）

重启 Claude Code 后，在任何项目目录输入：

```
/dev-loop "实现用户登录功能"        # 启动完整 3 Stage 循环
/status                              # 查看当前进度 (JSON)
/checkpoint list                    # 列出所有 checkpoint
/checkpoint show <id>               # 查看 checkpoint 详情
/project-tdd "需求"                 # TDD 快速循环 (跳过 Gate)
/project-worktree "需求"            # 在 git worktree 中执行
/project-agent architect "分析模块"  # 单 Agent 调用
/project-ci                         # 跑全量 Gate
```

### 方式 B: CLI 模式（终端直接调用）

```bash
ae dev-loop "需求描述"
ae gate-check --all
ae status --format json
ae doctor
```

CLI 模式需要独立的 `ANTHROPIC_API_KEY`（Plugin 模式从 Claude Code Agent 继承 key）。

---

## 7 个 Slash Commands

| Command | 作用 | 典型用法 |
|---------|------|---------|
| `/dev-loop` | 启动 3 Stage Agent 循环 | `/dev-loop "实现 JWT 登录"` |
| `/status` | 查看当前 loop 进度（JSON 7 字段） | `/status` 或 `/status --format json` |
| `/checkpoint` | 管理 SQLite checkpoint | `/checkpoint list` `/checkpoint show <id>` `/checkpoint resume <id>` `/checkpoint delete <id>` |
| `/project-tdd` | TDD 快速循环（跳过 Gate） | `/project-tdd "加单元测试"` |
| `/project-worktree` | 在 git worktree 中执行 | `/project-worktree "实验性功能"` |
| `/project-agent` | 单 Agent 调用 | `/project-agent architect "分析这个模块"` |
| `/project-ci` | 跑全量 Gate 检查 | `/project-ci` |

`/project-*` 类命令是项目级快捷方式（绕过 Plugin 模式校验，专为快速实验设计）。

---

## Engine 命令（CLI 调试用）

```bash
# 环境验证
ae doctor

# Gate 检查
ae gate-check --quick       # 3 道核心 Gate (safety+lint+type_check)
ae gate-check --all         # 全部 7 道 Gate

# 单 Agent 调用
ae agent architect "分析 OAuth2 流程"
ae agent developer "实现用户模型"
ae agent critic "审查 PR #42"

# Loop 状态
ae status --format json      # JSON 7 字段输出

# Checkpoint 管理
ae checkpoint list
ae checkpoint show <id>
ae checkpoint resume <id>
ae checkpoint delete <id>
```

---

## 工作流示例

### 完整开发流程

```bash
# 1. 在 Claude Code 中启动
/dev-loop "实现用户登录 API (JWT, 邮箱+密码)"

# Engine 自动:
#   - architect: 分析需求, 生成 plan/batch_plan/contracts
#   - developer: 实施代码 + 测试
#   - critic: 审查代码
#   - Guardrail 每阶段前后检查
#   - 7 道 Gate 全跑
#   - checkpoint 保存

# 2. 查看进度
/status
# 输出: thread_id, round, stage, verdict, recent_history

# 3. 中断后恢复
/checkpoint list
/checkpoint resume <thread_id>

# 4. 项目级 CI
/project-ci
```

### 团队协作流程

```bash
# 1. 团队成员各自安装 (一次性)
git clone git@github.com:qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
cd ~/.claude/plugins/auto-engineering && uv sync

# 2. 成员 A 在项目 A 中运行
cd ~/projects/project-a
/dev-loop "实现订单模块"

# 3. 成员 B 在项目 B 中运行
cd ~/projects/project-b
/dev-loop "实现支付回调"

# 两人都使用同一 Engine, 但 loop 状态独立 (SQLite per-project)
```

---

## 故障排查

### `/dev-loop` 报 "init-manifest.json 不存在"

需要先运行 Init Engineering 项目初始化生成 `.ae-state/init-manifest.json`。这是 Init-Loop 接口契约（IL-AC-01）要求。

**解决**：从 Init Engineering 项目获取或手动创建：
```json
{
  "schema_version": "1.0",
  "project_type": "app-service",
  "language": "python",
  "conventions": {
    "linter": "ruff",
    "type_checker": "pyright",
    "test_runner": "pytest"
  },
  "structure": {
    "source_root": "src/",
    "test_root": "tests/"
  }
}
```
放至 `.ae-state/init-manifest.json`。

### Gate 失败

| Gate | 失败原因 | 解决 |
|------|----------|------|
| safety | 检测到 API key / token | 从代码中删除敏感信息 |
| lint | ruff 检查失败 | `uv run ruff check --fix .` |
| type_check | mypy/pyright 失败 | `uv run mypy src/` |
| contract | ContractGate 不匹配 | 调整 architect 的 contracts 定义 |
| test | pytest 失败 | `uv run pytest -v` |
| coverage | 覆盖率 < 阈值 | 添加测试 |
| build | 导入失败 | `uv run python -c "import auto_engineering"` |

### Plugin 不被识别

```bash
# 1. 检查 symlink
ls -la ~/.claude/plugins/auto-engineering

# 2. 检查 plugin.json
python3 -c "import json; print(json.load(open('~/.claude/plugins/auto-engineering/.claude-plugin/plugin.json'))"

# 3. 重启 Claude Code
# 4. /help — 确认 7 个 /ae:* 命令已注册
```

### /dev-loop 跑得太慢

Engine 内部用 asyncio.gather 并行执行 N 个 task。慢通常因为：
- LLM API 慢（Claude API rate limit）
- Guardrail 阻塞（连续重试 3 次）
- 缺少 init-manifest 导致 Gate 配置回退

### `uv sync` 失败

```bash
cd ~/.claude/plugins/auto-engineering
uv sync                    # 依赖问题
ae doctor            # 环境问题
```

---

## 项目结构

```
~/.claude/plugins/auto-engineering/     # 安装根目录 (Claude Code 扫描)
├── auto_engineering/                    # Engine 核心代码
│   ├── loop/                            # Loop 控制流
│   │   ├── orchestrator.py            # 12 步主循环
│   │   ├── stage_router.py            # T1-T6 转换
│   │   ├── guardrail.py               # 5 Guardrails
│   │   ├── round.py                   # asyncio.gather
│   │   └── init_contract.py           # Init-Loop 契约
│   ├── gates/                          # 7 Gate 实现
│   ├── agents/                         # BaseAgent + authz
│   ├── cli/                            # Click 命令
│   └── tools/                          # file/bash/git tools
├── .claude-plugin/
│   └── plugin.json                    # Plugin manifest
├── commands/                           # 7 slash command 定义
├── hooks/                              # 5 lifecycle 事件脚本
├── skills/                             # Agent skill 描述
├── docs/                               # 用户文档 + API 参考
├── design/                             # 设计文档 (v5.0-Design-Loop, BEACON)
├── tests/                              # 1253 测试
├── Makefile                            # make test/ci
├── pyproject.toml                      # Python 项目配置
└── CLAUDE.md                           # Claude Code 项目规则
```

---

## 更新

```bash
cd ~/.claude/plugins/auto-engineering
git pull origin main
uv sync
```

---

## 卸载

```bash
rm -rf ~/.claude/plugins/auto-engineering   # 完整删除 (代码+symlink 一起)
```

**注意**：不会删除 `~/.claude/settings.json` 中的项目级 settings（如有手动配置）。

---

## 进阶配置

### 环境变量

| 变量 | 作用 | 必需 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Claude API key | CLI 模式必需，Plugin 模式可省略（从 Claude Code Agent 继承）|
| `AE_LOG_LEVEL` | 日志级别 (DEBUG/INFO/WARNING) | 否 |
| `AE_GATE_TIMEOUT` | Gate 超时（秒） | 否 |
| `AE_DB_PATH` | SQLite checkpoint 路径 | 否 |

### Init-Loop 集成

Auto-Engineering 是 Init-Loop 接口契约的 Loop 端。Init 端（独立项目）负责：
- 生成 `.ae-state/init-manifest.json`
- 写 init manifest + answers map
- 创建项目骨架

Loop 端（本项目）消费 init manifest：
- 读 manifest → 配置对应 Gate
- 按 language 配置工具映射（Python→ruff/pyright/pytest，TS→eslint/tsc/vitest，Go→golangci-lint/go vet/go test 等）

---

## 相关文档

- `CLAUDE.md` — 项目规则（Claude Code 行为约定）
- `design/BEACON.md` — 项目明灯（目标/范围/决策）
- `design/v5.0-Design-Loop.md` — 完整设计文档（2934 行）
- `docs/api-reference.md` — v5.0 API 接口 + 5 代码示例
- `docs/PLUGIN-USAGE.md` — Plugin 安装/使用
- `docs/production-deployment.md` — 生产部署
- `docs/EARS-v5.0.md` — 验收 15 AC + 5 IL-AC

---

## 反馈

- GitHub: https://github.com/qianminjian/Auto-engineering
- 内部测试项目: `/Users/minjianq/Documents/66-Project/ClaudeCode/test-project/prismscan_for_auto_cc`
- 测试状态: 1253 passed + 1 skipped, 7/7 doctor, 7/7 smoke, 20/20 acceptance, 90% coverage
