# Init 子系统设计审计报告

> 审计日期：2026-06-23
> 审计方式：对照 Copier/Cookiecutter/Yeoman 源码，逐模块检查设计文档的覆盖度
> 参考源码：Copier _main.py(Woker), _user_data.py(Question/AnswersMap), _template.py(Template/Task) / Cookiecutter generate.py, main.py, prompt.py, hooks.py / Yeoman routes/

---

## 审计发现（15 项）

### P0 — 设计缺口，不补会导致运行时问题

| # | 模块 | 缺口 | 参考源码 | 影响 |
|---|------|------|---------|------|
| 1 | renderer.py | 缺**二进制文件检测** — Jinja2 渲染 .png/.gif 会损坏文件 | Cookiecutter `generate.py:221` `binaryornot.check.is_binary()` | 模板中的图片/字体等二进制文件渲染后损坏 |
| 2 | renderer.py | 缺**换行符保持** — 渲染后的文件应保持原文件的换行符风格 | Cookiecutter `generate.py:241-252` 检测 `rd.newlines` | Windows 用户生成的文件换行符不一致 |
| 3 | renderer.py | 缺**文件权限保持** — 渲染后应 `shutil.copymode` | Cookiecutter `generate.py:259-260` | 可执行脚本失去 +x 权限 |
| 4 | TemplateConfig | `min_ae_version` 定义了但 **InitWorker 未调用版本兼容检查** | Copier `_template.py:130-158` `verify_copier_version()` | 旧版 ae 运行新版模板静默失败 |
| 5 | renderer.py | **Jinja2 Environment 应为 SandboxedEnvironment** — 普通 Environment 可执行任意 Python | Copier `_main.py:35` `SandboxedEnvironment` | 模板文件中的恶意 Jinja2 代码可执行系统命令 |

### P1 — 功能缺口，影响特定场景

| # | 模块 | 缺口 | 参考源码 | 建议 |
|---|------|------|---------|------|
| 6 | TemplateConfig | 缺 **`_copy_without_render`** 配置 — 标记文件不渲染只复制 | Cookiecutter `generate.py:39-56` `is_copy_only_path()` | 添加 `no_render` 列表，标记不需要 Jinja2 处理的文件 |
| 7 | TemplateConfig | 缺 **`_envops` 模板引擎选项** — 允许自定义 Jinja2 分隔符 | Copier `demo/copier.yaml:2-8` `block_start_string: "[%"` | 对使用 `{{ }}` 语法的项目（Vue/Go templates），避免与 Jinja2 冲突 |
| 8 | AnswersMap | 缺 **`external_data` 懒加载机制** — 从外部 YAML/JSON 注入数据 | Copier `_main.py:314-355` `_external_data()` + `LazyDict` | 复杂模板可从外部数据文件获取配置 |
| 9 | InitWorker | 缺 **`pretend` (dry-run) 模式** — 只模拟不写入 | Copier Worker `pretend: bool = False` | 调试模板时无法预览生成结果 |
| 10 | InitWorker | `cleanup_on_error` 应**可配置**（当前硬编码 True） | Copier Worker `cleanup_on_error: bool = True` | 用户可能想保留失败产物排查问题 |
| 11 | TemplateConfig | 缺 **`!include` YAML 标签** — 允许 ae-template.yml 拆分为多文件 | Copier `_template.py:92-106` YAML `!include` | Monorepo 等大型模板配置不便维护 |
| 12 | TemplateConfig | 缺**嵌套模板选择** — 一个类型下多个变体供选择 | Cookiecutter `main.py:144-146` `choose_nested_template()` | library 类型下 TS/Python/Go/Rust 四种变体无法通过子类型选择 |

### P2 — 增强项，当前可运行但不完善

| # | 模块 | 缺口 | 参考源码 | 建议 |
|---|------|------|---------|------|
| 13 | InitWorker | 缺 **Phase 上下文跟踪** — 下游模块不知道当前操作阶段 | Copier `_main.py:89` `ContextVar("_operation")` + `Phase.use()` | v2.0 update 功能需要区分 copy/update 操作 |
| 14 | Task 接口 | `extra_vars` **双注入未细化** — 需同时注入 Jinja 变量(`_k`)和环境变量(`K`) | Copier `_main.py:392-423` `extra_context` + `extra_env` | 钩子命令无法通过环境变量获取动态参数 |
| 15 | InitWorker | 缺**模板子目录支持** — `_subdirectory` 指定模板内的子路径 | Copier Template `_subdirectory` | 有嵌套变体的模板需要 |

---

## 逐模块对照设计文档的检查

### §16.3.2 config.py — 7 项检查

| 设计文档 | Copier 对应 | Cookiecutter 对应 | 是否缺失 |
|---------|-----------|-----------------|:---:|
| Question 数据类 | ✅ `_user_data.py:137` | ✅ `cookiecutter.json` | — |
| type 自动推导 | ✅ `_check_type` L232-236 | ❌ JSON 只有 str/bool/list/dict | — |
| cast_answer() | ✅ `CAST_STR_TO_NATIVE` | ✅ 分散在各 `read_user_*` | — |
| when 条件渲染 | ✅ `get_when()` | ❌ 不支持 | — |
| validator 校验 | ✅ `render_value(validator)` | ❌ 不支持 | — |
| **`_copy_without_render`** | ❌ 不支持 | ✅ `is_copy_only_path()` | ✅ P1#6 |
| **`_envops`** | ✅ `_envops` L2-8 | ❌ 不支持 | ✅ P1#7 |

### §16.3.3 answers.py — 3 项检查

| 设计文档 | Copier 对应 | 是否缺失 |
|---------|-----------|:---:|
| 5 层 ChainMap | ✅ 8 层 ChainMap `combined()` | — |
| hide() | ✅ `AnswersMap.hide()` L131-133 | — |
| **external_data 懒加载** | ✅ `_external_data()` + `LazyDict` | ✅ P1#8 |

### §16.3.5 renderer.py — 6 项检查

| 设计文档 | Copier 对应 | Cookiecutter 对应 | 是否缺失 |
|---------|-----------|-----------------|:---:|
| Jinja2 双层渲染 | ✅ `_render_file()` | ✅ `generate_file()` | — |
| `DEFAULT_EXCLUDE` 过滤 | ✅ `_exclude` + pathspec | ✅ `.gitignore` 风格 | — |
| 冲突处理 | ✅ `_render_allowed()` | ✅ `overwrite_if_exists` | — |
| **二进制检测** | ❌ 不处理 | ✅ `binaryornot.check.is_binary()` | ✅ P0#1 |
| **换行符保持** | ❌ 不处理 | ✅ `rd.newlines` L251 | ✅ P0#2 |
| **文件权限保持** | ❌ 不处理 | ✅ `shutil.copymode` L260 | ✅ P0#3 |

### §16.3.6 hooks.py — 2 项检查

| 设计文档 | Copier 对应 | 是否缺失 |
|---------|-----------|:---:|
| Jinja2 渲染命令 | ✅ `_render_string(task_cmd)` | — |
| working_directory | ✅ `task.working_directory` | — |
| **extra_vars 双注入** | ✅ extra_context(`_k`) + extra_env(`K`) | ✅ P2#14 |

### §16.3.8 scaffold.py — 5 项检查

| 设计文档 | Copier 对应 | 是否缺失 |
|---------|-----------|:---:|
| context manager | ✅ `__enter__`/`__exit__` | — |
| cleanup_on_error 仅删自己创建的 | ✅ L1275-1277 | — |
| **pretend 模式** | ✅ `pretend=False` L199 | ✅ P1#9 |
| **版本兼容检查** | ✅ `verify_copier_version()` | ✅ P0#4 |
| **Phase 上下文跟踪** | ✅ `Phase.use()` + ContextVar | ✅ P2#13 |

---

## 建议修复优先级

### 本迭代必须做（影响 init 功能正确性）：P0#1~5
1. `renderer.py` 接口增加 `is_binary` 检测 + 二进制文件 copy 路径
2. `scaffold.py` `execute()` 前调用 `verify_ae_version(self._template.min_ae_version)`
3. `renderer.py` 接口改用 `SandboxedEnvironment`

### 本迭代建议做（影响特定模板体验）：P1#6~9, 11
4. `TemplateConfig` 增加 `no_render: list[str]` 字段
5. `TemplateConfig` 增加 `_envops` 支持
6. `InitWorker` 增加 `pretend: bool = False` 参数

### 可延后（v2.0 update 功能时做）：P2#13, P1#8, P1#12
7. Phase 上下文跟踪 — 与 update 功能一起实现
8. external_data 懒加载 — 与复杂模板场景一起实现
9. 嵌套模板选择 — 与模板变体系统一起实现
