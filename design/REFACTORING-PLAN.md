# Init Engineering v5.1 改造计划（深度版）

> 制定日期：2026-06-30 | 版本：v5.1-deep-iter4 | 状态：待评审

---

## 文档目的

本计划基于 `design/v5.0-Design-Init.md`（设计文档）和 `auto_engineering/` 代码库（实现代码），逐模块分析现状与设计差距，给出可交付 atdo 推进的具体任务清单。

**深度版新增**：本版本针对上一版本的遗漏进行深度审查，补充了测试覆盖率目标、版本一致性、验收标准、隐含依赖、模块间调用链等系统性分析。

---

## Step 0: 已知未解决问题（在开始改造前必须明确）

以下问题在设计文档和代码库中均未解决，可能影响改造方向：

### Q-A: `_ae_version` 版本三元不一致

| 来源 | 值 | 备注 |
|------|---|------|
| `auto_engineering/__init__.py` | `"0.1.0"` | 包版本，CLI `--version` 输出 |
| `auto_engineering/init/answers.py` BUILTIN_VARS | `"1.0.0"` | 模板引擎版本，写入 .ae-answers.yml |
| 设计文档 header (v5.0-Design-Init.md) | `"1.0.0"` | ✅ 与代码一致 |
| 设计文档 §5.1 BUILTIN_VARS 示例 | `"5.0.0"` | ⚠️ **设计文档内部矛盾**，应以 header 为准 |

**本计划修正**:
- §5.1 的 `"5.0.0"` 是**设计文档的笔误**，header 的 `"1.0.0"` 才是正确承诺
- `__version__`（0.1.0）和 `_ae_version`（1.0.0）是**不同语义**：包版本 vs 模板引擎版本，无需统一值
- T3-1 改为：在 `answers.py` 和 `__init__.py` 中添加语义注释，澄清两者关系

### Q-B: 设计文档 Section 17（测试策略）完全无覆盖

设计文档 Section 17 要求 "tests/ 下测试，覆盖率 ≥ 80%"，当前 `test_init_core_coverage.py` 是空框架文件（仅含 import + 类骨架，无实际断言）。

**建议**: 补充测试覆盖率改造任务（T-TEST 阶段）

### Q-C: skill.py 的 `_parse_prompt()` 不支持 `--templates-suffix` 和 `--preserve-symlinks`

当前 Skill 入口的 `inputs` 定义中不包含这两个参数。如果 T2-1/T2-2 完成后要暴露到 CLI，则 skill.py 的 `_parse_prompt()` 也需要更新解析逻辑。

**建议**: T2-1/T2-2 完成后检查 skill.py 是否需要同步更新

---

## Step 1: 设计 ↔ 代码映射总表（16个模块）

| # | 模块 | 设计章节 | 代码文件 | 对应状态 | 关键发现 |
|---|------|---------|---------|---------|---------|
| 1 | InitWorker 编排器 | §2, §2.1 | `scaffold_phases.py` | ✅ 基本一致 | 状态机完整，project_type 路径穿越防护已实现 |
| 2 | TemplateRenderer | §7 | `renderer.py` | ⚠️ 需改造 | `templates_suffix`/`preserve_symlinks` 硬编码不可配置 |
| 3 | AnswersMap | §5 | `answers.py` | ✅ 基本一致 | 需补充版本语义注释（T3-1），非代码改造 |
| 4 | ProjectDetector | §4 | `detector.py` | ✅ 一致 | ADVANCED_CHECKS 完整 |
| 5 | InteractivePrompt | §6 | `prompts.py` | ✅ 一致 | secret/multiselect/placeholder 已实现 |
| 6 | TaskRunner | §6 | `hooks.py` | ✅ 一致 | 300s 超时保护 |
| 7 | 错误体系 | §9 | `init/errors.py` | ✅ 一致 | 8 种错误 + exit_code 完整 |
| 8 | 配置加载 | §6 | `config_loader.py` + `config.py` + `config_types.py` | ✅ 一致 | `!include` realpath 防护已实现 |
| 9 | ProjectEnvironment | §10 | `config/environment.py` | ✅ 基本一致 | `preflight()`/`load_ae_answers()` 已实现但文档未记录 |
| 10 | CLI/Skill 入口 | §11 | `skill.py` + `cli/__init__.py` | ✅ 基本一致 | skill.py 解析能力有限（Q-C） |
| 11 | Skill 标准结构 | §12 | `SKILL.md` | ✅ 一致 | 已创建 207 行 |
| 12 | 模板文件 | §3, §14 | `init/templates/` | ⚠️ 部分实现 | `_features/` 5/10，`_shared/` 多2个 |
| 13 | exclude 回调 | §12 | `init/_shared/exclude.py` | ✅ 一致 | `parse_exclude_callback` 已实现 |
| 14 | 测试覆盖率 | §17 | `tests/` | 🔴 需改造 | §17.2 关键测试用例未逐条覆盖 |
| 15 | AnswersMap 层数 | §5, §14 | `answers.py` | ✅ 实际够用 | Copier 额外2层在本项目无实际用途，6层已足够 |
| 16 | run_update() | §2.3, §16 | `scaffold_phases.py` | 🔴 缺失 | §2.3 明确标 P1: 缺失，计划原标 P3 偏低 |

---

## Step 2: 隐含依赖链分析（关键补充）

当前计划的 Step 3 只列出了 T2-1~T2-5 的内部依赖。以下是**模块间隐含依赖链**，这些决定了改造顺序：

```
调用链（从上到下）:
cli/__init__.py (Click CLI)
  └─ skill.py (Agent Skill 入口)
       └─ InitWorker (scaffold_phases.py)
            ├─ ProjectDetector.detect()  [模块4]
            ├─ TemplateConfig.load()      [模块8]
            ├─ InteractivePrompt          [模块5]
            ├─ scaffold_render.render_to() [模块2核心]
            │    └─ TemplateRenderer.render_to()  [模块2]
            │         ├─ TemplateRenderer.__init__  ← T2-1, T2-2 改造点
            │         └─ match_exclude 回调          [模块13]
            ├─ TaskRunner.run()           [模块6]
            └─ merge_incremental()       [scaffold_hooks.py]
                 └─ run_builtin_hooks()  [scaffold_hooks.py]

config_loader.py
  └─ TemplateConfig (dataclass)  [模块8]
       └─ templates_suffix 属性  ← T2-4 验证点
```

**关键隐含依赖**：
1. T2-3 依赖 scaffold_render.render_to() 签名扩展，这需要 InitWorker._phase_render() 的调用也相应更新（T2-5）
2. TemplateConfig.templates_suffix 已经在 config_loader.py 填充，但 scaffold_render.render_to() 没有参数接收它（T2-4）
3. skill.py 的 inputs 定义（YAML frontmatter）如果不更新，Claude Code agent 就不知道新增的参数（Q-C）
4. T16-2（run_update）依赖 scaffold_phases.py 扩展，如果决定实现，会影响 `_phase_render()` 的调用方式

---

## 模块 1: InitWorker 编排器（scaffold_phases.py + scaffold_hooks.py）

### 现状

**scaffold_phases.py（296行）**：
- `execute()` — 86行主入口，协调5阶段
- `_phase_detect()` — 目录状态检测 + 自动/交互项目类型检测
- `_phase_prompt()` — 加载模板 + 注入 CLI overrides + 交互问答
- `_phase_render(tmpdir)` — 调用 scaffold_render.render_to()
- `_phase_tasks(tmpdir)` — TaskRunner + 内置钩子
- `_phase_finalize(tmpdir, generated)` — 写入 `.ae-answers.yml` + 增量/全量 copytree

**scaffold_hooks.py（131行）**：
- `run_builtin_hooks(answers, tmpdir)` — git init → install → lefthook → git add+commit
- `merge_incremental(tmpdir, dst_path, created_files)` — 增量合并核心

**关键实现细节（当前计划未覆盖）**：
- `_phase_finalize()` 第154-159行有 project_type 路径穿越防护（正则 `^[A-Za-z0-9_-]+$`）✅
- `replay_dir = Path.home() / ".ae-replays" / raw_type` — replay 文件保存逻辑
- `run_builtin_hooks()` 中 git init 有 `-b main` 分支 fallback（git < 2.28 兼容）✅
- git add/commit 失败为非阻塞 warning（第76-92行）✅
- `merge_incremental()` 跳过 `.git/` 目录（第119行）✅

**§2.2 状态机映射**：设计文档 §2.2 描述 `InitWorker` 内部状态机（`_mode: "fresh" | "incremental"`），该逻辑在 `execute()` 和 `_phase_detect()` 中实现，与 Step 1 映射表中的模块1对应。无需独立改造任务。

### 设计差距

无实质代码差距。以下为文档/分析遗漏：
- 设计文档 Section 8（存量项目只增不改）未详细描述 `run_builtin_hooks()` 的行为
- `merge_incremental()` 未在 Step 1 映射表中单独标注（属于 scaffold_hooks.py，在模块1中包含）

### 改造步骤

**无代码改造步骤。** 以下为验证性任务（在 P1 阶段执行）：

- [ ] **T1-VERIFY-A**: 验证 `execute()` 在增量模式下的文件跳过行为（已有 `merge_incremental()` 实现）
- [ ] **T1-VERIFY-B**: 验证 `run_builtin_hooks()` 的 git fallback 逻辑在 git < 2.28 时正常工作
- [ ] **T1-VERIFY-C**: 验证 `project_type` 正则防护 `^[A-Za-z0-9_-]+$` 在 `_phase_finalize()` 中有效（已在代码中确认）

---

## 模块 2: TemplateRenderer（renderer.py）

### 现状

**完整调用链**:
```
InitWorker._phase_render()
  └─ scaffold_render.render_to()  [当前缺失 templates_suffix/preserve_symlinks]
       └─ TemplateRenderer.__init__()
            └─ TemplateRenderer.render_to()
```

**renderer.py（219行）** 关键实现：
- `TEMPLATE_SUFFIX = ".jinja"` — 硬编码（第47行）
- `preserve_symlinks` 行为：第125-134行内联实现（无参数）
- 路径穿越防护：第101-109行（os.path.realpath 双侧归一化）
- `match_exclude` 回调：第70行存储，第189行调用
- symlink 处理：第126-134行（target 存在则保留 symlink，否则跳过）

**scaffold_render.py（167行）** `render_to()` 函数：
- 签名（第99-110行）：`answers, folder_name, template_dir, subdirectory, exclude, skip_if_exists, no_render, envops, overwrite, tmpdir, exclude_callback`
- **缺失参数**：`templates_suffix`（YAML 已定义但未传递）、`preserve_symlinks`（无对应参数）

### 设计差距

| 差距项 | 设计承诺（§14） | 实际代码 | 后果 |
|--------|---------|---------|------|
| `templates_suffix` 可配置 | §14：仅 YAML 可配（CLI/InitWorker 层不可传），P2 gap | `scaffold_render.render_to()` 未接收，未传递 | **T2-4/T2-5 将扩展为 CLI 层也可传**，完成后需更新 §14 对比表 |
| `preserve_symlinks` 可配置 | §14：仅 TemplateRenderer 硬编码，CLI/InitWorker 层不可传，P2 gap | 硬编码 `True` 在 `render_to()` 内联逻辑中 | **T2-2/T2-3 将使 preserve_symlinks 可配置**，完成后需更新 §14 对比表 |

**安全分析**：路径穿越防护已实现在 `render_to()` 内（第101-109行），不是独立方法。这是设计文档 Round 7 已修正的内容，不需再改。

### 改造步骤（4个原子任务）

- [ ] **T2-1**: `TemplateRenderer.__init__` 添加 `templates_suffix: str = ".jinja"` 参数，存储为实例属性，替代现有的类属性 `TEMPLATE_SUFFIX`
- [ ] **T2-2**: `TemplateRenderer.__init__` 添加 `preserve_symlinks: bool = True` 参数，使 symlink 处理逻辑可配置
- [ ] **T2-3**: `TemplateRenderer.render_to()` 内联逻辑（第126-134行）读取 `self.preserve_symlinks` 替代硬编码 `True`
- [ ] **T2-4**: `scaffold_render.render_to()` 函数签名添加 `templates_suffix: str = ".jinja"` 和 `preserve_symlinks: bool = True` 参数，从 `template_config.templates_suffix` 读取并传递给 `TemplateRenderer`
- [ ] **T2-5**: `InitWorker._phase_render()` 调用 `scaffold_render.render_to()` 时，确认 `self._template.templates_suffix` 被传递（验证 T2-4 的端到端链路）

**验收标准**（统一格式）:
- T2-1: 单元测试 — `TemplateRenderer(templates_suffix=".j2")` 实例渲染时读取 `.j2` 文件（引用 renderer.py:47）
- T2-2: 单元测试 — `preserve_symlinks=False` 时 dangling symlink 被跳过而非创建（引用 renderer.py:126-134）
- T2-3: 依赖 T2-2，共用同一验收标准
- T2-4: 集成测试 — 创建带 `_templates_suffix: ".tmpl"` 的测试模板，验证渲染时使用 `.tmpl` 后缀
- T2-5: 集成测试 — 验证默认 `.jinja` 后缀仍然正常工作

**依赖关系**:
```
T2-1 (独立)
T2-2 (独立，可与 T2-1 并行)
T2-3 (依赖 T2-2)
T2-4 (依赖 T2-1, T2-3)
T2-5 (依赖 T2-4)
```

---

## 模块 3: AnswersMap（answers.py）

### 现状

**answers.py（257行）** 关键实现：
- `BUILTIN_VARS` — 7个内置变量，`_ae_version: "1.0.0"`（第17行）
- `_LazyExternalDict` — 懒加载外部数据，sandbox 检查（第53-115行）
- `hide(key)` — 标记字段不写入 `.ae-answers.yml`（第200-202行）
- `save_partial()` — Ctrl-C 中断恢复（第204-216行）

**版本语义澄清**（Q-A 已修正）:
- `__version__`（`__init__.py`）：CLI 包版本 = `0.1.0`
- `_ae_version`（`answers.py BUILTIN_VARS`）：模板引擎版本 = `1.0.0`，写入 `.ae-answers.yml` 元数据
- 设计文档 §5.1 承诺的是 `_ae_version = "1.0.0"`，与代码一致 ✅
- **两者语义不同，不是错误**，只需在代码中加注释澄清

### 设计差距

| 差距项 | 影响 | 严重度 |
|--------|------|--------|
| `_ae_version` 语义不清 | `__version__`（包版本）与 `_ae_version`（模板引擎版本）语义不同，但无注释说明，易导致误解 | 🟡 中（本计划已澄清） |
| `hide()` 和 `secret_questions` 的关系 | `config.py` 第90行定义 `secret_questions` list，但 `hide()` 需手动调用，不自动应用 | 🟡 中 |

### 改造步骤

- [ ] **T3-1**（P1）: 澄清 `_ae_version` 的语义并更新代码注释：
  - `_ae_version`（模板引擎内部版本，用于 .ae-answers.yml 元数据）= 设计文档 §5.1 承诺的 `1.0.0`，保持不变
  - `__version__`（CLI/Skill 包版本）= `0.1.0`，保持不变
  - **两个版本语义不同，无需统一**
  - 在 `answers.py` 的 `BUILTIN_VARS` 注释中注明：`_ae_version` 是模板引擎版本，与包版本 `__version__` 不同
  - 在 `__init__.py` 的 `__version__` 注释中注明：这是包版本，用于 CLI `--version` 输出
- [ ] **T3-2**（P2，观察）: 验证 `secret_questions` 列表是否自动调用 `answers.hide()`，还是需要手动处理（如果未自动调用，则需要改造）

**验收标准**:
- T3-1: `answers.py` 和 `__init__.py` 中的版本变量有清晰的语义注释，说明 `_ae_version`（模板引擎版本）与 `__version__`（包版本）的区别
- T3-2: 带 `secret: true` 的 Question 在 `.ae-answers.yml` 中不出现（已通过 `hide()` 标记）

---

## 模块 4: ProjectDetector（detector.py）

### 现状

**detector.py（88行）**:
- `FRAMEWORK_SIGNATURES` — 8类型签名（顺序重要，monorepo 最前）
- `ADVANCED_CHECKS` — mcp-server 和 cli-tool 的二次校验
- `_signature_matches()` — 支持目录签名 `/`、glob 通配符、普通文件

### 设计差距

无实质差距。

### 改造步骤

无改造步骤。

**验证任务**:
- [ ] **T4-VERIFY**: 运行 `pytest tests/test_init.py -k detector` 或手动测试，验证 monorepo 优先检测逻辑（FRAMEWORK_SIGNATURES 顺序）

---

## 模块 5: InteractivePrompt（prompts.py）

### 现状

**prompts.py（231行）**:
- 两遍循环（简单类型 → 复杂类型）
- `_PROMPT_DISPATCH` — 7种问题类型映射到 click 方法
- `secret` → `click.prompt(hide_input=True)` ✅
- `multiselect` → choice 类型支持多选（代码未明确实现，需要确认）
- `placeholder` → 占位文本支持（click.prompt 默认支持）

**关键未知**：当前 `multiselect` 在代码中是否实际支持多选（choice 类型 + `multiselect: true`）？需要实际验证。

### 设计差距

| 差距项 | 需要确认 |
|--------|---------|
| `multiselect` 多选 | choice 类型 + `multiselect: true` 时 click.Choice 是否支持多选？需要验证 `click.Choice` 本身不支持多选（这是 click 的限制） |

### 改造步骤

- [ ] **T5-VERIFY**: 实际运行带 `multiselect: true` 的 choice question，验证是否支持多选
  1. 创建临时测试模板：`/tmp/ae-test-multiselect/ae-template.yml`，含一个 `multiselect: true` + `type: choice` 的 Question
  2. 运行 `ae init /tmp/ae-test-multiselect-test --template /tmp/ae-test-multiselect` 并观察 click.Choice 是否支持多选输入（click.Choice 本身不支持多选，需自定义 prompt）
  3. `grep -n "multiselect\|choice\|click.Choice" prompts.py` 确认当前实现状态
  4. 如果不支持：标注为 P2 改造项（需要自定义多选 prompt，click.Choice 不支持多选）
  5. 清理：`rm -rf /tmp/ae-test-multiselect /tmp/ae-test-multiselect-test`

---

## 模块 6: TaskRunner（hooks.py）

### 现状

**hooks.py（86行）**:
- `TaskRunner.__init__(project_dir, current_phase)`
- `run(tasks, context, jinja_env)` — 执行任务列表
- `extra_vars` 双注入：`_{key}` → Jinja渲染变量，`{KEY}` → 环境变量
- `AE_PHASE` 环境变量传入 ✅
- 300秒超时保护 ✅
- `cmd` 为 `list[str]` 时 `shell=False`（安全），`str` 时 `shell=True`

### 设计差距

无实质差距。

### 改造步骤

无改造步骤。

**验证任务**:
- [ ] **T6-VERIFY**: 测试 `list[str]` cmd 执行时无 shell 注入风险（grep 确认 `subprocess.run` 使用 `shell=False`）

---

## 模块 7: 错误体系（init/errors.py）

### 现状

**errors.py（69行）** 8种错误类全部实现：

| 错误类 | exit_code | 实现状态 |
|--------|---------|---------|
| `InitError` | 1 | ✅ |
| `ConfigFileError` | 2 | ✅ |
| `UnsatisfiedPrerequisiteError` | 3 | ✅ |
| `TargetDirectoryError` | 4 | ✅ |
| `ValidationError` | 5 | ✅ |
| `TaskExecutionError` | 6 | ✅ (含 command/returncode/stderr) |
| `TemplateRenderError` | 7 | ✅ (含 src_path/jinja_error/line_number) |
| `InitInterruptedError` | 130 | ✅ |

### 设计差距

无实质差距。

### 改造步骤

无改造步骤。

---

## 模块 8: 配置加载（config_loader.py + config.py + config_types.py）

### 现状

**config_loader.py（194行）**:
- `load_template_config()` — 完整解析流程
- `!include` realpath 防护 ✅（第104-121行）
- `_parse_questions()` — 映射 YAML 到 Question dataclass
- `_parse_tasks()` — 分离 tasks_before/tasks_after

**config.py（109行）**:
- `TemplateConfig` dataclass（58-97行）
- `templates_suffix` 属性 ✅（YAML `_templates_suffix` 已映射）
- `exclude_callback` string spec ✅
- `envops` ✅
- `secret_questions` list ✅

**config_types.py（147行）**:
- `Question` dataclass — 含 `secret`/`multiselect`/`placeholder` ✅
- `Task` dataclass ✅
- `DEFAULT_EXCLUDE` ✅

### 设计差距

无实质差距。配置加载是设计-实现最一致的模块。

### 改造步骤

无改造步骤。

**验证任务**:
- [ ] **T8-VERIFY**: 验证 `!include ../../../etc/passwd` 会被 realpath 检查拒绝（安全测试）

---

## 模块 9: ProjectEnvironment（config/environment.py）

### 现状

**environment.py（242行）**:
- `ProjectEnvironment.resolve()` — 加载 + 自检测合并
- `preflight()` — 前置校验（Python ≥ 3.12、API key、git、磁盘空间）
- `load_ae_answers()` — 低级加载函数

**设计文档遗漏**（已在模块8中记录）：
- `preflight()` 和 `load_ae_answers()` 代码已实现但设计文档 Section 10 未描述

### 设计差距

文档层面的差距（非代码差距）：
- `preflight()` 和 `load_ae_answers()` 未写入设计文档

### 改造步骤

无代码改造。（设计文档补充任务已标注为"不执行"）

---

## 模块 10: CLI/Skill 入口（cli/__init__.py + skill.py）

### 现状

**cli/__init__.py（165行）**:
- 11个选项全部实现 ✅
- `--analyze` 模式完整 ✅
- `--pretend` 模式完整 ✅

**skill.py（223行）**:
- `_parse_prompt()` 支持 `init/analyze/detect` 三种格式
- 不支持 `--templates-suffix` 和 `--preserve-symlinks`（Q-C）

### 设计差距

| 差距项 | 当前状态 | 影响 |
|--------|---------|------|
| skill.py 不支持 `templates_suffix` 参数 | 不支持 | 如果用户通过 Skill 调用想传此参数，无法解析 |
| skill.py 不支持 `preserve_symlinks` 参数 | 不支持 | 同上 |

**分析**：当前 CLI 层（Click）和 Skill 层（skill.py）都没有暴露 `templates_suffix` 和 `preserve_symlinks` 的选项。这不是"bug"，而是设计选择——这两个参数原本只能通过 YAML 模板配置。

### 改造步骤

- [ ] **T10-VERIFY**: 确认 `templates_suffix` 和 `preserve_symlinks` 是否应该暴露到 CLI（由产品决策决定，不是技术问题）

---

## 模块 11: Skill 标准结构（SKILL.md）

### 现状

`SKILL.md` 已创建（207行），符合 Claude Code Skill 标准格式。

### 设计差距

无实质差距。

### 改造步骤

无改造步骤。

---

## 模块 12: 模板文件（init/templates/）

### 现状

```
init/templates/
├── _shared/           7项：CLAUDE.md, LICENSE, README, design/, .gitignore, .editorconfig, .claude/
├── _features/         5项：bash, go, python, rust, typescript
└── 8项目类型目录     全部存在（ae-template.yml + 模板文件）
```

### 设计差距

| 差距项 | 状态 |
|--------|------|
| `_features/` 10个模块 | 只有5个（bash/go/python/rust/typescript，剩余为 P2/P3 未来项） |
| `_shared/.gitignore.jinja` | ✅ 存在（设计文档未记录） |
| `_shared/.editorconfig.jinja` | ✅ 存在（设计文档未记录） |

### §3 模板目录结构核对（验证任务）

- [ ] **T12-VERIFY**: 核对 `init/templates/` 实际文件与设计文档 §3 描述是否一致：
  - `_shared/` 实际文件数（设计文档说7项）
  - `_features/` 实际子目录数（设计文档说10个，但只有5个实现）
  - 8个项目类型目录是否全部存在 ae-template.yml
  - 如果实际与设计不符，更新设计文档 §3 或补充任务修复

### 改造步骤

无代码改造。（T12-VERIFY 完成后根据结果决定是否需要设计文档更新任务）

---

## 模块 13: exclude 回调（init/_shared/exclude.py）

### 现状

**exclude.py（90行）**:
- `default_match_exclude(path)` — 排除 `.git/`/`__pycache__/`/`node_modules/`/`.DS_Store`/`.env`/`*.pyc`
- `parse_exclude_callback(spec)` — 解析 `"module:function"` spec

### 设计差距

无实质差距。

### 改造步骤

无改造步骤。

---

## 模块 14: 测试覆盖率（设计文档 Section 17）

### 现状

**设计要求**：tests/ 下测试，覆盖率 ≥ 80%

**当前测试文件**：
```
tests/
├── conftest.py              # pytest 配置 + fixtures
├── test_answers.py          # AnswersMap 单元测试
├── test_environment.py      # ProjectEnvironment 测试
├── test_error_codes.py      # 错误码测试
├── test_init_config_loader.py # 配置加载测试
├── test_init_core_coverage.py # ⭐ 覆盖率测试（空框架，仅导入+类骨架）
├── test_init_design_docs.py  # 设计文档一致性测试
├── test_init_e2e_scaffold.py # 端到端测试
├── test_init.py             # init 核心测试
└── test_settings.py         # 设置测试
```

**问题**：`test_init_core_coverage.py` 是覆盖率目标框架，但只有类骨架无实际断言。当前真实覆盖率未知。

### 设计差距

| 差距项 | 严重度 |
|--------|--------|
| 覆盖率目标无测量 | 🔴 高（目标存在但无测量） |
| 关键模块无单元测试 | 🟡 中（如 `merge_incremental()`、`run_builtin_hooks()`） |
| E2E 测试覆盖范围未知 | 🟡 中 |
| §17.2 关键测试用例未逐条覆盖 | 🟡 中（路径穿越、条件渲染、冲突处理、增量模式、中断恢复） |

### §17.2 关键测试用例覆盖映射

| 测试用例（§17.2） | 当前覆盖状态 | 需补充任务 |
|-------------------|------------|-----------|
| 路径穿越（project_type=../../etc） | 待 TTEST-1 测量确认 | TTEST-COVER-PATH |
| 条件渲染（when={{ false }}） | 待 TTEST-1 测量确认 | TTEST-COVER-CONDITIONAL |
| 文件冲突-overwrite | 待 TTEST-1 测量确认 | TTEST-COVER-CONFLICT-OVERWRITE |
| 文件冲突-skip | 待 TTEST-1 测量确认 | TTEST-COVER-CONFLICT-SKIP |
| 外部数据-合法（sandbox内） | 待 TTEST-1 测量确认 | TTEST-COVER-EXTERNAL-VALID |
| 外部数据-非法（指向/etc/passwd） | 待 TTEST-1 测量确认 | TTEST-COVER-EXTERNAL-INVALID |
| 增量-已存在文件跳过 | 待 TTEST-1 测量确认 | TTEST-COVER-INCREMENTAL |
| 中断恢复（Ctrl-C → --from-answers） | 待 TTEST-1 测量确认 | TTEST-COVER-PARTIAL |

### 改造步骤

- [ ] **TTEST-1**（P1）: 运行 `pytest --cov=auto_engineering --cov-report=term-missing` 测量当前覆盖率基线
- [ ] **TTEST-2**（P1）: 基于 TTEST-1 结果，补充缺失测试用例（优先级：renderer > answers > hooks > scaffold_phases）
- [ ] **TTEST-COVER**（P2）: 逐条实现 §17.2 关键测试用例覆盖映射表中的 8 个测试
- [ ] **TTEST-3**（P2）: 达到 Section 17 要求的 ≥ 80% 覆盖率目标

**验收标准**:
- TTEST-1: 获得覆盖率报告，明确当前覆盖率数值
- TTEST-2: 每个 P1 改造模块（T2、T3）配套单元测试
- TTEST-COVER: §17.2 中 8 个关键测试用例全部有对应测试函数
- TTEST-3: 全量测试覆盖率 ≥ 80%

---

## 模块 15: AnswersMap 层数差异（answers.py）

### 现状

**设计承诺**：§14 业界对比明确写"AnswersMap 层数：8层 ChainMap（Copier），v5.1 init：6层 ChainMap，差距 P2"

**实际实现**：answers.py 只有 6 层
```
优先级 (高 → 低):
  1. cli_overrides
  2. interactive
  3. previous
  4. defaults
  5. builtins
  6. external
```

**Copier 8层**（§14 引用）：
```
1. cli_overrides
2. interactive
3. previous
4. defaults
5. builtins
6. external
7. unused_imports（Copier 特有）
8. data（Copier 特有）
```

### 设计差距

| 差距项 | 设计承诺 | 实际代码 | 后果 |
|--------|---------|---------|------|
| AnswersMap 层数 | 8层（Copier），P2 gap | 6层 | 缺少 Copier 的 2 个内部层 |

**初步分析**（未经代码验证）：
- Copier 的 `unused_imports` 层：VCS 克隆后自动移除未使用的 imports，InitWorker 无 VCS 支持
- Copier 的 `data` 层：VCS 克隆后检测数据文件变更，InitWorker 无此场景
- 当前 6 层已覆盖所有必要场景

### 改造步骤

- [ ] **T15-VERIFY**（P2）: 读取 `$AE_REFS_DIR/copier/copier/_user_data.py` 源码中 Copier 的 8 层 ChainMap 定义，交叉验证 `unused_imports` 和 `data` 层在 AE 场景的实际用途
  1. `grep -n "ChainMap\|unused_imports\|data" $AE_REFS_DIR/copier/copier/_user_data.py` 定位 Copier 8 层定义
  2. 分析 `unused_imports` 层：在 Copier 中用于什么？InitWorker 有无相同场景？
  3. 分析 `data` 层：在 Copier 中用于什么？InitWorker 有无相同场景？
  4. **形成结论**：如果两层均无意义 → 在 §14 对比表加注"此 gap 在 AE 不适用"；如果有意义 → 补充实现方案

**验收标准**:
- T15-VERIFY: 引用 Copier 源码（文件路径+行号）证明结论有据，附两种场景的处理决策

---

## 模块 16: run_update()（scaffold_phases.py + scaffold.py）

### 现状

**设计文档 §2.3 Copier对照表 row 290**：
```
run_update(): 不支持 | P1: 缺失
```

§16 表格也明确写道：
```
run_update() | Worker.run_update() | P1 | 需实现差异检测 + migration_tasks
```

**设计文档 §2 流水线图**也标注了 `run_update()` 为可选功能。

### 设计差距

| 差距项 | 设计承诺 | 实际代码 | 后果 |
|--------|---------|---------|------|
| `run_update()` | §2.3 和 §16 均标 P1: 缺失 | 完全未实现 | 用户无法更新已有项目，只能重新初始化 |

**Copier 参考**（$AE_REFS_DIR/copier/）：
- `Worker.run_update()` — 检测模板变更，对比渲染差异，执行 migration_tasks
- 支持 `before_migration` 和 `after_migration` 钩子
- 实现难度：需要模板差异检测 + 增量任务执行

### 改造步骤

- [ ] **T16-1**（P1）: 研究 Copier `run_update()` 实现，确定 AE 差异化设计方向
  1. `grep -n "run_update\|update\|migration" $AE_REFS_DIR/copier/copier/worker.py` 定位 Copier run_update 相关代码
  2. 读取 `$AE_REFS_DIR/copier/copier/worker.py` 中 `run_update()` 方法（约 ~50 行）
  3. 分析 AE update 场景：与 Copier VCS 场景的本质差异（AE 无 git clone，模板由本地 YAML 驱动）
  4. 输出：设计决策文档（实现或不实现 + 引用 Copier 源码行号说明理由）
- [ ] **T16-2**（P2，结果驱动）: 基于 T16-1 设计决策
  - **如果 T16-1 决定实现**：需实现 `_phase_update()` 方法 + migration_tasks 支持，输出可工作的 `run_update()` 功能
  - **如果 T16-1 决定不实现**：需在设计文档 §13 "不做的事"中明确标注 `run_update()` 为"未来可选"，并在 §2.3 对照表中更新状态

**验收标准**:
- T16-1: 有明确的设计决策（实现或不实现，并引用 Copier 源码说明理由）
- T16-2: **结果驱动** — 如果实现，则 `run_update()` 可工作；如果放弃，则 §13 已更新

**风险**：
- 🟡 中等风险：`run_update()` 涉及模板差异检测，实现复杂度高
- 可能与增量模式（incremental）功能重叠，需先明确边界

---

## Step 3: 完整任务依赖图（含新增任务）

### P1 阶段（必须完成，阻断后续）

| 任务ID | 模块 | 任务描述 | 验收标准 | 依赖前置 |
|--------|------|---------|---------|---------|
| **T2-1** | TemplateRenderer | 添加 `templates_suffix` 参数 | 单元测试：`.j2` 文件被渲染（引用 renderer.py:47） | 无 |
| **T2-2** | TemplateRenderer | 添加 `preserve_symlinks` 参数 | 单元测试：`preserve_symlinks=False` 时 dangling symlink 被跳过 | 无（可并行） |
| **T2-3** | TemplateRenderer | `render_to()` 读取 `self.preserve_symlinks` | 依赖 T2-2，共用同一验收标准 | T2-2 |
| **T2-4** | scaffold_render | `render_to()` 签名扩展 + 透传参数 | 集成测试：自定义后缀模板渲染成功 | T2-1, T2-3 |
| **T2-5** | scaffold_phases | `InitWorker._phase_render()` 透传 `templates_suffix` | 集成测试：默认 `.jinja` 后缀仍正常工作 | T2-4 |
| **T3-1** | AnswersMap | 澄清版本语义，添加代码注释 | `answers.py` 和 `__init__.py` 注释清晰说明两个版本的语义差异 | 无 |
| **T16-1** | run_update | 研究 Copier run_update()（读 $AE_REFS_DIR/copier/copier/worker.py），输出设计决策文档 | 输出设计决策文档（实现或不实现 + 引用 Copier 源码行号说明理由） | 无 |
| **TTEST-1** | 测试 | 测量当前覆盖率基线 | 获得覆盖率数值 | 无 |
| **TTEST-2** | 测试 | 补充 T2 改造的单元测试 | T2 配套测试存在且通过 | T2-1, T2-2, T2-3, T2-4, T2-5 全部完成 |

### P2 阶段（T2/T3 完成后执行）

| 任务ID | 模块 | 任务描述 | 验收标准 | 依赖前置 |
|--------|------|---------|---------|---------|
| **T3-2** | AnswersMap | 验证 `secret_questions` 自动调用 `hide()` | 带 `secret: true` 的答案不写入 `.ae-answers.yml` | T3-1 |
| **T5-VERIFY** | InteractivePrompt | 验证 `multiselect` 多选支持 | 确认多选是否工作或标记为缺失 | 无 |
| **T12-VERIFY** | 模板文件 | 核对 §3 模板目录结构与实际文件 | 设计文档与实际一致或有明确说明 | 无 |
| **T15-VERIFY** | AnswersMap | 确认 Copier 额外2层在本项目无实际用途 | 形成结论：6层已足够 | 无 |
| **T16-2** | run_update | 基于 T16-1 决策实现 run_update() 或明确放弃 | §13 更新或功能实现 | T16-1 |
| **TTEST-COVER** | 测试 | 实现 §17.2 关键测试用例覆盖 | 8个关键用例全部有对应测试 | TTEST-1 |
| **TTEST-3** | 测试 | 达到 ≥ 80% 覆盖率 | 覆盖率报告 ≥ 80% | TTEST-2 |

### P3 阶段（可选/未来项）

| 任务ID | 模块 | 任务描述 | 依赖前置 |
|--------|------|---------|---------|
| T11-1 | 设计文档 | 更新 Section 3 描述（_features/ 实际数量） | 无 |
| T10-VERIFY | CLI/Skill | 确认 templates_suffix/preserve_symlinks 是否暴露到 CLI | T2-4 |
| T16-3 | run_update | 如果 T16-2 决定实现，完成完整的 run_update() 功能 | T16-2 |

---

## Step 4: 改造优先级汇总表

| 任务ID | 阶段 | 风险等级 | 阻塞后续 | 说明 |
|--------|------|---------|---------|------|
| T2-1 | **P1** | 🟡 中 | ✅ 是 | 添加参数是简单扩展 |
| T2-2 | **P1** | 🟡 中 | ✅ 是 | 同上 |
| T2-3 | **P1** | 🟢 低 | ✅ 是 | 逻辑替换（硬编码→实例属性） |
| T2-4 | **P1** | 🟡 中 | ✅ 是 | 函数签名扩展，需同步调用方 |
| T2-5 | **P1** | 🟢 低 | ✅ 是 | 验证端到端链路 |
| T3-1 | **P1** | 🟢 低 | ❌ 否 | 纯文档/注释澄清，非代码改造 |
| T16-1 | **P1** | 🟡 中 | ✅ 是 | 研究决策，不阻塞 T2，但影响 T16-2 方向 |
| TTEST-1 | **P1** | 🟢 低 | ✅ 是 | 提供覆盖率基线 |
| TTEST-2 | **P1** | 🟢 低 | ❌ 否 | 依赖 T2 完成 |
| T16-2 | P2 | 🟡 中 | ❌ 否 | 依赖 T16-1 设计决策 |
| T3-2 | P2 | 🟢 低 | ❌ 否 | 可观察，不阻塞 |
| T5-VERIFY | P2 | 🟢 低 | ❌ 否 | 验证性任务 |
| T12-VERIFY | P2 | 🟢 低 | ❌ 否 | 验证 §3 与实际一致性 |
| T15-VERIFY | P2 | 🟢 低 | ❌ 否 | 确认 6层够用 |
| TTEST-COVER | P2 | 🟡 中 | ❌ 否 | 8个关键用例逐条覆盖 |
| TTEST-3 | P2 | 🟡 中 | ❌ 否 | 覆盖率目标 |
| T11-1 | P2 | 🟢 低 | ❌ 否 | 仅文档更新 |
| T10-VERIFY | P2 | 🟢 低 | ❌ 否 | 决策性验证 |
| T16-3 | P3 | 🟡 中 | ❌ 否 | run_update 完整实现 |

---

## Step 5: atdo 可执行的任务清单

### P1 阶段 — 可立即并行执行

```
[01] T2-1: TemplateRenderer 添加 templates_suffix 参数
[02] T2-2: TemplateRenderer 添加 preserve_symlinks 参数
[03] T3-1: 澄清 _ae_version vs __version__ 语义（注释）
[04] TTEST-1: pytest --cov 测量当前覆盖率基线
[05] T16-1: 研究 Copier run_update()，输出设计决策文档

[06] T2-3: render_to() 读取 self.preserve_symlinks（依赖 [02]）
[07] TTEST-2: 补充 T2 改造的单元测试（依赖 [01],[02],[04],[05] 全部完成）

完整依赖链:
  [01] T2-1 + [02] T2-2（并行）
         ↓
  [06] T2-3（依赖 [02]）
         ↓
  [04] T2-4（依赖 [01],[06]）
         ↓
  [05] T2-5（依赖 [04]）
         ↓
  [07] TTEST-2（依赖 [01],[02],[04],[05]）
```

### P2 阶段（T2/T3 完成后执行）

```
[08] T16-2: 基于 T16-1 决策实现或放弃 run_update()
[09] T3-2: 验证 secret_questions 自动调用 hide()
[10] T5-VERIFY: 验证 multiselect 多选支持
[11] T12-VERIFY: 核对 §3 模板目录与实际一致性
[12] T15-VERIFY: 确认 Copier 额外2层无实际用途（引用源码）
[13] TTEST-COVER: §17.2 八个关键测试用例逐条覆盖
[14] TTEST-3: 达到 ≥ 80% 覆盖率
```

### P3 阶段（可选/未来项）

```
[15] T11-1: 更新设计文档 §3（_features/ 实际数量）
[16] T10-VERIFY: 决策 templates_suffix/preserve_symlinks 是否暴露 CLI
[17] T16-3: run_update 完整实现（依赖 T16-2 决策）
```

### 验证任务（可独立运行，无需依赖）

```
[V1] T1-VERIFY-A: 验证增量模式文件跳过行为
[V2] T1-VERIFY-B: 验证 git fallback 逻辑
[V3] T4-VERIFY: 验证 monorepo 优先检测
[V4] T6-VERIFY: 验证 shell=False 安全
[V5] T8-VERIFY: 验证 !include realpath 防护
```

---

## 结论

### 核心发现

1. **P1 改造任务涉及 3 个模块**（TemplateRenderer + AnswersMap + run_update研究方向），共 7 个原子任务（T2-1~T2-5 + T3-1 + T16-1），T2 系列可完全并行执行

2. **测试覆盖率是被完全遗漏的改造维度**（Section 17），需要在 P1 阶段并行启动覆盖率测量；§17.2 的 8 个关键测试用例需要逐条覆盖（新增 TTEST-COVER）

3. **版本问题（Q-A）已重新评估**：
   - §5.1 中的 `_ae_version: "5.0.0"` 是**设计文档内部笔误**
   - 设计文档 header 承诺 `_ae_version: 1.0.0`，与代码一致 ✅
   - `__version__`（0.1.0，包版本）和 `_ae_version`（1.0.0，模板引擎版本）是**不同语义**，T3-1 改为澄清语义并添加注释

4. **Skill.py 的参数解析能力**（Q-C）在 T2 完成后需要评估是否暴露新参数

5. **模块间调用链清晰**，无循环依赖，P1 任务可以完全并行执行

6. **§14 与 T2-4/T2-5 设计意图澄清**：§14 说 templates_suffix "仅 YAML 可配"，T2-4/T2-5 扩展了 CLI 层传递。完成后需同步更新 §14 对比表。

7. **run_update() 被低估为 P3**：设计文档 §2.3 和 §16 均明确标 P1: 缺失，这是计划的严重低估。已升级为 T16-1（P1研究方向）+ T16-2（P2实现）

8. **§2.2 状态机**：在模块1中补充映射说明

9. **§3 模板目录**：新增 T12-VERIFY 核对任务

10. **AnswersMap 层数**（模块15）：§14 说差2层，但 Copier 的 `unused_imports` 和 `data` 层在 AE 场景无实际用途，6层已足够；T15-VERIFY 已明确引用 `$AE_REFS_DIR/copier/copier/_user_data.py` 源码验证

12. **T16-1 研究路径已明确**：引用 `$AE_REFS_DIR/copier/copier/worker.py` 具体文件，输出需包含 Copier 源码行号

13. **设计文档内部矛盾**：§5.1 BUILTIN_VARS 示例写 `_ae_version: "5.0.0"`，但设计文档 header 写 `1.0.0`，两者互相矛盾。本计划以 header 为准（1.0.0）

### 当前可立即开始的任务（无需等待）

```
# P1 并行执行（[01]-[05]）
T2-1 + T2-2 + T3-1 + TTEST-1 + T16-1（研究方向）
```

---

_文档版本: v5.1-deep-iter4 | 创建: 2026-06-30 | 变更: TTEST-2依赖链补全(T2-4,T2-5)、T5-VERIFY第1步加临时模板路径+清理步骤、结论编号修正(10/11/12)_
