# Auto-Engineering v5.0 Production Deployment

> **Version**: 5.0.0 | **Status**: Production-ready | **Last updated**: 2026-07-01
> 决策依据: `design/BEACON.md` 决策 #28 · `docs/PLUGIN-USAGE.md`
>
> v1.0 / v2.0 / v2.3 部署章节已删除 — 归档版本见 `_scratch/his_bak/production-deployment.md` (v2.2 FINAL, 79 行)。

Auto-Engineering v5.0 以 **Claude Code Plugin** 形式分发。部署 = 把 `.claude-plugin/` 拷贝到目标项目 + uv sync + 重启 Claude Code。

---

## 1. 系统要求

| 组件 | 最低版本 | 检查命令 |
|------|---------|----------|
| Python | 3.10+ | `python3 --version` |
| uv | 0.1.0+ | `uv --version` |
| git | 2.30+ | `git --version` |
| sqlite3 (CLI) | 3.35+ | `sqlite3 --version` |
| Claude Code | 1.0.0+ | `claude --version` |
| 操作系统 | macOS 12+ / Linux / WSL2 | — |
| 物理内存 | 16 GB+ | `free -h` / 活动监视器 |
| 磁盘 | 2 GB+ (含 .venv) | `df -h .` |

> **16G 内存约束**：本机 16 GB 物理内存时，pytest + coverage 叠加 ~2x → 必须 `--no-cov`。详见 `.claude/rules/pytest-memory-management.md`。

---

## 2. 安装流程

### 2.1 步骤总览

```bash
# 1. 拷贝 Plugin 到目标项目
cd ~/path/to/your-project
cp -r /path/to/auto-engineering/.claude-plugin ./

# 2. 拷贝项目级配置（可选，但建议）
cp -r /path/to/auto-engineering/.claude ./your-project/.claude

# 3. 创建 Python 虚拟环境
uv sync                          # 创建 .venv + 安装 deps

# 4. 设置 API Key
export ANTHROPIC_API_KEY="sk-ant-..."

# 5. 验证环境
.venv/bin/ae doctor              # 必须全 ok

# 6. 重启 Claude Code（Plugin 加载）
# 关闭并重新打开 Claude Code 会话
```

### 2.2 验证 Plugin 注册

```bash
# Claude Code 内
/help
# 应见 7 个 /ae:* 命令:
#   /ae:dev-loop  /ae:status  /ae:checkpoint
#   /ae:project-tdd  /ae:project-worktree  /ae:project-agent  /ae:project-ci
```

> 真实环境验证（cp + restart + /help）由用户执行（EARS AC-12）。

### 2.3 验证 dev-loop 端到端

```bash
# 在 Claude Code 内
/ae:dev-loop "实现一个 hello world 函数" --max-rounds 3

# 或 CLI
.venv/bin/ae dev-loop "实现 hello world" --max-rounds 3
```

期望：3 Stage (architect → developer → critic) → APPROVE → 退出码 0。

---

## 3. 环境变量 (9 个)

| 变量 | 必需 | 默认 | 说明 |
|------|------|------|------|
| `ANTHROPIC_API_KEY` | **是** | — | Anthropic API Key。未设 → `ae doctor` 报错，dev-loop exit 2 (EARS AC-09) |
| `AE_DB_PATH` | 否 | `.ae-state/checkpoints.db` | SQLite checkpoint 路径 |
| `AE_LOG_LEVEL` | 否 | `INFO` | 引擎日志级别 (`DEBUG`/`INFO`/`WARN`/`ERROR`) |
| `AE_GATE_TIMEOUT` | 否 | `300` | Gate 执行超时 (秒) |
| `AE_NO_GATES` | 否 | `false` | 跳过 Gate 体系 (3 级收敛) |
| `AE_MAX_ITERATIONS` | 否 | `20` | Orchestrator 最大迭代步数 |
| `AE_LLM_PROVIDER` | 否 | `anthropic` | 仅 `anthropic` 实装，其他保留 |
| `AE_PROJECT_ROOT` | 否 | `cwd` | 项目根目录 (绝对路径) |
| `AE_INIT_MANIFEST` | 否 | `./init-manifest.json` | init-manifest 路径 |

### 3.1 必需环境设置

```bash
# ~/.zshrc 或 ~/.bashrc
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# 可选优化
export AE_LOG_LEVEL=INFO
export AE_GATE_TIMEOUT=300
```

### 3.2 验证环境

```bash
.venv/bin/ae doctor
# 期望: status=ok, 所有 checks.ok=true
```

---

## 4. 监控与可观测性

### 4.1 日志

- **引擎日志**：`AE_LOG_LEVEL=DEBUG` 时输出 per-task 详细日志
- **Plugin Hook 日志**：`~/.claude/logs/` 下查看
- **Checkpoint 历史**：`ae status --verbose` 看 recent_history × 5

### 4.2 关键指标

| 指标 | 来源 | 监控方式 |
|------|------|----------|
| dev-loop 收敛率 | AE 历史 | `.ae-state/checkpoints.db` SQL 聚合 |
| 单 Stage 平均时长 | `state.stage_started_at` | `ae status --json` |
| Gate 失败率 | `state.gate_results` | `ae status --json` |
| 连续 MAJOR 次数 | `state.majors_in_a_row` | `ae status --json` |
| Checkpoint 数 | `state.checkpoint_count` | `ae status` |

### 4.3 SQL 监控示例

```bash
# 列出最近 10 个 checkpoint
sqlite3 .ae-state/checkpoints.db \
  "SELECT checkpoint_id, stage, created_at FROM checkpoints ORDER BY created_at DESC LIMIT 10"

# 计算平均收敛轮数
sqlite3 .ae-state/checkpoints.db \
  "SELECT AVG(round_index) FROM checkpoints WHERE status='APPROVE'"
```

---

## 5. 降级路径 (v5.0 §B13)

Auto-Engineering v5.0 内置 3 类降级，按严重度排序：

### 5.1 CoverageGate 永远 skip (v5.0 §B6.4 决策)

**触发**：默认情况下 `CoverageGate.run()` 直接返回 `SKIP`。
**原因**：coverage instrumentation 内存叠加 ~2x，在 16G 物理内存下频繁跑测试会爆。
**绕过**：用户主动用 `ae gate-check --all` 时才会跑 coverage。

```python
# auto_engineering/gates/coverage.py
async def run(self, state: EngineState) -> GateResult:
    # v5.0 §B6.4: 永远 skip, 防止 pytest + coverage 内存爆
    return GateResult(self.name, GateVerdict.SKIP, "coverage disabled by default")
```

### 5.2 SemanticEvaluator 不可用 → 3 级收敛 (v5.0 §B6.5)

**触发**：`SemanticEvaluator` 初始化失败（LLM 不可达 / 缺 API key / 异常）。
**降级**：`loop.convergence` 切换到 3 级收敛（gate PASS / no-gates / max-round / stop），跳过 LLM 评估。
**影响**：仅影响 "语义收敛" 判定，不影响 Gate 体系与 Stage 状态机。

```python
# auto_engineering/loop/convergence.py
if not semantic_evaluator.is_available():
    logger.warning("SemanticEvaluator unavailable, fallback to 3-level convergence")
    return self._three_level_check(state)
```

### 5.3 Gate 工具缺失 → skip (v5.0 §B6.2)

**触发**：Gate 检测到工具缺失（如 `ruff` 未安装 → `LintGate` 不可用）。
**降级**：返回 `GateVerdict.SKIP`，不阻塞 Stage 推进。
**影响**：用户需自行保证工具链完整，否则跳过该 Gate。

| Gate | 缺失时行为 | 建议 |
|------|-----------|------|
| `LintGate` | skip | `pip install ruff` |
| `TypeCheckGate` | skip | `pip install mypy` |
| `TestGate` | skip | `pip install pytest` |
| `CoverageGate` | **永远 skip** | 不需操作 |
| `SafetyGate` | skip | `pip install bandit` |
| `BuildGate` | skip | 检查 build_cmd 配置 |
| `ContractGate` | skip | 检查 init-manifest.json |

### 5.4 LLM 不可用 → 重试 + 退出码 1

**触发**：`AnthropicProvider.create_message` 连续 3 次失败（`LLM_MAX_RETRIES`）。
**影响**：`ae dev-loop` 退出码 1，未写 checkpoint。
**恢复**：检查网络 / API key / API 限额后重试。

### 5.5 Checkpoint DB 损坏 → 重建

**触发**：`CHECKPOINT_LOAD_FAILED` 异常。
**降级**：`Orchestrator.resume()` 失败，提示用户从更早 checkpoint 恢复或重新启动 dev-loop。
**恢复**：
```bash
# 列出有效 checkpoint
.venv/bin/ae checkpoint list

# 删损坏 checkpoint
.venv/bin/ae checkpoint delete <bad-id>

# 重新启动
.venv/bin/ae dev-loop "..."
```

---

## 6. 升级与回滚

### 6.1 升级 Plugin

```bash
# 1. 备份当前 Plugin
cp -r .claude-plugin .claude-plugin.bak.$(date +%Y%m%d)

# 2. 拷贝新版
cp -r /path/to/auto-engineering-v5.x/.claude-plugin ./

# 3. 同步 Python 依赖（可能有新版 deps）
uv sync

# 4. 验证
.venv/bin/ae doctor
bash ae-plugin-acceptance-test.sh    # 18 场景

# 5. 重启 Claude Code
```

### 6.2 回滚

```bash
# 1. 恢复旧 Plugin
rm -rf .claude-plugin
mv .claude-plugin.bak.<date> .claude-plugin

# 2. 恢复依赖
git checkout pyproject.toml uv.lock
uv sync

# 3. 重启 Claude Code
```

### 6.3 Checkpoint 兼容性

- v5.0 → v5.x：兼容（`schema_version=1`）
- v2.0 JSON → v5.0 SQLite：自动迁移 (`CheckpointMigrator`)
- v1.0 JSON → v5.0：需手动 export/import

---

## 7. 安全检查清单

部署前逐项确认：

- [ ] `ANTHROPIC_API_KEY` 已设且未硬编码
- [ ] `ae doctor` 全 `ok`
- [ ] Plugin Hooks `chmod +x` 全部就绪
- [ ] pre-tool.sh denylist 已激活 (13 模式)
- [ ] `.ae-state/` 在 `.gitignore` 中
- [ ] `.venv/` 在 `.gitignore` 中
- [ ] `init-manifest.json` 在项目根且 schema_version=1
- [ ] `bash ae-plugin-acceptance-test.sh` 18/18 PASS
- [ ] `pytest tests/ --no-cov --timeout=300 -q` 全 PASS

---

## 8. 引用

- `docs/PLUGIN-USAGE.md` — 安装/命令/Troubleshooting
- `docs/api-reference.md` — 完整接口文档
- `docs/e2e-real-run.md` — 端到端流程 + 性能基准
- `docs/EARS-v5.0.md` — 15 AC + 5 IL-AC 验收
- `design/BEACON.md` 决策 #28 · `design/v5.0-Design-Loop.md` §B13 降级
- `.claude/rules/pytest-memory-management.md` — 16G 内存约束

---

_v1.0 / v2.0 部署流程已删除。归档版本见 `_scratch/his_bak/production-deployment.md`。_
