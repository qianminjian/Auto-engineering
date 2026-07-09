# Init → Loop 接口契约（交付给 Init 项目）

> 创建：2026-07-09 | 来源：Auto-Engineering v5.6 设计变革对 Init 项目的需求输入
> 用途：**本文件是给 Init 项目团队的独立交付物**，自包含。Init 据此更新其 manifest 产出逻辑。
> 权威源：`design/v5.6-Design-Loop.md` §IL.1-IL.5（本文件是其面向 Init 的抽取，不引入新契约）

---

## §0 TL;DR — Init 需要做的 4 件事

1. **采用版本化 Schema SSOT**：Loop 侧抽出 `init-manifest.schema.json`（JSON Schema，见 §5）作为**双仓库唯一权威契约源**。Init 以**复制 + 版本 pin** 方式引用该 schema（复制内化，非运行时链接），生成 manifest 后依它自校验。
2. **新增字段 `conventions.ci_platform`**（可选，enum `github`/`gitlab`/`none`，默认 `none`）：Init 声明自己脚手架了哪个 CI 平台，供 Loop 的 CI 薄壳选型。
3. **新增字段 `structure.design_root`**（可选，string）：Init 声明设计文档目录约定。注意——**manifest 只声明目录位置，不载设计文档内容**（内容由 Loop 侧 `ae dev-loop --design-doc <path>` 人工/外部输入）。
4. **提供共享 reference fixture**：`tests/fixtures/init-manifest.reference.json` 代表一份真实 Init 产物，双仓库同步同一副本做消费者驱动契约测试（Init 做生成侧断言，Loop 做消费侧断言）。

> 契约**架构选型不变**（单向 Init→Loop / 文件桥接 / Loop 只读 / forward-compat 未知字段忽略）。v5.6 仅补缺口，不推翻。

---

## §1 契约总览

| 方向 | 数据 | 位置 | 说明 |
|------|------|------|------|
| **Init → Loop** | `.ae-state/init-manifest.json` | 项目根 | Init 完成时写入，Loop 启动时读取（**只读**）|
| **Loop → Init** | (无) | — | Loop 不反向调用 Init（**单向依赖**）|
| **契约 SSOT** | `init-manifest.schema.json` | 双仓库共享 | 版本化 JSON Schema：Init 依它生成 / Loop 依它校验 |

**契约面边界（重要）**：`.ae-state/checkpoints.db` 是 **Loop 私有运行时状态，不是 Init-Loop 契约面**。Init **不需要**读写该 DB。若未来 Init 需读，须**另立**版本化契约，不复用 manifest schema。

---

## §2 完整字段规格 + 示例

| 字段 | 类型 | 必需 | Loop 用途 | 引入版本 |
|------|------|------|----------|---------|
| `schema_version` | string | 是 | 兼容性检测（Loop 支持 min 1.0 / max 9.9）| v5.0 |
| `project_type` | enum(8) | 是 | 类型校验（见 §7 monorepo 限制）| v5.0 |
| `language` | enum(5) | 是 | 决定 linter/type_checker/test_runner 默认 | v5.0 |
| `conventions.linter` | string | 是 | 配置 lint Gate | v5.0 |
| `conventions.type_checker` | string | 是 | 配置 type_check Gate | v5.0 |
| `conventions.test_runner` | string | 是 | 配置 test Gate | v5.0 |
| `conventions.build_cmd` | string | 否 | 配置 build Gate | v5.0 |
| **`conventions.ci_platform`** | **enum(github/gitlab/none)** | **否（默认 none）** | **CI 薄壳选型** | **v5.6** |
| `structure.source_root` | string | 是 | 文件沙箱根 | v5.0 |
| `structure.test_root` | string | 是 | 测试目录 | v5.0 |
| **`structure.design_root`** | **string** | **否** | **设计文档目录约定（Architect design-doc 模式 / Pre-flight Gap 默认检索根）** | **v5.6** |

**示例（v1.1，含 v5.6 新字段）：**

```json
{
  "schema_version": "1.1",
  "project_type": "cli-tool",
  "language": "python",
  "conventions": {
    "linter": "ruff",
    "type_checker": "mypy",
    "test_runner": "pytest",
    "build_cmd": "uv build",
    "ci_platform": "github"
  },
  "structure": {
    "source_root": "src/myapp",
    "test_root": "tests",
    "design_root": "design"
  }
}
```

---

## §3 枚举合法值（与 Loop 侧 `init_contract.py` 一致）

- **`project_type`（8）**：`app-service` · `library` · `cli-tool` · `skill` · `hook` · `mcp-server` · `spec-doc` · `monorepo`
- **`language`（5）**：`python` · `typescript` · `go` · `rust` · `bash`
- **`conventions.ci_platform`（3）**：`github` · `gitlab` · `none`

> Loop 校验：`project_type`/`language` 不在合法值 → 报错拒绝运行。`schema_version` < 1.0 → 拒绝；> 9.9 → WARN forward-compat 继续。

---

## §4 v5.6 新增字段的设计理由

- **`conventions.ci_platform`（B1）**：Init 最清楚自己脚手架了 `.github/workflows/` 还是 `.gitlab-ci.yml`，由它声明最权威。Loop 的远程 CI 薄壳据此选型，避免运行时探测目录的脆弱推断。
- **`structure.design_root`（B2）**：设计文档**内容**是人工/外部输入（`ae dev-loop --design-doc <path>`），manifest 只声明**目录约定**。理由：manifest 承载 structure/conventions（结构约定），不承载 content（设计意图）；Init 不生产设计意图。

---

## §5 契约 SSOT 协议 + JSON Schema（v1.1）

**为什么要 Schema SSOT**：Init 是独立仓库。此前契约由"Loop 设计文档表格 + Loop 侧手写 `validate_*` 函数"两处定义，Init 靠读文档表对齐 → 跨仓库漂移必然。

**协议**：
- **权威副本在 Loop 仓库**：`init-manifest.schema.json`。
- **Init 复制内化**：以复制 + 版本 pin 引用（**非运行时链接**——不 fetch、不依赖 Loop 仓库在线）。
- **联动**：schema 文件含 `$id` + `version`，与 manifest 的 `schema_version` 字段联动。
- **变更纪律**：schema 变更 = 契约变更，须**双仓库同步 + bump version**。

**JSON Schema 骨架（权威定义）：**

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://auto-engineering/init-manifest.schema.json",
  "version": "1.1",                         // v5.6 引入 ci_platform/design_root → 1.1
  "type": "object",
  "required": ["schema_version", "project_type", "language", "conventions", "structure"],
  "additionalProperties": true,             // forward-compat: 未知字段忽略
  "properties": {
    "schema_version": { "type": "string" },
    "project_type": { "enum": ["app-service","library","cli-tool","skill","hook","mcp-server","spec-doc","monorepo"] },
    "language": { "enum": ["python","typescript","go","rust","bash"] },
    "conventions": {
      "type": "object",
      "required": ["linter", "type_checker", "test_runner"],
      "properties": {
        "linter": { "type": "string" },
        "type_checker": { "type": "string" },
        "test_runner": { "type": "string" },
        "build_cmd": { "type": "string" },
        "ci_platform": { "enum": ["github","gitlab","none"], "default": "none" }
      }
    },
    "structure": {
      "type": "object",
      "required": ["source_root", "test_root"],
      "properties": {
        "source_root": { "type": "string" },
        "test_root": { "type": "string" },
        "design_root": { "type": "string" }
      }
    }
  }
}
```

---

## §6 消费者驱动契约测试（reference fixture）

**问题**：IL-AC 测试此前用合成 fixture，Init 真实输出格式从未被 pin —— 双边契约只测消费侧。

**方案**：
- **共享 reference fixture** `tests/fixtures/init-manifest.reference.json` —— 代表一份**真实 Init 产物**（覆盖全部必需 + 可选字段 + 一个 monorepo 样例）。
- **双仓库同步**：Init 仓库以相同副本做**生成侧**断言，Loop 仓库做**消费侧**断言（consumer-driven contract，类 Pact 思路的轻量版）。
- **round-trip 断言**：Loop 侧 `validate_init_manifest(reference).ok is True` 且据它产出预期 Gate 配置。
- fixture 随 schema `version` 升级同步更新。

---

## §7 monorepo 约定（已知限制，非承诺）

v5.6 沙箱 + BatchState 设计基于**单包布局**：
- `monorepo` 枚举值**保留**（不删，避免破坏 Init 已有输出 = 契约降级）。
- Loop 将 `structure.source_root`/`test_root` 视为**主包**根。
- `project_type=monorepo` 时 Loop 输出 **WARN** 提示单包降级运行。
- **多包沙箱隔离推迟**（YAGNI，团队内部工具当前不需要）。

> Init 可继续输出 `monorepo`，但应知晓 Loop 当前按主包降级处理。

---

## §8 不属于 Init 的职责

- ❌ Init 不写 `.ae-state/checkpoints.db`（Loop 私有）。
- ❌ Init 不载设计文档**内容**（只声明 `design_root` 目录）。
- ❌ Init 不反向调用 Loop（单向依赖）。
- ❌ Init 不需要实现多包 monorepo 隔离（Loop 侧当前不消费）。

---

## §9 Init 验收清单

Init 更新完成后应满足：

- [ ] manifest 生成后依 `init-manifest.schema.json`（v1.1）自校验通过。
- [ ] 输出含 `conventions.ci_platform`（若脚手架了 CI）。
- [ ] 输出含 `structure.design_root`（若有设计文档目录）。
- [ ] 与 Loop 共享同一份 `tests/fixtures/init-manifest.reference.json`，生成侧断言通过。
- [ ] schema 变更时双仓库同步 + bump `version`。
- [ ] 保持向后兼容：不删除 v5.0 必需字段，未知字段可加（Loop 会忽略）。

对应 Loop 侧验收（供参考）：

| ID | 验收条件 | 状态 |
|----|---------|------|
| IL-AC-01~05 | v5.0 基线（缺失报错 / 读取配 Gate / 未知字段忽略 / 版本下限拒绝 / Loop 不改 manifest）| ✅ 已交付 |
| IL-AC-06 | Loop 校验对照 schema SSOT 执行（非手写字段检查）| v5.6 待实现 |
| IL-AC-07 | 共享 reference fixture round-trip 契约测试通过 | v5.6 待实现 |
| IL-AC-08 | monorepo 单包降级 + WARN；ci_platform 驱动 CI 薄壳选型 | v5.6 待实现 |

---

## §10 变更历史

| 日期 | 变更 | 版本 |
|------|------|------|
| 2026-07-09 | v5.6 契约扩展：Schema SSOT + `ci_platform` + `design_root` + monorepo 单包降级 + 消费者驱动契约测试；checkpoints.db 从契约面移除 | schema 1.1 |
| （v5.0 基线）| `schema_version`/`project_type`/`language`/`conventions`/`structure` + IL-AC-01~05 | schema 1.0 |
