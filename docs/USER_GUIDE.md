# Auto-Engineering 用户指南

> 适用版本：5.8.0-rc.5｜更新：2026-08-29

Auto-Engineering 通过离散 Tick 协议，让宿主 Agent 执行推理与工具调用，让 Python Core
负责状态、门禁、验证和恢复。Claude Code 与 Codex 共用同一 Core。

## 1. 选择宿主入口

| 宿主 | 入口 | 说明 |
|---|---|---|
| Claude Code | `/auto-engineering:dev-loop "需求"` | slash command |
| Codex | `$auto-engineering`，随后描述需求 | Skill |

两种入口最终都调用插件自带的 `ae-run`。Python Core 不直接调用 LLM，也不要求 Core
安装某个特定 Provider SDK。

## 2. 安装与预检

Claude Code Marketplace 安装：

```text
/plugin marketplace add qianminjian/Auto-engineering
/plugin install auto-engineering
```

Codex 和 Claude Code 都由宿主原生 Marketplace 管理 `.codex-plugin/`、`.claude-plugin/`、
`skills/` 与 Hook 资产；安装后从各自入口进入。本仓库开发机不得直接把源码目录注册成任一
宿主 Marketplace。标准本机安装入口为：

```bash
uv run python scripts/install_codex_local.py --source qianminjian/Auto-engineering
uv run python scripts/install_claude_local.py --source qianminjian/Auto-engineering
```

两个命令均先卸载用户级旧插件和同名 Marketplace，再调用宿主原生 Git Marketplace 安装。
Codex 可用 `--ref <git-ref>` 固定分支或标签；Claude Code 使用仓库默认分支。插件缓存、
启用状态和安装路径由宿主管理，不由本项目另建 staging 目录。开发目录只用于执行安装
脚本，不会被注册为运行时 Marketplace。

直接使用宿主命令也可以：

```bash
codex plugin marketplace add qianminjian/Auto-engineering
codex plugin add auto-engineering@auto-engineering
```

源码安装与预检：

```bash
uv sync
ae-run doctor
```

如需可选 Provider SDK：

```bash
uv sync --extra anthropic
uv sync --extra openai
```

`doctor` 显示宿主模式、项目环境、Init manifest、可选功能和依赖问题，但不修改项目。

## 3. 最小 Tick 工作流

```bash
ae-run dev-loop --init "需求"
```

stdout 返回首个 action JSON。宿主 Agent 按 action 完成工作，生成符合 schema 的
`result.json`，再推进：

```bash
ae-run dev-loop --tick --result result.json
ae-run status --format json
ae-run dev-loop --resume
```

循环结束时 action 为 `done`。诊断信息写 stderr，便于脚本安全消费 stdout JSON。

## 4. 项目前置条件

目标项目不强制依赖 Init Engineering。Auto-Engineering 默认通过本地确定性探测和
`ae.toml` 解析项目语言、源码/测试根和工具命令；已有 `.ae-state/init-manifest.json`
时，仅作为只读兼容输入消费。空项目或无法识别项目能力时，`doctor` 会明确提示缺失项，
不会把缺少 Init manifest 误报成安装失败。

## 5. 配置与运行状态

- `.ae-state/`：checkpoint、result、metrics 等本地状态。
- `ae.toml`：项目配置。首次启动 `dev-loop` 时必须存在有效配置；交互终端会启动
  向导，Claude Code/Codex 等非交互宿主会自动写入可立即运行的 standard
  Profile。环境变量优先级高于文件，可在运行前逐项覆盖。也可提前执行
  `ae doctor --init-config` 生成标准配置，或执行 `ae doctor --wizard` 自定义。
- `FeatureManifest`：全部 `AE_*` 功能默认值的唯一事实源。
- `RuntimeConfig`：业务代码的类型化配置访问层。

通过 `ae-run doctor` 查看功能。安全相关包括 `AE_PII_ENABLED`、
`AE_PRODUCTION`、`AE_STRICT_RED`；可观测性包括 `AE_AUDIT_LOG`、`AE_METRICS`、
`AE_OTLP_ENDPOINT`。

## 6. 质量流程

每个 Tick 按当前 Stage 执行：

1. Guardrail 前后置约束。
2. safety、lint、type check、audit、contract、test、build Gates。
3. critic、component、plate、system 与 system deep audit 五层验证。
4. checkpoint 原子持久化。

验证范围可按变更范围裁剪，但必需层不可被提示词或口头结论短路。

## 7. Release 验收

自动检查解压归档、隔离安装、运行 doctor 与最小 Tick，记为 `archive_smoke`。只有在
真实 Claude Code 或 Codex 产品内安装并运行，才能把 `product_install` 标为 `pass`；
未执行时必须显示 `not_run`。

## 8. 常见问题

**找不到 CLI**：确认项目 `.venv/bin/ae` 可执行，或系统能找到 `uv`，然后运行
`ae-run doctor`。

**宿主未识别**：从 Claude Code 的 `/auto-engineering:dev-loop` 或 Codex 的
`$auto-engineering` 进入，不要手工伪造宿主状态。

**Tick 无法恢复**：先查看 `ae-run status --format json`；保留
`.ae-state/` 供诊断，不直接编辑 checkpoint 数据库。

## 9. 更多资料

- 当前设计：`design/v5.6-Design-Loop.md`
- 目标设计：`design/v5.7-Protocol-Kernel-Design.md`
- 当前跟踪：`design/IMPLEMENTATION-TRACKER.md`
- API：`docs/api-reference.md`
- 历史：`design/HISTORY.md`
