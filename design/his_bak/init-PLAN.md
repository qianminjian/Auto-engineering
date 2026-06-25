# init 子系统断路修复执行计划

> 创建：2026-06-24 | 来源：`design/v1.0-INIT.md` §1.7 实现偏差审计 + §1.8 待办 + §二 实施计划
> 关联：`design/BEACON.md` — 当前阶段指针

---

## 背景

`ae init` 的设计骨架正确（B+），但实现保真度约 60%。编排器 `scaffold.py` 是偏差集中的模块。审计发现 21 个偏差项，按优先级分四档。

**参考源码**：Copier `_main.py`（Worker 全生命周期）、Cookiecutter `main.py`/`generate.py`/`prompt.py`、Yeoman `router.js`（composeWith 模式）

---

## Phase 4.1：断路修复（P0 — 3 项，~1h）

> 这 3 项阻塞了 init 的真实场景使用，必须最先修复。

### R1：`_phase_render` 多层模板目录组合

- **偏差**：G1 — 只传 `[self._template.template_dir]` 单目录
- **影响**：`_shared/` 和 `_features/` 下的模板永不生成，项目骨架不完整
- **文件**：`auto_engineering/init/scaffold.py` `_phase_render` 方法（L188-196）
- **改动**：将单目录替换为设计文档 §1.3.8 的 `_build_template_dirs()` 逻辑（~40 行）
  ```
  template_dirs = [TEMPLATES_ROOT / "_shared"]
  → 语言 feature（typescript/python/go/rust/bash）
  → 基础设施 feature（lefthook/github-actions/gitlab-ci/docker/monorepo）
  → 类型模板（type_dir，含 subdirectory 处理）
  ```
- **验证**：`ae init test-project --type app-service --defaults` 输出含 CLAUDE.md、.gitignore、README.md、LICENSE 等共享文件

### R2：`--from-answers` previous 层注入

- **偏差**：G2 — `_phase_prompt` 构造 AnswersMap 时未传 `previous=`
- **影响**：`ae init --from-answers .ae-answers.yml` 加载的答案不生效
- **文件**：`auto_engineering/init/scaffold.py` `_phase_prompt` 方法（L176-179）
- **改动**：AnswersMap 构造增加 `previous=self._previous_answers`（~1 行）
  ```python
  self._answers = AnswersMap(
      defaults={q.var_name: q.default for q in self._template.questions},
      cli_overrides=cli_overrides,
      previous=self._previous_answers or {},  # ← 新增
  )
  ```
- **验证**：先生成项目保存 `.ae-answers.yml`，再用 `ae init test2 --from-answers .ae-answers.yml --defaults` 重放

### R3：路径穿越防护

- **偏差**：G3 — 设计未提及，实现无检查
- **影响**：恶意模板可通过 `../` 注入写入临时目录外文件
- **文件**：`auto_engineering/init/renderer.py` `render_to` 方法（L90 附近）
- **改动**：在 `dst_file = dst_dir / rendered_rel` 后增加检查（~5 行）
  ```python
  dst_file = dst_dir / rendered_rel
  dst_real = dst_file.resolve()
  if not dst_real.is_relative_to(dst_dir.resolve()):
      raise TemplateRenderError(str(src_file), ValueError("路径穿越"))
  ```
- **验证**：构造一个包含 `../../etc/passwd` 路径的模板，确认抛出异常

---

## Phase 4.2：行为纠正（P1 — 8 项，~2h）

> 功能逻辑不符设计预期，但不阻塞基本流程。

### R4：`_run_builtin_hooks` 错误传播

- **偏差**：G4 — 全部 `check=False` 静默失败
- **设计**：§1.3.8 每个步骤检查 returncode，失败 raise TaskExecutionError
- **文件**：`auto_engineering/init/scaffold.py` `_run_builtin_hooks`（L206-220）
- **改动**：每步 subprocess.run 后检查 result.returncode != 0 → raise TaskExecutionError（~20 行）
  - git init 失败 → raise
  - pm install 失败 → raise
  - lefthook install 失败 → raise
  - git add 失败 → raise
  - git commit 失败 → 警告（非阻塞：可能无文件变更）

### R5：git init 分支回退兼容

- **偏差**：G5 — 只试 `git init -b main`
- **设计**：§1.3.8 先试 `-b main`，不支持则回退 `git init`
- **改动**：检查 stderr 中是否有 "unknown option"，有则重试无 -b 的 git init（~10 行）

### R6：`_check_prerequisites` 跨平台

- **偏差**：G6 — `subprocess.run(["which", cmd])`
- **设计**：§1.3.8 标注用 `shutil.which`
- **改动**：`shutil.which(cmd) is None` 替代 subprocess 检查（~3 行）

### R7：`__exit__` 始终清理

- **偏差**：G7 — 仅在 `exc_val is not None` 时清理
- **参考**：Copier Worker 始终执行 `_cleanup()`
- **改动**：移除 `if exc_val is not None` 条件（~3 行）

### R8：`envops`/`no_render`/`subdirectory` 传入 TemplateRenderer

- **偏差**：G8 — 字段在 config.py 中已解析，但 scaffold.py 未传递
- **改动**：`_phase_render` 中 TemplateRenderer 构造增加 `envops=self._template.envops`、`no_render=self._template.no_render`、`subdirectory` 用于目录选择（~5 行）

### R9：`external_data` 注入 AnswersMap

- **偏差**：G19 — `TemplateConfig.external_data` 已解析但 AnswersMap 未接收
- **改动**：`_phase_prompt` 中 AnswersMap 构造增加 `external=self._template.external_data`（~3 行）

### R10：`message_before`/`message_after` 渲染前后提示

- **偏差**：G18 — 字段已定义但未在 phase 中调用
- **改动**：`_phase_render` 前打印 `message_before`，`_phase_tasks` 后打印 `message_after`（~4 行）

### R11：Jinja2 `StrictUndefined`

- **偏差**：G15 — 使用默认 `Undefined`，未定义变量静默变空字符串
- **参考**：Copier `_user_data.py` 使用 `jinja2.StrictUndefined`
- **改动**：renderer.py 和 prompts.py 的 Jinja2 环境构造增加 `undefined=jinja2.StrictUndefined`（~2 行）

---

## Phase 4.3：健壮性增强（P2 — 7 项，~3h）

> 边缘场景和跨平台兼容性，不影响核心流程。

### R12+R16：`pathspec` 替代 `fnmatch`

- **偏差**：G13 — `fnmatch` 不支持 `.gitignore` 语义（`**/pattern` 等）
- **参考**：Copier `_path_matcher` + `pathspec.GitWildMatchPattern`
- **文件**：`auto_engineering/init/renderer.py`
- **改动**：添加 pathspec 依赖；`_is_excluded` 改用 `GitWildMatchPattern`；新建 `_path_matcher` 方法（~20 行）

### R13：模板上下文内置变量补充

- **偏差**：G11 — 仅 `_ae_version`
- **参考**：Copier `_render_context()` — `_folder_name`, `sep`, `os`, `_copier_python`
- **文件**：`auto_engineering/init/answers.py` `BUILTIN_VARS`
- **改动**：增加 `_folder_name`/`_ae_python`/`sep`/`os` 四个变量（~10 行）
  - `_folder_name`: 目标目录名
  - `_ae_python`: `sys.executable`
  - `sep`: `os.sep`
  - `os`: `"linux"`/`"macos"`/`"windows"`

### R14：Cookiecutter replay 自动保存

- **偏差**：G14 — 正常生成不保存答案副本，无法跨会话重放
- **参考**：Cookiecutter `dump(replay_dir, template_name, context)`
- **文件**：`auto_engineering/init/scaffold.py`
- **改动**：`_phase_tasks` 结束后，将 `_answers.to_answers_file()` dump 到 `~/.ae-replays/<project_type>/<timestamp>.yml`（~15 行）

### R15：文件冲突内容比较

- **偏差**：G12 — 只检查文件是否存在，不比较内容
- **参考**：Copier `_render_allowed` + expected_contents hash
- **文件**：`auto_engineering/init/renderer.py` `_should_overwrite`
- **改动**：文件已存在时，读取前 4KB 计算 sha256，与待写入内容比较；相同则跳过（~15 行）

### R17：`_features/` ae-feature.yml 声明式配置

- **偏差**：G9+G10 — feature 是纯模板文件，无声明式配置
- **参考**：Yeoman generator 独立 lifecycle（prompts/writing/install/end）
- **文件**：`auto_engineering/init/templates/_features/*/ae-feature.yml`（新建约 6 个文件）
- **改动**：每个 feature 目录新建 `ae-feature.yml`，格式：
  ```yaml
  name: typescript
  description: TypeScript 语言支持
  when: "{{ use_typescript }}"
  questions: {}       # feature 专属问题（可选）
  tasks_after: []     # feature 专属钩子（可选）
  ```
  同时在 `_phase_render` 中读取 ae-feature.yml 判断何时激活 feature（~20 行 × 6）

### R18：symlink 处理

- **偏差**：G21 — `rglob("*")` 可能跳过或不正确处理符号链接
- **参考**：Copier `_render_symlink`
- **文件**：`auto_engineering/init/renderer.py` `render_to`
- **改动**：检测 `src_file.is_symlink()` → 使用 `shutil.copy2` 复制链接（~8 行）

---

## Phase 4.4：大功能（P3 — 3 项，~4h）

> 设计已确认但代码未开始，v1.1 排期。

### R19：增量模式（`--incremental`）

- **偏差**：G16
- **设计**：`v1.0-INIT.md` §1.3.10 — Phase 3.5 MERGE、_created_files 跟踪、错误回滚语义变更
- **文件**：`auto_engineering/init/scaffold.py` + CLI
- **改动**：
  1. InitWorker 增加 `incremental: bool` 字段
  2. `_phase_detect` 非空目录自动检测 → 提示增量模式
  3. 新建 `_phase_merge(tmpdir)` 方法：逐文件复制，跳过已存在
  4. `execute()` 中 mode 分支
  5. CLI 增加 `--incremental` flag（~150 行）

### R20：嵌套模板交互式选择

- **偏差**：G17
- **设计**：§1.3.2 `_resolve_nested_template` + Cookiecutter `choose_nested_template`
- **文件**：`auto_engineering/init/prompts.py`
- **改动**：实现 `prompt_for_nested_template`，在 `_phase_prompt` 中检测后调用（~40 行）

### R21：`_subdirectory` 支持

- **偏差**：G20
- **设计**：§1.3.2 P2#15 — TemplateConfig 已解析字段
- **文件**：`auto_engineering/init/scaffold.py` `_phase_render`
- **改动**：type_dir 使用 `self._template.template_dir / self._template.subdirectory`（~5 行）

---

## Phase 5：测试补全（与各 Phase 并行）

| # | 测试 | 覆盖 | 位置 |
|---|------|------|------|
| T1 | 多层模板目录组合集成测试 | R1 | `tests/test_init.py` |
| T2 | --from-answers 恢复 E2E | R2 | `tests/test_init.py` |
| T3 | 路径穿越防护单元测试 | R3 | `tests/test_renderer.py` |
| T4 | 内置钩子错误传播测试 | R4 | `tests/test_init.py` |
| T5 | git 分支回退兼容测试 | R5 | `tests/test_init.py` |
| T6 | 增量模式 E2E 测试 | R19 | `tests/test_init.py` |

---

## 风险与注意事项

1. **R1 改动范围最大**：`_phase_render` 从 8 行扩展到 ~50 行，注意语言 feature 映射的配置化（避免在代码中硬编码所有语言类型）
2. **R11 StrictUndefined 可能暴露现有模板 bug**：模板中引用未定义变量会从"静默过"变成"抛异常"，切换后需全量模板回归
3. **R17 ae-feature.yml 格式**：v1.0 先做最简版本（name + when + questions + tasks_after），后续可扩展
4. **R19 增量模式**：与新建模式共用 Phase 1/2/3，仅在 Phase 3.5/4/5 存在分支，架构上不冲突

---

## 验收门禁（每 Phase 完成后）

- [ ] `python -m pytest tests/ -q` 通过
- [ ] `ae init test-project --type app-service --defaults` 生成正确骨架
- [ ] `ae init test-project --type library --pretend` 预览正确
- [ ] `ae init --help` 所有 flag 正常显示
- [ ] 无 `check=False` 静默失败（除 git commit 空提交外）
- [ ] 无 `fnmatch` 残留（p1.3 后全部迁移到 pathspec）
