# Phase 50 Codex Migration Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让当前设计、规则、代码、配置、文档、CI 与 Claude Code/Codex 双宿主能力完全一致，同时保留可追溯的历史设计资产。

**Architecture:** 保持 Host-neutral Tick Core 不变，将平台差异收敛到 Host Adapter、规则模板、manifest、Skill/Hook 和 Packaging。当前资产与历史资产物理分层，契约测试负责阻断规则、文档、配置和发布包再次漂移。

**Tech Stack:** Python 3.12、Click、pytest、Ruff、mypy、uv、GitHub Actions、Markdown、JSON manifest、Shell CLI resolver。

---

## 文件职责与变更地图

| 文件/目录 | 职责 |
|---|---|
| `design/BEACON.md` | 80 行以内的当前目标、有效决策和状态 |
| `design/IMPLEMENTATION-TRACKER.md` | Phase 50 当前任务及历史 Phase 索引 |
| `design/archive/INDEX.md` | 历史决策与旧规格导航 |
| `design/archive/decisions/` | 从 BEACON 迁出的历史决策正文 |
| `design/archive/legacy/` | 旧 Standalone/Provider/CodeBuddy 规格 |
| `agent-rules/*.tmpl` | Claude/Codex 项目规则 SSOT |
| `auto_engineering/host/` | Host Adapter 静态契约与平台实现 |
| `.claude-plugin/`, `.codex-plugin/` | 平台 manifest |
| `scripts/check_*.py` | 规则、metadata、host package 确定性检查 |
| `scripts/install_acceptance.py` | Release 解压目录双宿主自动验收 |
| `README.md`, `docs/*.md` | 当前用户能力文档 |

### Task 1: Phase 50 落表

**Files:**
- Modify: `design/IMPLEMENTATION-TRACKER.md`
- Modify: `design/BEACON.md`

- [ ] **Step 1: 在 Tracker 新增 Phase 50 的 8 个任务**

新增 T233–T240：

```text
T233 CI 与测试真实性
T234 跨 Agent 规则收口
T235 Host Adapter 契约收敛
T236 manifest/依赖/配置 SSOT
T237 Release 验收分层
T238 设计资产归档与 BEACON 压缩
T239 当前用户文档重写
T240 全量验收与状态收口
```

- [ ] **Step 2: 将 Phase 50 标为进行中**

BEACON 仅增加“Phase 50 设计已确认、T233 进行中”，不翻转任何既有 ✅/❌ 决策。

- [ ] **Step 3: 校验状态记录**

Run:

```bash
rg -n "Phase 50|T233|T240|◐" design/BEACON.md design/IMPLEMENTATION-TRACKER.md
```

Expected: Phase 50 与 8 个任务可定位，只有 T233 为进行中。

### Task 2: 修复 CI Ruff 与测试自动跳过

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/e2e/test_cli_roundtrip.py`
- Modify: `tests/test_checkpoint_migrate.py`
- Modify: `tests/test_context_summarization.py`
- Modify: `tests/test_doctor.py`
- Modify: `tests/test_gate_ts_support.py`
- Modify: `tests/test_git_utils.py`
- Modify: `tests/test_loop_round_extended.py`
- Modify: `tests/test_loop_state_d_fields.py`
- Modify: `tests/test_plugin_contract.py`
- Modify: `tests/test_task_factory.py`
- Test: `tests/test_test_infrastructure.py`

- [ ] **Step 1: 写失败测试**

新增：

```python
def test_failure_history_never_adds_skip_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest, "_FAILURE_CACHE", tmp_path / "failures.json")
    conftest._write_failures({"tests/test_demo.py::test_demo": 3})
    item = FakeItem("tests/test_demo.py::test_demo")
    conftest.pytest_collection_modifyitems(None, [item])
    assert item.markers == []
```

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_test_infrastructure.py -v --no-cov --timeout=60
```

Expected: FAIL，现有 hook 添加 skip marker。

- [ ] **Step 3: 删除自动 skip，只保留诊断报告**

`pytest_collection_modifyitems` 可输出失败历史，但不得调用 `item.add_marker(skip_marker)`。
保留 `_reset_block_cache` 兼容 fixture，避免扩大测试改动。

- [ ] **Step 4: 修复 Ruff 的 15 条现有问题**

只调整 import 顺序、删除未使用 import、将未使用变量改为 `_stdout`；不改测试行为。

- [ ] **Step 5: 验证 GREEN**

Run:

```bash
uv run pytest tests/test_test_infrastructure.py -v --no-cov --timeout=60
uv run ruff check .
```

Expected: 新测试通过；Ruff `All checks passed!`。

### Task 3: 收口跨 Agent 规则

**Files:**
- Modify: `agent-rules/instructions.md.tmpl`
- Modify: `agent-rules/claude.md.tmpl`
- Modify: `agent-rules/codex.md.tmpl`
- Regenerate: `CLAUDE.md`
- Regenerate: `AGENTS.md`
- Modify: `tests/test_sync_agent_instructions.py`

- [ ] **Step 1: 写规则防漂移测试**

断言公共模板和两个生成文件均不包含：

```python
RETIRED_COMMANDS = (
    "ae gate-check",
    "ae agent architect",
    "ae progress",
    'ae dev-loop "需求"',
    "1702 passed",
    "~1703 tests",
)
```

并断言存在 `scripts/ae-run doctor`、`scripts/ae-run status --format json` 与
`[tool.auto-engineering.baseline]`。

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_sync_agent_instructions.py -v --no-cov --timeout=60
```

Expected: FAIL，命中退役命令或旧基线。

- [ ] **Step 3: 更新公共模板并生成规则**

Run:

```bash
python3 scripts/sync_agent_instructions.py
python3 scripts/sync_agent_instructions.py --check
```

Expected: AGENTS.md/CLAUDE.md 生成成功且无漂移。

- [ ] **Step 4: 验证 GREEN**

Run:

```bash
uv run pytest tests/test_sync_agent_instructions.py -v --no-cov --timeout=60
```

Expected: 全部通过。

### Task 4: 补齐 Host Adapter 契约

**Files:**
- Modify: `auto_engineering/host/__init__.py`
- Create: `auto_engineering/host/adapters.py`
- Modify: `auto_engineering/host/codex_hooks.py`
- Test: `tests/test_host_adapter.py`

- [ ] **Step 1: 写失败契约测试**

测试 Claude/Codex Adapter 均提供：

```python
adapter.platform
adapter.capabilities
adapter.normalize_event(event)
adapter.resolve_cli(plugin_root)
adapter.usage_source(project_root)
```

并断言 Codex usage source 为 `None`、Claude 为 `claude-transcript/anthropic`。

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_host_adapter.py -v --no-cov --timeout=60
```

Expected: FAIL，当前没有具体 Adapter 实现。

- [ ] **Step 3: 实现最小 Adapter**

`adapters.py` 提供 `ClaudeCodeAdapter`、`CodexAdapter` 和
`adapter_for(platform)`；CLI 解析只返回候选命令，不执行 subprocess。
Codex event 复用现有 `normalize_codex_event`，Claude 不支持的原始事件返回 `None`。

- [ ] **Step 4: 验证 GREEN 与 Core 依赖方向**

Run:

```bash
uv run pytest tests/test_host_adapter.py tests/test_codex_hooks.py -v --no-cov --timeout=60
! rg -n "host\\.adapters|codex_hooks|claude" auto_engineering/loop auto_engineering/gates
```

Expected: 测试通过；Core 不反向 import Adapter。

### Task 5: 收敛 manifest、依赖和配置 SSOT

**Files:**
- Modify: `pyproject.toml`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.codex-plugin/plugin.json`
- Modify: `scripts/check_project_metadata.py`
- Test: `tests/test_project_metadata.py`
- Test: `tests/test_v8_platform.py`

- [ ] **Step 1: 写失败 metadata 测试**

断言：

```python
assert "v5.0" not in project_description
assert "anthropic" not in required_dependencies
assert "commands" not in codex_manifest
assert not codex_manifest["author"]["email"].endswith("@anthropic.com")
assert declared_ae_env_keys <= feature_manifest_keys | credential_keys
```

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_project_metadata.py tests/test_v8_platform.py -v --no-cov --timeout=60
```

Expected: FAIL，命中旧描述、强制依赖、Codex commands 或死环境变量。

- [ ] **Step 3: 最小清理**

- 包描述更新为 v5.6 Host-neutral Core。
- `anthropic` 移到 `anthropic` 可选 extra。
- Claude manifest 环境变量只保留有消费者且默认值一致的项目。
- Codex manifest 删除 `commands`，作者仅保留姓名或中性邮箱。

- [ ] **Step 4: 验证安装组合**

Run:

```bash
uv sync
uv sync --extra anthropic
uv run pytest tests/test_project_metadata.py tests/test_v8_platform.py -v --no-cov --timeout=60
```

Expected: 基础安装和可选 Anthropic 安装成功；测试通过。

### Task 6: 强化 Release 验收分层

**Files:**
- Modify: `scripts/check_host_package.py`
- Modify: `scripts/install_acceptance.py`
- Modify: `tests/test_release_package.py`
- Modify: `tests/test_codex_integration.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: 写失败验收测试**

断言验收结果明确包含：

```json
{
  "automated": "passed",
  "product_install": "not_run",
  "host": "codex"
}
```

同时验证 manifest 引用路径、Hook handler、Skill 入口、规则同步、doctor 和 Tick。

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_release_package.py tests/test_codex_integration.py -v --no-cov --timeout=60
```

Expected: FAIL，当前脚本只输出文本 OK，未区分自动验收与产品安装。

- [ ] **Step 3: 实现结构化验收结果**

CLI 默认打印 JSON；`product_install` 在没有真实 Codex 安装接口时固定为
`not_run`，并附中文原因。CI 对 `automated != passed` 失败。

- [ ] **Step 4: 双宿主真实压缩包 smoke**

Run:

```bash
archive="$(mktemp -t ae-phase50-XXXXXX.tar.gz)"
uv run python scripts/build_release.py --root . --output "$archive"
uv run python scripts/install_acceptance.py --archive "$archive" --host claude-code
uv run python scripts/install_acceptance.py --archive "$archive" --host codex
```

Expected: 两次 `automated=passed`；Codex `product_install=not_run`。

### Task 7: 设计资产归档与 BEACON 压缩

**Files:**
- Create: `design/archive/INDEX.md`
- Create: `design/archive/decisions/BEACON-HISTORY.md`
- Create: `design/archive/legacy/README.md`
- Modify: `design/BEACON.md`
- Modify: `design/IMPLEMENTATION-TRACKER.md`
- Modify: `design/INDEX.md`
- Test: `tests/test_documentation_contract.py`

- [ ] **Step 1: 写失败设计资产测试**

```python
def test_beacon_is_a_compact_current_state_file():
    lines = BEACON.read_text().splitlines()
    assert len(lines) <= 80
    assert "Phase 50" in BEACON.read_text()

def test_archive_index_preserves_decision_navigation():
    assert "决策 #1-#101" in ARCHIVE_INDEX.read_text()
```

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_documentation_contract.py -v --no-cov --timeout=60
```

Expected: FAIL，BEACON 超过 80 行且 archive 索引不存在。

- [ ] **Step 3: 迁移历史并压缩当前文件**

保留有效决策 #97–#101 摘要；#1–#96 正文迁入历史决策文件。Tracker 顶部保留
Phase 50 与 Phase 49 摘要，其余历史表通过 archive 索引访问。不得删除原决策编号、
日期和状态。

- [ ] **Step 4: 验证链接和行数**

Run:

```bash
uv run pytest tests/test_documentation_contract.py -v --no-cov --timeout=60
test "$(wc -l < design/BEACON.md)" -le 80
rg -n "决策 #1-#101|Phase 50" design/archive/INDEX.md design/BEACON.md
```

Expected: 测试通过，历史导航完整。

### Task 8: 重写当前用户文档

**Files:**
- Modify: `README.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `docs/api-reference.md`
- Modify: `docs/PRODUCT-TRAINING-GUIDE.md`
- Test: `tests/test_documentation_contract.py`

- [ ] **Step 1: 扩展失败文档测试**

对每份当前文档的 current section 断言不含：

```python
RETIRED_CLAIMS = (
    "//ae:dev-loop",
    "Standalone 模式",
    "多 Provider 支持",
    "AE_CACHE_CONTROL",
    "CodeBuddy Plugin",
    "v7.0 双驱动",
)
```

允许归档链接标题出现历史关键词，但不得包含可复制的旧命令。

- [ ] **Step 2: 验证 RED**

Run:

```bash
uv run pytest tests/test_documentation_contract.py -v --no-cov --timeout=60
```

Expected: FAIL，命中 USER_GUIDE/API/培训手册残留。

- [ ] **Step 3: 重写当前内容**

四份文档统一：

- Claude Code：`/ae:dev-loop`
- Codex：`$auto-engineering`
- 共享 resolver：`scripts/ae-run`
- 当前能力：Tick、Gate、Checkpoint、Host Adapter
- 历史能力：仅链接 `design/archive/INDEX.md`

- [ ] **Step 4: 验证 GREEN**

Run:

```bash
uv run pytest tests/test_documentation_contract.py -v --no-cov --timeout=60
```

Expected: 当前文档契约全部通过。

### Task 9: 全量验收与 Phase 50 收口

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `design/BEACON.md`
- Modify: `design/IMPLEMENTATION-TRACKER.md`

- [ ] **Step 1: 运行生成和 metadata 门禁**

```bash
python3 scripts/sync_agent_instructions.py --check
uv run python scripts/check_project_metadata.py
git diff --check
```

Expected: 全部退出 0。

- [ ] **Step 2: 运行静态门禁**

```bash
uv run ruff check .
uv run mypy auto_engineering
```

Expected: Ruff 零错误；mypy 99+ 源文件零错误。

- [ ] **Step 3: 运行全量测试**

```bash
state_dir="$(mktemp -d)"
AE_TEST_STATE_DIR="$state_dir" uv run pytest tests/ --no-cov --timeout=120 -q
```

Expected: 零失败；仅保留有明确原因的静态 skip。

- [ ] **Step 4: 运行覆盖率门禁**

```bash
state_dir="$(mktemp -d)"
AE_TEST_STATE_DIR="$state_dir" uv run pytest tests/ \
  --cov=auto_engineering --cov-report=term-missing \
  --cov-fail-under=90 --timeout=300 -q
```

Expected: 覆盖率 ≥90%，退出 0。

- [ ] **Step 5: 更新 SSOT 基线和状态**

以 Step 3 的新鲜结果更新：

- `pyproject.toml [tool.auto-engineering.baseline]`
- README test-baseline
- BEACON 项目规模与验证证据
- Tracker T233–T240 状态

Phase 50 只有在 Step 1–4 全部通过后才能标为完成。

- [ ] **Step 6: 最终敏感信息和差异审查**

```bash
git diff --check
git status --short
git diff --stat
```

Expected: 差异全部可追溯到 Phase 50；无 `.env`、凭据、私钥或生产数据。

> Git 提交不属于本计划自动步骤。只有用户后续明确要求 `commit` 时，才按
> Conventional Commits 创建提交；本计划不 push、不发布。

