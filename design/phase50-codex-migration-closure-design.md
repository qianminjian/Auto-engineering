# Phase 50 Codex 迁移全面收口设计

> 日期：2026-07-27
> 状态：已确认，待实施
> 来源：Phase 49 完成后的 Claude Code → Codex 迁移复审
> 权威关系：补充 BEACON #101 与 `v5.6-Design-Loop.md` D.14，不翻转既有 ✅/❌ 决策

## 1. 目标与成功标准

Phase 50 将项目从“跨宿主能力已实现”推进到“当前设计、规则、代码、配置、
文档、CI 和发布证据完全一致”。完成后，Codex 与 Claude Code 共用同一套
Host-neutral Core；当前入口不再被历史 Standalone、Provider、CodeBuddy 或已删除
CLI 命令污染；历史资产仍可审计追溯。

成功标准：

1. Codex 加载的 AGENTS.md 不包含已删除命令、旧测试基线或 Claude `@include`。
2. CI 的 Ruff、mypy、全量测试和覆盖率门禁可真实通过。
3. 失败测试不得因跨会话计数被自动跳过。
4. Host Adapter 契约覆盖检测、能力、事件归一化、CLI 解析和 usage source。
5. 当前用户文档只描述 Claude Code/Codex 的有效入口和能力。
6. Release 从压缩包验证双宿主资产、doctor 和最小 Tick。
7. BEACON 不超过 80 行，历史决策和旧规格通过归档索引访问。

## 2. 范围边界

### 2.1 做

- 修复全仓 Ruff 失败与本地测试自动 skip。
- 修正 `agent-rules/` 公共模板并重新生成 AGENTS.md/CLAUDE.md。
- 补齐 Host Adapter 的静态契约和双宿主实现边界。
- 清理 manifest、包元数据、死环境变量及未使用的强制 Provider 依赖。
- 重写 README、USER_GUIDE、API Reference、培训手册的当前能力区。
- 将旧设计决策、Standalone/Provider/CodeBuddy 规格迁移到 `design/archive/`。
- 压缩 BEACON，并将 Tracker 分为当前执行区与历史索引。
- 强化双宿主 Release 验收和契约测试。

### 2.2 不做

- 不修改 TickOrchestrator 状态机、StageRouter 转换、Gate 或 Guardrail 语义。
- 不恢复 StandaloneDriver、多 Provider 或 CodeBuddy 支持。
- 不删除 Git 历史，不删除仍有审计价值的历史设计内容。
- 不承诺 Codex 与 Claude Code 拥有相同 UI、Hook 或 transcript 能力。
- 不自动 commit、push、发布或修改用户级配置。

## 3. 设计资产分层

```text
design/
├── BEACON.md                         # 80 行以内的当前明灯
├── IMPLEMENTATION-TRACKER.md         # 当前 Phase + 历史索引
├── v5.6-Design-Loop.md               # 当前 Tick/Core 规格
├── phase50-codex-migration-closure-design.md
└── archive/
    ├── INDEX.md                      # 历史资产导航
    ├── decisions/                    # BEACON 历史决策正文
    └── legacy/                       # v5.0/Standalone/Provider/CodeBuddy 规格
```

当前文档不得以内联长篇历史记录承担审计职责。迁移历史内容时保留来源文件、原章节、
日期和决策编号，`archive/INDEX.md` 提供双向定位。Git 历史仍是最终变更证据。

## 4. 规则与文档生成

`agent-rules/instructions.md.tmpl` 是公共规则 SSOT；
`agent-rules/claude.md.tmpl` 与 `agent-rules/codex.md.tmpl` 只承载平台差异。

公共模板只列当前真实命令：

- `scripts/ae-run doctor`
- `scripts/ae-run dev-loop --init/--tick/--resume`
- `scripts/ae-run status --format json`

测试基线不得人工复制固定数字；规则模板引用
`pyproject.toml [tool.auto-engineering.baseline]` 为权威源。生成器继续以原子写方式同步
AGENTS.md/CLAUDE.md，CI 使用 `--check` 阻断漂移。

README、USER_GUIDE、API Reference 和培训手册分成：

1. 当前能力：只描述 Claude Code/Codex。
2. 历史入口：只提供归档链接，不保留可复制的退役命令。

## 5. Host Adapter 架构

Core 只依赖宿主无关数据契约。宿主适配层提供：

```python
class HostAdapter(Protocol):
    platform: HostPlatform
    capabilities: HostCapabilities

    def normalize_event(
        self, event: Mapping[str, object]
    ) -> HostEvent | None: ...

    def resolve_cli(self, plugin_root: Path) -> Sequence[str]: ...

    def usage_source(self, project_root: Path) -> UsageSource | None: ...
```

角色调用仍由宿主 Skill 使用原生协作能力执行，不进入 Python Core。Claude/Codex 的
Hook schema 独立；归一化后才进入共享策略。能力不足返回
`HOST_CAPABILITY_UNAVAILABLE`，不得用 inline 执行伪造隔离角色。

CLI resolver 的算法继续由 `scripts/ae-run` 承担；Python Adapter 暴露同等解析语义供
测试和后续宿主复用，二者通过契约测试保持一致，不复制业务状态机。

## 6. 配置、依赖与发布

- `pyproject.toml` 描述更新为 v5.6 Host-neutral Core。
- Core 未使用的 Anthropic SDK 不再作为强制依赖；确有兼容用途时放入可选 extra。
- manifest 只声明真实消费者存在的环境变量，默认值与 FeatureManifest 一致。
- Codex manifest 不声明 `commands` 能力；作者元数据不得使用 Anthropic 域名。
- Release 包继续包含双宿主 manifest、规则、Skill/Command、Hook 和 Core。
- 安装验收从 Release 压缩包执行，不从源码目录偷取模块或可执行文件。

真实 Codex 产品级插件安装若当前环境没有可调用安装接口，验收明确分为：

1. 自动化强保证：manifest 引用、Hook schema、Skill 入口、隔离安装、doctor、最小 Tick。
2. 人工产品验收：Codex 实际发现 Plugin、加载 Skill、触发 Hook。

不得将第 1 层表述为已经完成第 2 层。

## 7. 测试与错误处理

测试采用 Red → Green → Refactor：

- 规则契约测试先断言退役命令和旧数字不存在。
- 测试基础设施契约先证明失败测试不会被自动 skip。
- Host Adapter 测试先锁定 Protocol 和 Claude/Codex 行为。
- manifest/config 测试先锁定 SSOT、默认值和零死配置。
- 文档契约扫描当前区，历史归档不纳入“当前能力”断言。
- Release 测试从归档解压目录执行双宿主 smoke。

同类失败遵循三档升级；任何部分成功必须标注缺失的产品级验收。

## 8. EARS 验收标准

- **AC50-01**：While Codex 加载项目规则，when 读取核心命令，the rules shall 不包含
  `gate-check`、`ae agent`、`ae progress` 或 v5.5 裸参数入口。
- **AC50-02**：While CI 执行，when 运行 Ruff、mypy 和 pytest，the repository shall
  零 lint、零类型错误且不存在由失败计数触发的自动 skip。
- **AC50-03**：While 当前文档被检索，when 搜索 Standalone、Provider 或 CodeBuddy，
  the active sections shall 不宣称这些能力当前可用。
- **AC50-04**：While 新宿主实现 HostAdapter，when 接入 Core，the implementation
  shall 不修改 TickOrchestrator、StageRouter、Gate 或 Guardrail。
- **AC50-05**：While 构建 manifest，when 校验环境变量和默认值，the package metadata
  shall 与 FeatureManifest/RuntimeConfig 一致且不包含零消费者配置。
- **AC50-06**：While 从 Release 安装 Claude Code 或 Codex，when 执行自动验收，
  doctor and minimal Tick shall 通过，且报告不得冒充真实产品安装验收。
- **AC50-07**：While 读取 BEACON，when 获取当前目标、状态和下一步，the reader
  shall 在 80 行以内完成定位，并可通过 archive 索引追溯历史决策。

## 9. 实施顺序

1. Phase 50 落表并建立防漂移测试。
2. 修复 CI Ruff 与测试自动 skip。
3. 修正规则模板并同步双平台规则。
4. 收敛 Host Adapter、manifest、依赖和配置。
5. 强化 Release 验收边界。
6. 迁移历史设计资产并压缩 BEACON/Tracker。
7. 重写当前用户文档。
8. 执行规则同步、metadata、Ruff、mypy、全量测试、覆盖率和双宿主 Release 验收。

## 10. 风险与控制

| 风险 | 控制 |
|------|------|
| 历史迁移导致审计链断裂 | archive 保留原编号、日期、来源和索引 |
| 文档重写误删当前契约 | 文档契约测试先行，Core 规格 D.14 为准 |
| Adapter 重构影响 Core | 禁止 Core 反向依赖；现有 Tick 集成测试全量回归 |
| 依赖清理破坏可选兼容路径 | 先扫描真实 import，再以 extras 安装测试验证 |
| 产品级 Codex 验收能力不可用 | 自动/人工验收分层，明确 partial success |
