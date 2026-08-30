# Auto-Engineering v5.6 EARS Acceptance Criteria

> **Version**: 5.6.0 | **Status**: v5.6 验收基线 (v5.0 15 AC + v5.6 扩展) | **Last updated**: 2026-07-16
> 决策依据: `design/BEACON.md` 决策 #28, #41, #53 · `design/v5.6-Design-Loop.md` §B18 + §IL.6
> 验收人: AI 自动 + 用户手动 (EARS AC-12/14 真实环境)

**EARS 格式**: `When <trigger>, the <system> shall <response>`

> **诚实标注原则** (per Phase 11 constraints): PASS / PARTIAL / 缺 必须如实标记，禁止全部 PASS。

> **当前口径说明（D16）**：本节 IL-AC-01 是 v5.0 历史兼容基线。当前 v5.8 运行时以本地
> ProjectProfile 探测和 `ae.toml` 为默认输入，缺少 Init manifest 不再是运行时硬阻断；旧
> manifest 仍按只读兼容契约验证。

---

## 1. v5.0 15 AC 状态表 (v5.0 §B18)

| AC | 描述 | EARS | Phase 实现 | 测试覆盖 | 状态 | 备注 |
|----|------|------|-----------|---------|------|------|
| AC-01 | `/dev-loop "实现登录"` → 3 Stage + JSON 输出 | When 用户启动 `/auto-engineering:dev-loop`, the Orchestrator shall 跑完 architect→developer→critic 3 Stage 并输出 6 字段 JSON | Phase 01-11 | `test_loop_orchestrator.py` (4 测试) | **PASS** | `tests/test_loop_orchestrator.py` 验证 3 Stage 转换 + JSON 契约 |
| AC-02 | `/dev-loop "需求" --tasks FILE` → 预定义 Task | When 用户传 --tasks FILE, the Orchestrator shall 跳过 architect Stage 直接用预定义 Task DAG | Phase 03 | `test_task_factory.py` | **PASS** | `_tasks_from_batch_plan` 解析 tasks.yml + 追加 critic |
| AC-03 | critic 连续 max_majors_in_a_row 次 (默认 3, Self-Refine 原则 3) MAJOR → StageRouter should_stop=True | When critic verdict=MAJOR 连续 3 次, the StageRouter shall 设置 should_stop=True | Phase 01 | `test_stage_router.py` (T6 测试) | **PASS** | `test_stage_router.py::test_t6_two_consecutive_majors_stops` (2026-07-04: 默认值 2→3, Self-Refine 原则 3 最优) |
| AC-04 | Stage 推进后 checkpoint | When Stage 推进完成, the Orchestrator shall 写 SQLite checkpoint 含 stage + round_index | Phase 04 | `test_checkpoint_envelope.py` | **PASS** | `_save_checkpoint` 在 step 10 调用 |
| AC-05 | GitDiffExists 过滤 (post/developer) | When developer Stage 完成, the GuardrailChain shall 跑 G3 GitDiffExists 验证 diff 非空 | Phase 02 | `test_guardrail.py` | **PASS** | `test_guardrail.py::test_git_diff_exists` (新仓库降级 --cached) |
| AC-06 | `--no-gates` → 3 级收敛 | When 用户传 --no-gates, the Orchestrator shall 跳过 7 Gates 用 3 级收敛 (gate PASS / no-gates / max-round / stop) | Phase 07 | `test_plugin_contract.py` | **PASS** | `AE_NO_GATES=true` → convergence._three_level_check |
| AC-07 | LLM timeout → BaseAgent retry×3 | When AnthropicProvider 超时, the BaseAgent shall 重试 3 次后抛 LLM_MAX_RETRIES | existing | `test_anthropic_provider.py` | **PASS** | `test_anthropic_provider.py::test_timeout_retry` |
| AC-08 | checkpoint resume → retry_counters | When 用户通过 `/auto-engineering:dev-loop` 恢复, the Orchestrator shall 注入 envelope.retry_counters 到 state | Phase 04 | `test_checkpoint_envelope.py` | **PASS** | `resume()` → 重建 state + 注入 retry_counters |
| AC-09 | ANTHROPIC_API_KEY NOT_APPLICABLE | When ANTHROPIC_API_KEY 未设, Plugin 模式不报错 (SDK 自动从 env 读 key, Claude Code Agent 提供) | Phase 07+08 | `test_plugin_contract.py` | **PASS** | `test_plugin_contract.py::test_missing_api_key_exit_2` |
| AC-10 | Ctrl-C → checkpoint + exit 130 | When 用户按 Ctrl-C, the Orchestrator shall 写 interrupted checkpoint 且 exit 130 | Phase 07 | `test_plugin_contract.py` | **PASS** | `test_plugin_contract.py::test_ctrl_c_exit_130` |
| AC-11 | Plugin → Engine + Agent 展示 JSON | When Plugin 调 ae dev-loop, the Engine shall 输出 6 字段 JSON 供 Plugin 解析展示 | Phase 09 | `tests/test_plugin_contract.py` + archive smoke | **PASS** | 双宿主 archive smoke 验证最小 Tick |
| AC-12 | plugin.json → 当前发布命令注册 | When Plugin 安装到 Claude Code, the host shall 注册发布包声明的全部 slash command | Phase 09/58 | 真实产品安装 | **PASS** | Claude Code 2.1.220 user scope enabled；4 个当前命令被发现，`/auto-engineering:status` 实际调用成功。 |
| AC-13 | `ae doctor` 检查 | When 用户跑 ae doctor, the CLI shall 执行当前注册的 11 项环境检查 | Phase 07+08 | `tests/test_doctor.py` | **PASS** | atdo smoke 验证 11/11 |
| AC-14 | pre-tool hook denylist 拦截 | When Bash 命令匹配危险模式, the pre-tool.sh shall 拦截并 exit 2 | Phase 09 | `tests/test_plugin_contract.py` | **PASS** | Plugin 合同测试验证 denylist |
| AC-15 | Engine 崩溃 Plugin 优雅展示 | When Engine 异常退出, the Plugin shall 解析 stderr 输出结构化失败结果 | Phase 09 | `tests/test_install_acceptance.py` | **PASS** | 隔离安装与最小 Tick 验收 |

### 1.1 AC 状态汇总

| 状态 | 数量 | 占比 | AC 列表 |
|------|------|------|---------|
| **PASS** | 15 | 100% | AC-01/02/03/04/05/06/07/08/09/10/11/12/13/14/15 |
| **PARTIAL** | 0 | 0% | — |
| **缺** | 0 | 0% | — |

> **口径迁移**：Phase 09 的 7+1 命令描述属于历史产品面；当前发布包保留
> `audit`、`code-review`、`dev-loop`、`status` 4 个命令。Phase 58 已通过真实
> Claude Code 安装和直接命令调用关闭 AC-12，不再以已退役命令数量作为发布门。

### 1.2 AC-12 release-blocking verification (Phase 12.10)

> **release-blocking**: AC-12 是 v5.0 唯一未 PASS 的核心 AC。release 前必须由用户手动验证并标记 PASS，否则不可发布。

**当前已交付（代码层可验证）**：
- `.claude-plugin/plugin.json` 声明 commands/skills 路径
- `commands/*.md` 共 **4 文件**:
  - `audit.md` → `/auto-engineering:audit`
  - `code-review.md` → `/auto-engineering:code-review`
  - `dev-loop.md` → `/auto-engineering:dev-loop`
  - `status.md` → `/auto-engineering:status`

**真实环境复验步骤**：

```
AC-12 release-blocking verification 步骤:
1. 从 release marketplace 安装 `auto-engineering`
2. 确认 plugin 为 enabled
3. 在新 Claude Code 进程运行 `/auto-engineering:status`
4. 验证 `audit`、`code-review`、`dev-loop`、`status` 均被发现
5. 任一 command 缺失 → 检查 plugin.json commands 路径
```

**FAIL 标准**：
- 当前发布包声明的任一命令缺失 → AC-12 FAIL → 阻塞 release
- 全部当前命令可见且 `status` 可调用 → AC-12 PASS

**关联 commit**: Phase 09 commit `0664343` (plugin + commands + hooks + skills 交付)

---

## 2. v5.0 5 IL-AC 状态表 (v5.0 §IL.6)

Init-Loop 契约验收（Phase 08 实现）。

| IL-AC | 描述 | EARS | 测试覆盖 | 状态 | 备注 |
|-------|------|------|---------|------|------|
| IL-AC-01 | init-manifest 缺失 → doctor 报错 | When init-manifest.json 缺失, the ae doctor shall 报 fail | `test_init_contract.py` | **PASS** | `test_init_contract.py::test_doctor_reports_missing_manifest` |
| IL-AC-02 | conventions → Gate 配置 | When init-manifest 含 conventions, the Gate 应替换硬编码 ruff/mypy/pytest | `test_init_contract.py` | **PASS** | `test_init_contract.py::test_gates_use_manifest_config` (Phase 08 commit `a4d1bd2`) |
| IL-AC-03 | 未知字段静默忽略 | When tasks.yml 含 init_metadata, the parser shall 静默忽略 | `test_init_contract.py` | **PASS** | `test_init_contract.py::test_unknown_init_metadata_silent` (Phase 08 commit `9060519`) |
| IL-AC-04 | schema_version 太旧 → 拒绝 | When init-manifest schema_version < 1, the validate shall 拒绝 | `test_init_contract.py` | **PASS** | `test_init_contract.py::test_old_schema_version_rejected` |
| IL-AC-05 | mtime 不变 | When ae doctor 跑完, the init-manifest mtime shall 不变 | `test_init_contract.py` | **PASS** | `test_init_contract.py::test_doctor_does_not_modify_mtime` (Phase 08 commit `23d3dfa`) |

### 2.1 IL-AC 状态汇总

| 状态 | 数量 | 占比 |
|------|------|------|
| **PASS** | 5 | 100% |
| **PARTIAL** | 0 | 0% |
| **缺** | 0 | 0% |

> **5/5 IL-AC 全 PASS** — Phase 08 全部交付。

---

## 3. 验收命令汇总

```bash
# 1. 单元 + 集成测试
uv run pytest tests/ --no-cov --timeout=120 -q
# 权威数量见 pyproject.toml [tool.auto-engineering.baseline]

# 2. 双宿主 archive smoke（真实产品安装状态仍单独报告）
python3 scripts/build_release.py --root . --output _scratch/release.tar.gz
python3 scripts/install_acceptance.py --archive _scratch/release.tar.gz --host claude-code --wheel-cache "$(uv cache dir)"
python3 scripts/install_acceptance.py --archive _scratch/release.tar.gz --host codex --wheel-cache "$(uv cache dir)"

# 3. 环境自检
uv run ae doctor
# 期望: status=ok, 11 checks 全 ok

# 4. 覆盖率
uv run pytest tests/ --cov=auto_engineering --cov-report=term-missing --timeout=300 -q
# 期望: ≥ 90% (v5.6 基准, 用户硬指标)
```

---

## 4. 真实环境验收

以下场景需在真实宿主环境执行：

| 场景 | 步骤 | 期望 | 关联 AC |
|------|------|------|---------|
| **AC-12** Plugin 注册 | 安装 release，确认 enabled，在新进程调用 `/auto-engineering:status` | 4 个当前命令可见且 status 返回有效状态 | AC-12 |
| **端到端 dev-loop** | 在 Claude Code 内运行 `/auto-engineering:dev-loop "实现 hello world"` | 3 Stage + APPROVE + exit 0 + 6 字段 JSON | AC-01 |
| **Ctrl-C 优雅退出** | dev-loop 运行时按 Ctrl-C | 写 interrupted checkpoint + exit 130 | AC-10 |
| **缺 API key** | N/A — Plugin 模式 SDK 自动读 env, 不需用户设置 | AC-09 |

---

## 5. 真实安装结果

### 5.1 Phase 58 双宿主结果

- Claude Code 2.1.220：真实安装、enabled、缓存完整、宿主识别、Skill 加载及
  `/auto-engineering:status` 调用均通过。
- Codex 0.145.0：真实安装、enabled、缓存完整、安装缓存 `doctor` 通过；
  `gpt-5.6-sol` 新进程成功加载 `$auto-engineering` 并执行 status。
- 双宿主 product install 总门为 PASS。Phase 59 已修复 Codex read-only 沙箱的
  SQLite WAL/临时目录限制；v5.7.0 release 已由双宿主真实安装识别复验。

### 5.2 acceptance test 18 场景 — 15 场景待扩

**当前实装**：3 场景 (Phase 09 commit `9db22a5`)：
- 场景 1: Plugin → Engine + Agent 展示 JSON (AC-11)
- 场景 2: pre-tool hook denylist 拦截 (AC-14)
- 场景 3: Engine 崩溃 Plugin 优雅展示 (AC-15)

**待扩展**：15 场景（对应剩余 12 AC + 3 Init-Loop 边界）。Phase 11 不要求全部实装 — 仅 3 核心场景 + 用户手动验证兜底。

---

## 6. 引用

- `design/v5.6-Design-Loop.md` §B18 — 15 AC 列表
- `design/v5.6-Design-Loop.md` §IL.6 — 5 IL-AC 列表
- `tests/` — 全部测试覆盖（含 test_loop_orchestrator / test_stage_router / test_guardrail / test_plugin_contract / test_init_contract）
- `scripts/build_release.py` / `scripts/install_acceptance.py` — 双宿主 archive smoke
- `docs/api-reference.md` — 完整接口（含 19 错误码表）
- `docs/USER_GUIDE.md` §6.2 — 降级路径 / §5.6 — 错误场景

---

_Phase 11 M12 文档验收基线。后续 Phase 12+ 路线图: 扩展 acceptance test 15 场景 + Init-Loop UI 集成。_
