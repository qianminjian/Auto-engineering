# vNext 对标分析：LangGraph + Deep Agents vs Auto-engineering

> 来源：`docs/AI-Loop框架七方对比分析报告.html`（2026-07-18，七方对比：LangGraph + Deep Agents + AutoGen + CrewAI + Superpowers + Claude Code + ORCA）
> 范围：以 LangGraph + Deep Agents 为对标基准，审视 Auto-engineering v5.6 当前方案的差距、可借鉴点、演进方向
> 产出：优先级排序的思考分析 + 难度/风险评估，作为后续版本迭代设计输入
> **状态：已定稿并入设计文档** — 2026-07-18 所有决策点已同步到 `BEACON.md`（决策 #63-#68）+ `IMPLEMENTATION-TRACKER.md`（Phase 17/18/19）+ `v5.6-Design-Loop.md`（附录 E）。**本讨论稿不再与后续开发形成依赖关系**，后续开发以设计文档为准。

---

## 🚨 前置发现：除 Developer 外所有角色的独立 Agent 隔离已被无声移除（设计治理重大故障）

### 原始设计意图

v5.6 设计的角色模型有一条清晰的边界：

| 角色 | 设计定位 | 上下文需求 | Agent 模式 |
|------|---------|-----------|-----------|
| **developer** | 主会话，唯一执行者 | **需要上下文连贯**（跨 batch 连续编码，理解之前的实现决策） | 主 Agent 自身 |
| **architect** | 独立设计者 | **不需要** developer 上下文（只读需求+设计文档，产出 batch_plan） | 独立 subagent |
| **critic** | 独立审查者 | **绝不能**共享 developer 上下文（客观审查 diff，不能看 developer 的思考过程） | 独立 subagent |
| **component_verifier** | 独立验证者 | **不需要** developer 上下文（只读设计 spec + 代码文件，做覆盖映射） | 独立 subagent |
| **plate_deep_audit** | 独立审计者 | **不需要** developer 上下文（只读跨组件契约 + 代码，B6.7a 要求 3 并行 subagent） | 3 个独立 subagent |
| **system_verifier** | 独立验证者 | **不需要** developer 上下文（全量设计覆盖核查） | 独立 subagent |
| **system_deep_audit** | 独立审计者 | **不需要** developer 上下文（全量 6 维代码质量审计，B6.7a 要求 3 并行 subagent） | 3 个独立 subagent |

**设计逻辑**：只有 developer 是"主会话"——它需要跨 batch 的上下文连贯来理解之前的实现决策。其他所有角色都是"审查/验证/审计"——它们的工作是读产出物（diff/代码/设计文档）做独立判断，恰恰**不应该**被 developer 的思考过程影响。

**v5.6 设计文档至今仍保留这一意图**。B6.7a（L1058-L1068）明确规定：

> plate_deep_audit / system_deep_audit 的 action 含 `audit_agents` 字段（3 条），Agent 收到后**在单条消息内并行 spawn 3 个 code-reviewer 子 Agent**，各注入其 dimensions + scope_files + agent_source

### 发生了什么

| 日期 | 事件 |
|------|------|
| 2026-07-04 | gsd-code-fixer agent spawn 僵死，导致生产失效 |
| 2026-07-09 | 决策 #46（B14）将 4 项"外部依赖"打包标记为必须移除：`subagent_type="Plan"` / `subagent_type="code-reviewer"` / `/code-review --fix --auto` / `gsd-code-fixer` |
| 2026-07-11 | T10（commit `e13da0c`）执行：dev-loop.md 重写，移除全部 4 项。**所有角色的独立 Agent 隔离被一刀切移除**——architect、critic、component_verifier、plate_deep_audit、system_verifier、system_deep_audit 全部降级为同一 Agent 切换 role prompt |

当前 dev-loop.md 实际指令（L100-L104）：

```
- ❌ spawn subagent_type="Plan" for architect — you act as architect directly
- ❌ spawn subagent_type="code-reviewer" for critic — you act as critic directly
- ❌ call /code-review --fix --auto or gsd-code-fixer — covered by built-in critic + 4 verification layers
- ❌ call any gsd-* agent or MCP tool as part of the loop
```

**结果**：除了 developer，所有角色全在同一 Agent 的同一 context window 内运行。设计文档说 deep_audit 要 spawn 3 个并行 subagent，命令却说"don't spawn, act directly"——**设计文档与执行载体直接矛盾**。

### 问题定性

**这是和 2026-07-08 BEACON 决策翻转同类的设计治理事故**——甚至更严重，因为本次不是改文档，而是改命令（设计的执行载体），更难被发现。

### 三个捆绑错误

决策 #46 / T10 把四类完全不同的东西打包成"外部依赖"一刀切禁掉：

| 被禁对象 | 类型 | 是否该禁 | 理由 |
|------|------|:---:|------|
| `gsd-code-fixer` | 外部框架专属 agent | ✅ 该禁 | 功能与内部 critic + plan_refine 回路重叠，跨框架耦合导致僵死 |
| `subagent_type="Plan"` | Claude Code 内置 subagent | ❌ 不该禁 | 平台原生能力，architect 独立设计载体，不是"外部依赖" |
| `subagent_type="code-reviewer"` | Claude Code 内置 subagent | ❌ 不该禁 | 平台原生能力，设计文档 B6.7a 明确要求 3 并行审计 |
| MCP 工具 / 外部搜索 skill | 信息获取工具 | ❌ 不该禁 | 数据源不是执行者，architect 查最佳实践、critic 查参考实现都依赖搜索 |

**正确做法**：
- `gsd-code-fixer` 该禁——功能重叠 + 跨框架耦合，禁掉是对的
- Plan/code-reviewer subagent 不该禁——它们是 Claude Code 平台原生能力，不是外部框架依赖。把平台原生能力和外部框架 agent 混在一起禁，等于把自家房子的承重墙当违章建筑拆了
- MCP/搜索 skill 不该禁——architect 做设计时需要查业界最佳实践，critic 审查时需要查参考实现。数据源不是执行者，禁了是自断信息获取渠道

### 设计文档与命令的当前矛盾

| 设计文档（v5.6-Design-Loop.md） | 当前 dev-loop.md 命令 |
|------|------|
| B6.7a: plate_deep_audit "在单条消息内并行 spawn 3 个 code-reviewer 子 Agent" | L102: "❌ spawn subagent_type='code-reviewer'" |
| B6.7a: system_deep_audit 同上 3 并行 subagent | L102: 同上禁令 |
| v5.1 原始设计: architect = Plan subagent, critic = code-reviewer subagent | L100-L102: architect/critic "act directly" |

**这是 design-document-inviolability §1 的典型场景**：设计文档描述 A，命令做了 B。按照 governance 规则，默认判断应该是**命令缺失实现，不是设计过时**。

### 2026-07-18 结论：方案 A — 完整恢复 + Governance 修复

**用户决策：方案 A（完整恢复）+ Governance 修复（必须做）。**

#### 一、禁令块整段删除（Phase 17 T49/T50）

当前 dev-loop.md L98-L105 和 SKILL.md L41-L45 的四行禁令整段删除：

- **gsd-***：Python 代码不调它，Agent 按 stage 指令走就不会碰，prompt 级禁令多余
- **MCP/搜索 skill**：信息获取工具，从来就不该禁
- **Plan/code-reviewer subagent**：角色独立性恢复后自然加回独立 spawn 指令

#### 二、角色独立 Agent 隔离完整恢复（Phase 17 T51a-T51f）

所有 6 个非 developer 角色恢复独立 subagent 隔离：

| 角色 | Agent 模式 | 模型 | 说明 |
|------|-----------|------|------|
| **developer** | 主 Agent 自身 | Sonnet | 唯一需要上下文连贯的角色 |
| **architect** | `subagent_type="Plan"` | Sonnet | 独立设计，不共享 developer 上下文 |
| **critic** | `subagent_type="code-reviewer"` | Sonnet | 独立审查，绝不能看 developer 思考过程 |
| **component_verifier** | `subagent_type="general-purpose"` | Haiku | 轻量模型，设计→代码覆盖映射 |
| **plate_deep_audit** | 3× `subagent_type="code-reviewer"` | Sonnet | B6.7a 要求 3 并行审计，各注入维度+scope_files |
| **system_verifier** | `subagent_type="general-purpose"` | Haiku | 轻量模型，全量设计覆盖核查 |
| **system_deep_audit** | 3× `subagent_type="code-reviewer"` | Sonnet | B6.7a 要求 3 并行，6 维代码质量审计 |

**T51 子任务映射**：

| 子任务 | 角色 | 说明 |
|:---:|------|------|
| T51a | architect | Plan subagent，产出 batch_plan |
| T51b | critic | code-reviewer subagent，产出 findings + verdict |
| T51c | component_verifier | general-purpose subagent（Haiku），组件级设计→代码覆盖映射 |
| T51d | plate_deep_audit | 3× code-reviewer subagent（Sonnet），B6.7a 跨组件契约审计 |
| T51e | system_verifier | general-purpose subagent（Haiku），全量设计覆盖核查 |
| T51f | system_deep_audit | 3× code-reviewer subagent（Sonnet），B6.7a 全量 6 维代码质量审计 |

#### 三、Governance 修复（Phase 17 T52a-T52c）

1. **T52a** — `design-document-inviolability.md` 覆盖范围扩展到 `commands/*.md` + `skills/*/SKILL.md` + `hooks/*.sh` 中涉及架构设计约束的变更
2. **T52b** — B14 追加澄清：Claude Code 内置 subagent（Plan/code-reviewer/general-purpose）**不属于**"外部依赖"，是平台原生能力。禁令仅针对外部框架专属 agent（gsd-* / superpowers-*）
3. **T52c** — B14 追加澄清：MCP 工具和外部搜索 skill 是**信息获取工具**，不是执行者，不在禁令范围

**Governance 修复（已纳入 Phase 17 T52a-T52c，见上方决策结果）**

---

## 0. 策略定调：学他们、造自己——源码级内化

**不做 Deep Agents 的 wrapper，不自毁架构自控权。** 研究 LangGraph + Deep Agents 的方案和实现，是为了理解他们解决了什么问题、怎么解决的、哪些设计比我们好——然后把好的设计消化吸收到我们自己的架构里，形成自己的最优方案。

这个策略和 Auto-engineering 一贯的做法一致：借鉴 LangGraph 的 tick 骨架、借鉴 CrewAI 的 guardrail 三态、借鉴 Superpowers 的提示词纪律——都是"学设计、自己造"，没有一次是"装他们的包、当他们的插件"。

### 0.1 源码级内化：设计借鉴 → 源码复用（2026-07-18 战略升级）

> **决策**：全部自建，零运行时依赖。但自建过程中**直接复用 Deep Agents（Apache 2.0）的成熟源码**——不是装包调用，而是将源码内化改造后纳入 `auto_engineering/`，保持版权声明。

**Why**：
- Deep Agents 的 harness 层能力（PII middleware、Provider 抽象、Context offloading、Sub-agent 隔离）是 LangChain 团队维护的生产级代码——重新设计没问题，但重新实现一遍不如直接复用他们的源码
- Apache 2.0 许可允许复制、修改、再分发，只需保留原始版权声明——完全合法
- 内化后仍然是"零运行时依赖"——不需要 `pip install deepagents`，不需要 `import deepagents`，源码已经变成 Auto-engineering 的一部分

**复用原则**：

| # | 原则 | 说明 |
|---|------|------|
| 1 | **保留版权** | 每个内化文件头部保留原始 Apache 2.0 版权声明 + 标注修改范围 |
| 2 | **适配不改口** | 改造接口以适配 Tick 协议和 EngineState，但核心算法逻辑不改 |
| 3 | **本地测试覆盖** | 内化后的代码必须有独立 pytest，不依赖 Deep Agents 测试框架 |
| 4 | **禁拉依赖** | 内化代码如果依赖了 LangChain 内部库 → 摘出来自己实现，不在 `requirements.txt` 里加 LangChain |
| 5 | **纪律层不抄** | Tick 协议、Gate/Guardrail、TDD REDGuard、收敛判定、DecisionGate 是 Auto-engineering 独占价值，保持原创 |

**Deep Agents → Auto-engineering 源码复用映射**：

| Auto-engineering 目标 | Deep Agents 参考源 | 复用程度 | 适配点 |
|------|------|:---:|------|
| `auto_engineering/pii/redactor.py` | `deepagents/middleware/pii.py` — PII 正则规则集 + redact/mask/hash/block pipeline | **高** — 复用规则集 + pipeline 架构 | 挂载到 `BaseAgent.execute()` 调用链；规则扩展为 `PIIDetectionRule` dataclass（§5.4） |
| `auto_engineering/pii/guardrail.py`（G10） | `deepagents/middleware/pii.py` — post-agent 全量扫描 | **中** — 复用扫描模式 | 适配 Guardrail 框架的 `evaluate(state) → GuardrailResult` 接口 |
| `auto_engineering/providers/ollama.py`（T55） | LangChain `ChatOllama` adapter 的 OpenAI 兼容层 | **中** — 复用 tool_use ↔ function_call 格式转换 | 适配 v8.0 `LLMProvider` Protocol，去掉 LangChain 依赖 |
| `auto_engineering/providers/glm.py` 等（T58） | LangChain `ChatZhipuAI` / `ChatTongyi` 等 adapter | **低** — 复用 API 差异处理模式 | 大部分国产模型已兼容 OpenAI 格式，adapter 可以做得很薄 |
| `auto_engineering/context/offloading.py`（T53） | `deepagents/middleware/summarization.py` — LLM 摘要生成 + 文件 offload | **中** — 复用摘要 prompt 模板 + offload 策略 | 适配 Tick 协议的 stage 边界；摘要质量阈值可配置 |
| `auto_engineering/context/summarization.py`（T54） | 同上 — 跨轮次对话历史压缩 | **高** — 复用滚动摘要算法 | 仅 developer 主会话需要；摘要注入 tick system prompt |
| Sub-agent spawn 协议（Phase 17 T51） | `deepagents/` sub-agent context 传递 + 结果回收机制 | **低** — 复用 context 传递模式 | Claude Code `Agent` tool 原生隔离，不依赖 Deep Agents 的 spawn 实现 |

**不做源码复用的部分（纪律层，Auto-engineering 独占价值）**：

| 能力 | 理由 |
|------|------|
| Tick-Based Discrete Invocation 协议 | LangGraph 的 Pregel 是通用超步模型，Tick 是软件开发特化的离散协议 |
| 9 角色固定状态机 | StageRouter + 固定角色模型是 Deep Agents 的 supervisor pattern 的垂直替代 |
| 7+1 Gate + 9 Guardrail | 原创纪律设计，Deep Agents 的 middleware hook 是通用框架 |
| TDD REDGuard | 原创——没有任何框架把 TDD 强制成 Guardrail |
| 5 层验证 + 4 级收敛 | 原创组合设计 |
| Plan Refine 回路 | 原创——Deep Agents 的 feedback loop 是通用重试 |
| DecisionGate（HITL） | ORCA 理念借鉴 + 原创 Tick 集成 |

### 0.2 分析定位

**本分析的定位**：LangGraph + Deep Agents 是"设计参考源 + 源码参考源"，不是"迁移目标"。每个改进项都要回答三个问题：
1. 他们怎么做的（设计模式）
2. Deep Agents 源码能不能直接内化复用（Apache 2.0）
3. 实现后比现在好多少、代价多大（性价比）

---

## 1. 架构演进方向：借鉴什么、不借鉴什么

### 1.1 报告的判断（部分认同，方向不同）

报告认为"Auto-engineering 在通用 harness 层是重复造轮子，应构建在 Deep Agents 之上"。对了一半：我们的 tick 编排/SQLite checkpoint/token 限流确实和 Deep Agents 的成熟能力功能重叠。但"重叠"不等于"应该用人家的"——我们借鉴 LangGraph 的 Pregel 超步模型自己写了 tick 循环，结果比 LangGraph 更适合软件开发场景（白盒、可调试、无黑盒 graph 编排）。

**结论：功能重叠不是问题，自己造的比通用的更贴合场景才是价值。**

### 1.2 借鉴框架

对 LangGraph + Deep Agents 的能力清单，逐项判定"学设计自己造"还是"不适用"：

| Deep Agents 能力 | 判定的借鉴策略 | 理由 |
|------|------|------|
| Pregel 超步 + checkpoint | ✅ 已借鉴 | v5.6 Tick 协议就是借鉴 Pregel 的自己实现 |
| Sub-agent context 隔离 | ✅ 已恢复（Phase 17） | v5.1 原始设计即有此能力，T10 误禁，方案 A 完整恢复见 §🚨 |
| Context offloading / summarization | ✅ 学设计自己造 | 见 §2 |
| Prompt caching | ✅ 直接可用 | Anthropic 原生支持，不依赖 Deep Agents |
| 虚拟文件系统 | ❌ 不适用 | git 已是天然的 sandbox + 版本控制，软件开发场景不需要虚拟 FS |
| PII middleware | ✅ 学设计自己造 | 见 §5，用 Python guardrail 实现 |
| Permissions 声明式 allow/deny | ⚠️ 部分借鉴 | 文件级权限已有 batch_plan file_targets 约束，补 guardrail 即可 |
| modelFallbackMiddleware | ⚠️ 低优先级 | 当前模型切换可手动，自动降级 YAGNI |
| LangSmith tracing | ❌ 不绑定 | 自建 OpenTelemetry，LangSmith 作为可选 exporter |
| 模型无关（Ollama/GLM/通义） | ✅ 自己扩展 | 见 §3，基于 v8.0 Provider 抽象加 adapter |
| StoreBackend（持久化后端） | ❌ 不换 | SQLite WAL 已满足需求，换 StoreBackend 无增量价值 |
| 虚拟文件 CompositeBackend | ❌ 不适用 | 同上，git 隔离已足够 |

### 1.3 核心原则

**借鉴设计，自己实现，不引入运行时依赖。** 这和借鉴 LangGraph/CrewAI/Superpowers 的模式完全一致——学的是"问题怎么解"，不是"装哪个包"。

### 1.4 第三种范式：ORCA 编排式（七方报告新增）

> 来源：`docs/AI-Loop框架七方对比分析报告.html` §三、§六。ORCA（stablyai/orca，21K★）是七方报告新增的对比对象，代表第三种独立范式——**编排式**。控制流在编排层，用消息 + DAG + dispatch 协调多个独立 agent。

**范式定位**：

| 范式 | 控制流位置 | 代表 | 核心机制 |
|------|-----------|------|---------|
| 说服式 | LLM 脑内 | Claude Code /goal, Superpowers | prompt 说服 LLM 按流程走 |
| 强制式 | Python 进程内 | Auto-engineering, Deep Agents | 代码强制 LLM 必须按流程走 |
| **编排式** | 编排层 | ORCA | 消息 + DAG + dispatch 协调多 agent |

**ORCA 五层编排能力与 Auto-engineering 的映射**：

| ORCA 层 | 能力 | Auto-engineering 对应 | 差距 |
|------|------|------|------|
| 消息层 | Inter-agent messaging，SQLite 持久化 mail store，push-on-idle 投递，7 种消息类型（status/dispatch/worker_done/merge_ready/escalation/handoff/decision_gate） | tick JSON 文件桥接（agent→Python→agent） | 有消息传递，**缺消息类型语义**——tick JSON 是通用 payload，没有 status/dispatch/escalation 等类型区分 |
| 任务层 | Task DAG with deps 依赖，task 在 deps 全 completed 后变 ready | batch_plan 平铺 list，无依赖关系 | **缺依赖声明**——batch 间是隐式串行（按 list 顺序），无法表达"A 完成后 B/C 并行"的 DAG 结构 |
| 调度层 | Dispatch with preamble injection（任务说明 + 通信规则注入） | role prompt + task.description | 已有类似机制，但 preamble 是隐式的（嵌在 system prompt 中），不如 ORCA 的显式注入清晰 |
| 门控层 | Decision gate 人在环检查点，`--wait` 阻塞等待人工裁决 | gap_review 单点（AskUserQuestion） | **缺一等公民机制**——gap_review 是特定场景的检查点，不是通用的"任何阶段可插入人工审批"的机制 |
| 编排者层 | Coordinator loop：check inbox → dispatch → 等待 worker_done，人工可随时介入 | TickOrchestrator 循环（init→tick→result loop） | 编排循环结构相似，**缺人工随时介入的 escape hatch**——tick 一旦启动就跑完，无法在中间插入人工决策 |

**可借鉴的设计模式（4 项）**：

| # | 借鉴点 | 描述 | 映射到 Auto-engineering | 优先级 |
|---|--------|------|------|:---:|
| 1 | **Task DAG 依赖声明** | batch_plan 的 batch 间增加 `depends_on` 字段，支持"A→B/C 并行→D"的 DAG 拓扑。developer 按拓扑序执行，可并行 batch 留给后续并行执行能力 | batch_plan JSON schema 扩展：`depends_on: ["batch_id"]` 字段，BatchState 按 ready queue 推进而非线性游标 | P2 |
| 2 | **消息类型语义** | tick action/result JSON 增加 `message_type` 字段（status/dispatch/escalation），让 agent 和 Python 之间的消息有显式语义类型，而非通用 payload | action JSON schema 扩展：增加 `message_type` 枚举，TickOrchestrator 按类型路由处理逻辑 | P2 |
| 3 | **Decision gate 通用化** | 将 gap_review 的 AskUserQuestion 模式抽象为通用的 `DecisionGate`——任何 stage 完成后可插入人工审批检查点，不限于 gap 场景。**银行场景价值**：关键决策（如"是否跳过某验证层"、"是否接受 MAJOR 后重做的代码"）需要人工双签 | 新增 `DecisionGate` 抽象，与现有 Guardrail/Gate 配合：Guardrail（事前边界）→ Gate（事后卡点）→ DecisionGate（人工审批点） | P1 |
| 4 | **Coordinator escape hatch** | TickOrchestrator 循环中增加人工介入 hook——在 stage 切换点允许"暂停 + 展示当前状态 + 等人工指令"。coordinator loop 不是全自动跑完，是"自动推进 + 人工可随时暂停审查" | TickOrchestrator 增加 `--pause-at-stage` 参数，指定 stage 前暂停等待 CLI 输入 | P2 |

**不借鉴的部分**：

| 项 | 理由 |
|----|------|
| Worktree 物理隔离 | 搁置，Phase 17 subagent 逻辑隔离已满足当前需求 |
| Desktop ADE 形态 | ORCA 是桌面 GUI 应用，Auto-engineering 是 CLI + Plugin |
| 多 agent 路由（30+ CLI agent） | 我们走 subagent 隔离路线，不依赖外部 agent CLI |
| Coordinator 全自动循环 | Tick 协议已是编排循环，只补 escape hatch，不换循环结构 |

### 1.5 ORCA 人在环（HITL）双向阻塞机制：深度解析与借鉴

> 来源：核实自 `orchestration skill` 官方文档（`stablyai/orca`）。ORCA 的 HITL 不是简单的"加个审批点"——核心是**双向阻塞消息机制，人工决策是消息生命周期中的一等公民类型**。

#### 1.5.1 两条独立 HITL 通道

ORCA 有两条方向相反的 HITL 通道，覆盖完全不同的人工介入场景：

**通道 1：Gate（自上而下，协调者预设计检查点）**

```
协调者: gate-create --task <task_id> --question "此方案是否通过架构审查？"
          --options '["通过","驳回","修改后重审"]'
        → task 状态变为 blocked，协调者循环在此暂停

人工:   gate-resolve --id <gate_id> --resolution "通过"
        → task 解除阻塞，继续调度
```

- 协调者**预先**在 task DAG 中声明检查点——我知道这里需要人工决策
- task 到达 gate 时**自动变为 blocked 状态**，不会被跳过
- 人工决策含**结构化选项**（多选），不是自由文本，降低认知负担且可统计审计

**通道 2：Ask/Reply（自下而上，Worker 主动"举手"）**

```
Worker:  orca orchestration ask --to coordinator
          --question "发现循环依赖 A→B→A，设计规格是否允许？"
          --options '["打破循环","保留，加注释","撤回此task"]'
          --timeout-ms 600000
        → Worker CLI 阻塞，等待回复

协调者:   check --wait --types decision_gate
          → 收到 decision_gate 消息
          reply --id <msg_id> --body "打破循环"

Worker:   收到回复 → CLI 解除阻塞 → 拿到答案 → 继续执行
```

- Worker 在**执行中途遇到不确定**的情况，主动阻塞自己
- 发 `decision_gate` 类型消息给协调者
- 协调者（人）看到后回应——**CLI 级别的同步等待语义**
- `--timeout-ms` 防止永久阻塞，超时后 Worker 做降级处理

**两条通道的关键区别**：

| 维度 | Gate（自上而下） | Ask/Reply（自下而上） |
|------|------|------|
| 发起方 | 协调者（人预设） | Worker（Agent 主动） |
| 触发时机 | **事前**：知道此处需审核 | **事中**：遇到未预见情况 |
| 阻塞对象 | task（状态 = blocked） | Worker CLI（进程级阻塞） |
| 典型场景 | 架构审批、预算批准、安全审查 | 依赖冲突、需求歧义、发现 bug |

#### 1.5.2 消息类型系统是 HITL 的路由基础设施

两条通道依赖同一个 SQLite 持久化消息系统，8 种消息类型就是 HITL 的"路由表"：

| 消息类型 | 方向 | HITL 角色 | Auto-engineering 对应 |
|------|------|------|------|
| `decision_gate` | Worker→Coordinator | 🧑 Worker 举手等答案 | **无** |
| `escalation` | Worker→Coordinator | 🧑 人工接管，Worker 无法继续 | **无** |
| `worker_done` | Worker→Coordinator | 🧑 人工确认结果 | tick action JSON（无类型标记） |
| `dispatch` | Coordinator→Worker | 🧑 人工调度决策 | batch_plan dispatch（隐式） |
| `merge_ready` | Worker→Coordinator | 🧑 人工 merge | **无** |
| `status` | Worker→Coordinator | 🧑 人工监控进度 | progress_tree_json（单向） |
| `handoff` | Worker→Worker | 🧑 人工确认交接 | **无** |
| `heartbeat` | Worker→Coordinator | 🧑 人工监控 | **无** |

**核心差距**：Auto-engineering 只有 `status`（progress_tree_json）和 `worker_done`（tick action JSON）两种隐式语义，缺 6 种——特别是 `decision_gate` 和 `escalation`，这是 HITL 的核心。

#### 1.5.3 协调者循环中的人工介入嵌入点

ORCA 的协调者循环**不是全自动的**，在 `check --wait` 处天然阻塞：

```
loop:
  task-list --ready              → 查 ready queue
  dispatch --task <id> --inject  → 分配 task
  check --wait --types worker_done, escalation, decision_gate  → 🛑 阻塞
  ├─ worker_done   → 标记完成，check deps 是否解锁新 task
  ├─ decision_gate → 🧑 人工看 Worker 的问题 → reply → 继续 wait
  └─ escalation    → 🧑 人工判断 → 接管 or reply → 继续 wait
```

**设计精髓**：`check --wait` 不是"偶尔插入的人工审批点"，而是**循环本身的节拍器**——每一次 tick 推进都由消息到达触发，人工决策和 Worker 完成是同一层级的循环事件。

#### 1.5.4 Auto-engineering 差距总结

| 维度 | ORCA | Auto-engineering | 差距本质 |
|------|------|------|------|
| 预设检查点 | `gate-create` 绑定 task，自动 blocked | gap_review 单场景 AskUserQuestion | 无**通用 gate 原语**，无法在任何 stage 插入检查点 |
| Agent 主动举手 | `ask --to coordinator`，CLI 阻塞等回复 | 无 | Agent 无法**主动说"我不确定"** |
| 结构化决策 | `--options '["A","B","C"]'` 多选 | 自由文本 AskUserQuestion | 决策结果**不可统计审计** |
| 决策超时 | `--timeout-ms` 防无限等待 | AskUserQuestion 无限期 | 无**降级路径** |
| 阻塞语义 | gate 让 task blocked + ask 让 CLI 阻塞 | 仅 gap_review 暂停 tick | 阻塞不是**通用原语** |
| 人工介入与自动循环的关系 | 人工决策和 worker_done 是**同一层级**的循环事件 | gap_review 是**例外**，不是常态 | 人工介入不是**一等公民** |

#### 1.5.5 借鉴方案：DecisionGate 通用原语

核心思路：**不引入 ORCA 的消息系统（那需要 SQLite mail store + check --wait 循环重构，对单 tick 单 agent 架构过重），但把 HITL 的双向阻塞语义抽象为 Tick 协议的三形态 DecisionGate 原语。**

**三形态 DecisionGate**：

```
形态 1 — Pre-planned Gate（预设检查点）：
  architect 在 batch_plan 中声明 gate：
  {
    "batch_id": "b3",
    "gates": [{
      "id": "g1",
      "trigger": "after_critic",
      "question": "critic MAJOR，是否继续重做？",
      "options": ["继续重做", "跳过此 batch", "终止 loop"],
      "default": "继续重做"
    }]
  }
  → TickOrchestrator 到达 trigger 时输出 gate action JSON，
    Agent 收到 → AskUserQuestion 展示 options → 用户选 → tick 继续

形态 2 — Escalation Gate（Agent 主动举手）：
  新增 CLI 入口：
  ae dev-loop --escalate --question "发现循环依赖" --options '["打破","保留","撤回"]'
  → TickOrchestrator 暂停当前 tick，待用户回复后继续

形态 3 — Stage Checkpoint Gate（阶段边界审查）：
  TickOrchestrator 在 stage 切换时（architect→developer→critic→verifier），
  支持 --pause-at-stage 参数，输出进度摘要 + "继续/审查/终止" → 用户决策
```

**与现有机制的关系**：

| 现有机制 | 升级后 |
|------|------|
| `gap_review`（AskUserQuestion 单场景） | `DecisionGate` 通用原语，gap_review 是其中一种 gate 类型 |
| action JSON 通用 payload | action JSON 增加可选的 `gate` 块：`{type, question, options, timeout_ms}` |
| Tick 全自动推进 | Tick 支持 `--pause-at-stage`，在 stage 边界插入 checkpoint gate |

**为什么不引入 ORCA 的消息系统**：

ORCA 的 SQLite mail store + 8 消息类型 + `check --wait` 阻塞循环是为"多 agent 并行 + 跨进程协调"设计的，Auto-engineering 是单 tick 单 agent（developer，Phase 17 后其他角色走 subagent），Python 和 Agent 之间通过文件桥接通信——不需要独立的消息中间件。DecisionGate 在现有 tick JSON 协议上扩展 `gate` 字段即可，**不改循环结构，只加阻塞语义**。

**实现优先级**：

| # | 形态 | 优先级 | 理由 |
|---|------|:---:|------|
| 1 | Stage Checkpoint Gate（形态 3） | **P1** | 最低侵入，只加 `--pause-at-stage` 参数，不改变任何现有协议 |
| 2 | Pre-planned Gate（形态 1） | P2 | 需扩展 batch_plan JSON schema + TickOrchestrator gate 处理 |
| 3 | Escalation Gate（形态 2） | P2 | 需新增 CLI 入口 + agent 侧 tool 调用，上游依赖形态 1 的 gate action JSON 格式 |
| 4 | 结构化 options + timeout | P2 | 所有 gate 形态通用能力，底层 AskUserQuestion 增强 |

---

## 2. P0 — Context Management & Sub-agent 隔离（报告"担忧一"）

> **决策（2026-07-18）**：§2.4 改进建议全部接受。Phase 17 恢复 subagent 隔离后，Phase 18 执行 T53 Stage context offloading + T54 Cross-tick summarization。Prompt caching（P1）补入 Phase 19，Intermediate artifact offloading（P2）入战略储备。

### 2.1 问题还原

报告 §2.6 指出：Auto-engineering 禁用了 subagent，9 个角色全在同一 agent 的 context window 内通过 stage 切换实现。现有缓解措施（`_truncate_tool_results`、`AE_MAX_TOOL_CALLS`、Tick 独立进程、5 层验证裁剪）都是"截断/限制/裁剪"，没有真正的 **context offloading**。

**报告指出此事时的状态是真实的**——T10（2026-07-11）确实把 subagent 一刀切禁掉了。但这是设计执行错误，不是设计意图。v5.1 原始设计只有 developer 是主会话（需要上下文连贯），其余 6 个角色全部是独立 subagent。**2026-07-18 对标分析中暴露此问题，用户决策方案 A 完整恢复（Phase 17 T51a-T51f），回到设计本意。**

### 2.2 Deep Agents 怎么做

Deep Agents 的 context 管理三层：
1. **Summarization**：超长对话历史自动摘要压缩
2. **文件 offloading**：中间结果写入虚拟文件系统，需要时读回，不占 context
3. **Prompt caching**：静态 prompt 片段缓存，减少重复 token 消耗

加上 **sub-agent 隔离**：每个 sub-agent 有独立 context window，主 agent 只接收摘要。

### 2.3 我们当前有什么 + Phase 17 修复后的状态

| 机制 | 位置/Phase | 作用 | 状态 |
|------|-----------|------|:---:|
| `_truncate_tool_results` | `agents/base.py:36` | 截断 tool_result 到 8000 字符 | 仅 v5.5 路径，治标 |
| `AE_MAX_TOOL_CALLS=10` | `plugin.json:56` | 单次 tool 循环上限 | 限单 tick 不限累积 |
| Tick 独立进程 | v5.6 协议核心 | 每次 tick SQLite 持久化，进程隔离 | 同一 tick 内仍是全量 context |
| 5 层验证裁剪 | 决策 #41 | 按设计层次跳过验证层 | 减少角色数，不减单角色压力 |
| **Sub-agent context 隔离** | Phase 17 T51a-T51f | 6 个非 developer 角色各自独立 subagent，独立 context window | **恢复中** — Claude Code 原生能力，每个 subagent 自己管理自己的 context |

**Phase 17 后的剩余缺口**：
- 跨 tick 的对话历史摘要/压缩（developer 主会话累积多 tick 后的 context 压力）
- 中间产物 offloading（design doc 每 tick 重新 parse 反而增加了 context 压力）
- Prompt caching（静态 prompt 片段可缓存但未利用）

### 2.4 改进建议（Phase 17 后重新排序）

**Sub-agent 隔离已被 Phase 17 覆盖，从改进清单移除。** 剩余项按优先级重排：

| 优先级 | 改进项 | 描述 | 难度 | 风险 |
|:---:|------|------|:---:|:---:|
| **P0** | Stage context offloading | 每个 stage 完成后，将本 stage 的完整 context 卸载到文件，下一 stage 只加载摘要 + 必要上下文。**subagent 隔离恢复后更简单**——每个 subagent 的产出是结构化 JSON（batch_plan/findings），主 Agent 只需消费摘要，不需要加载子 agent 的完整对话历史 | 中 | 低 — Claude Code subagent 天然隔离，主 Agent 只接收返回结果 |
| **P0** | Cross-tick developer session summarization | developer 是唯一跨 tick 持续的主会话，tick > N（建议 5）时将其前 N-1 tick 的对话历史压缩为结构化摘要注入 prompt。**注意：仅 developer 需要此能力**——其他 6 个角色是独立 subagent，每次 tick 新 spawn，天然无累积 context 压力 | 中 | 中 — 摘要质量依赖 LLM，可能丢失关键信息 |
| P1 | Prompt caching | 静态 prompt 片段（角色定义、Hard Constraints）标注为可缓存，减少重复 token。Anthropic 原生支持，不依赖 Deep Agents | 低 | 低 |
| P2 | Intermediate artifact offloading | 大文件（design doc、全量代码）不直接塞 prompt，改为先写入 offload 文件，prompt 中只放文件路径 + 摘要 | 低 | 低 |

### 2.5 关键洞察：Subagent 隔离恢复后 Context 压力模型彻底改变

Phase 17 恢复 subagent 隔离后，context 压力模型从"1 个 Agent 扛 7 个角色"变为"1 个主 Agent + 6 个独立 subagent"：

| 维度 | 当前（禁令后） | Phase 17 恢复后 |
|------|--------------|----------------|
| 主 Agent context 负载 | 7 个角色的 prompt + 全部对话历史 | 仅 developer role prompt + 编码上下文 |
| architect context | 混在主 Agent 中 | 独立 Plan subagent，产出 batch_plan JSON |
| critic context | 混在主 Agent 中（自审盲区） | 独立 code-reviewer subagent，产出 findings JSON |
| deep_audit context | 混在主 Agent 中 | 3 个并行 code-reviewer subagent，各自独立 context |
| 累积压力 | 所有角色累积在同一个 window | developer 独享主 window，其他角色每次 tick 新 spawn |

**这个变化意味着**：Cross-tick summarization 的 urgency 从"所有角色都需要"降为"仅 developer 需要"。Subagent 角色每次 tick 新 spawn、只看当前 tick 的输入、产出结构化 JSON——天然无累积 context 压力。这是 Deep Agents 的 sub-agent 隔离设计被我们借鉴后产生的最大收益：**context 压力被 7 个独立 window 分摊，不再是单一瓶颈。**

---

## 3. P0 — 模型无关 & 平台无关

> **决策（2026-07-18）**：§3.3 改进建议全部接受。Ollama adapter + 国产模型 adapter + StandaloneDriver 全 P0，Phase 18/19 执行。

### 3.1 差距

| 维度 | Auto-engineering 现状 | Deep Agents | 差距严重度 |
|------|----------------------|-------------|:---:|
| LLM 后端 | Anthropic + OpenAI（通过 v8.0 Provider 抽象） | 任何 LangChain 兼容（Ollama/GLM/通义/文心） | **银行场景 P0** |
| 平台依赖 | 必须挂 Claude Code/Codex/CodeBuddy | 纯 Python 进程，无平台依赖 | 中 — v7.0 StandaloneDriver 已解耦 |
| 本地部署 | 不支持 | Ollama 完全离线 | **银行内网 P0** |

### 3.2 当前进展

v8.0 的 `LLMProvider` Protocol + `OpenAIProvider` 已经迈出第一步，但距离"模型无关"还有很大差距：
- 只有 Anthropic + OpenAI 两个 adapter
- 没有 Ollama/GLM/通义 adapter
- tool_use 格式转换只覆盖了 Anthropic↔OpenAI

### 3.3 改进建议

> **定位决策（2026-07-18）**：Auto-engineering 定位为**银行生产级框架**。模型无关（内网 Ollama/国产模型）和彻底平台无关是银行 AI 应用的准入条件——全部升级为 P0。

| 优先级 | 改进项 | 描述 | 难度 | 风险 |
|:---:|------|------|:---:|:---:|
| **P0** | Ollama adapter | 实现 `OllamaProvider`（OpenAI 兼容 API，tool_use → function_call 转换复用 v8.0） | 低 | 低 — Ollama 兼容 OpenAI API 格式 |
| **P0** | 国产模型 adapter | GLM/通义/文心 adapter，优先 OpenAI 兼容格式（大部分国产模型已兼容）。银行信创要求必须支持国产模型 | 中 | 中 — tool_use 格式差异需逐个适配 |
| **P0** | 彻底平台无关 | StandaloneDriver 完善（v7.0 路线图已有），不再依赖 Claude Code agent 平台。银行内网无外部 Agent 平台可用 | 中 | 中 — v7.0 已设计，是执行问题非设计问题 |

### 3.4 定位已定：银行生产级框架

不再讨论"是不是银行框架"——**是**。这意味着：

- 模型无关不是 nice-to-have，是银行内网部署的准入条件
- 国产模型适配不是可选扩展，是信创合规要求
- 平台无关不是远期目标，是银行内网无 Claude Code 平台时的唯一运行方式
- §5 PII Middleware 同步升级为 P0——银行监管对数据出境有硬约束，LLM 请求中的 PII 必须脱敏

---

## 4. P1 — 可观测性与审计追溯

> **决策（2026-07-18）**：自建方案接受。OTLP tracing + 结构化审计日志按 Phase 19 T60/T61 执行，后续进一步优化。LangSmith exporter 入战略储备。

> **推进策略**：自建（OpenTelemetry + 结构化审计日志），不绑定 LangSmith。按建议方案执行。另有独立讨论主题「AI Coding 度量与自进化体系」作为更深层的设计输入，本主题延后推进。

### 4.1 差距

| 维度 | Auto-engineering | Deep Agents + LangSmith |
|------|-----------------|------------------------|
| 每节点 trace | DebugTracer（Phase 15）tick JSON + errors.jsonl | LangSmith 一等公民，每节点自动 trace |
| prompt/response 版本锁 | PromptRegistry sha256 hash | LangSmith 自动记录 |
| 全量审计 | tick-{N}.json 自建 | LangSmith 完整 prompt/response/时间戳/操作人 |
| 可视化 | 无 | LangSmith 仪表板 |
| 成本 | 零（自建） | LangSmith 付费（有免费层） |

### 4.2 改进建议

| 优先级 | 改进项 | 描述 | 难度 | 风险 |
|:---:|------|------|:---:|:---:|
| P1 | OpenTelemetry tracing | 用 OpenTelemetry SDK 给每个 stage/guardrail/gate 打 span，导出到 OTLP collector | 中 | 低 — 行业标准，不绑定厂商 |
| P1 | Structured audit log | 每次 LLM 调用记录完整 request/response/timestamp/tokens，JSONL 格式持久化 | 低 | 低 — 扩展 DebugTracer |
| P2 | LangSmith integration | 可选 LangSmith exporter（类似 Deep Agents），但不做硬依赖 | 低 | 低 — 通过 OTLP exporter 桥接 |

### 4.3 关键讨论点

**自建 vs 买。** LangSmith 是付费 SaaS，银行内网可能不可达。OpenTelemetry 是厂商中立的行业标准——先做 OTLP tracing，LangSmith 作为可选的 exporter 插件。

Phase 15 DebugTracer 已经是好的起点——补齐 OTLP span 打点即可升级为生产级。

**更深层的设计输入**：可观测性的终点不只是"看到数据"，而是"用数据驱动自进化"。独立讨论稿 `design/discussion/vNext-AI-Coding-度量与自进化体系.md` 将从度量指标体系（28 项指标、三级评价模型）+ 自进化引擎（信号检测→诊断→方案生成→棘轮验证）两个板块展开，作为后续 Phase 设计输入。

---

## 5. P0 — PII Middleware & 数据安全

> **定位决策（2026-07-18）**：银行生产级框架 → PII 防护从 P1 升级为 P0。银行监管对数据出境有硬约束——LLM 请求发送到外部 API 前必须脱敏。

### 5.1 差距

Deep Agents 有内置 PII middleware（redact/mask/hash/block），Auto-engineering 在数据隐私层完全空白。

当前的安全防护只在规则层（`engineering-practices.md` §4.5 敏感信息检测闸门 + Hook `block-secrets-write.sh`），不在运行时 middleware 层。

| 层级 | 现有防护 | 缺失 |
|------|---------|------|
| 代码静态检测 | Hook `block-secrets-write.sh` 拦截写入 | - |
| LLM 请求脱敏 | **无** | 发送给 LLM 的 prompt 中可能含 PII |
| LLM 响应检测 | **无** | LLM 返回内容可能含生成的 PII |
| 日志脱敏 | AnthropicProvider key 脱敏 | 工具调用参数/返回结果未脱敏 |

### 5.2 改进建议

| 优先级 | 改进项 | 描述 | 难度 | 风险 |
|:---:|------|------|:---:|:---:|
| **P0** | Prompt PII redaction | 在 `BaseAgent._build_messages()` 发送前，对 prompt 做 PII 正则扫描 + 脱敏。**银行场景硬需求**：LLM 请求发送到外部 API 前必须脱敏，防止敏感数据出境 | 低 | 低 — 正则检测已有（block-secrets-write.sh），复用检测规则 |
| **P0** | Tool result PII scan | 在 `_truncate_tool_results` 同时做 PII 扫描，命中则 warn + 脱敏。防止 LLM 返回内容中含生成的 PII 被写入代码文件 | 低 | 低 |
| P1 | PII Guardrail | 新增 G10 PIIGuardrail，post-agent 扫描 LLM 响应中的 PII 模式，独立于 prompt redaction 的第二道防线 | 中 | 低 |

### 5.3 实现架构

PII middleware 在两个边界以 pipeline 模式插入现有 LLM 调用链路：

```
                         ┌──────────────────────────┐
用户 Prompt ──→ PII Scan │ T56: PromptPIIRedactor    │
                         │ BaseAgent 发送 LLM 前     │
                         │ scan + redact + warn_log  │
                         └──────────┬───────────────┘
                                    ↓
                         ┌──────────────────────────┐
                         │ LLM API Call              │
                         └──────────┬───────────────┘
                                    ↓
                         ┌──────────────────────────┐
LLM Response ──→ PII Scan│ T57: ToolResultPIIScanner │←── tool_result 合并写入前
                         │ _truncate_tool_results    │
                         │ 同步 scan + redact + warn │
                         └──────────┬───────────────┘
                                    ↓
                         ┌──────────────────────────┐
                         │ G10: PIIGuardrail         │←── 第二道防线（延后 Phase）
                         │ post-agent 全量文件扫描   │
                         │ 独立 Guardrail 框架挂载   │
                         └──────────────────────────┘
```

**设计要点**：

- **非侵入式 pipeline**：T56 在 `BaseAgent.execute()` 的 system prompt + user message 合成后、LLM 调用前插入；T57 在 `_truncate_tool_results()` 中扩展，不改变现有函数签名
- **检测规则复用**：T56/T57 共用同一个 `PII_REGEX_PATTERNS` 规则集（见 §5.4），避免两套规则
- **失败不阻断**：PII scan 命中后**默认脱敏 + WARN 日志**，不抛出异常阻断 Agent 执行。误杀的场景（如代码注释中提到身份证格式）通过白名单排除。**block 模式作为可选开关**，银行强合规场景启用
- **性能约束**：PII 扫描在每次 LLM 调用路径上（单 tick 约 3-5 次 LLM 调用），正则扫描必须 < 50ms。prompt 通常 < 20K 字符，正则扫描满足要求

### 5.4 PII 检测规则定义

复用 `engineering-practices.md` §4.5 的敏感信息规则，扩展为 Python 正则规则集：

```python
# auto_engineering/pii/rules.py（新增模块）
PII_RULES: list[PIIDetectionRule] = [
    # 中国身份证号（18 位，含校验位）
    PIIDetectionRule(
        name="cn_id_card",
        pattern=r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]',
        replacement=r'\1**********\2',
        severity="CRITICAL",
        category="PERSONAL_ID",
    ),
    # 中国手机号（11 位）
    PIIDetectionRule(
        name="cn_phone",
        pattern=r'1[3-9]\d{9}',
        replacement=r'\1****\2',
        severity="CRITICAL",
        category="CONTACT",
    ),
    # 银行卡号（13-19 位）
    PIIDetectionRule(
        name="bank_card",
        pattern=r'\b\d{13,19}\b',
        replacement=r'\1****\2',
        severity="CRITICAL",
        category="FINANCIAL",
        # 排除：git commit hash（40 hex）、timestamp（13 位毫秒）、文件大小数字
        exclusion_patterns=[r'[0-9a-f]{40}', r'\d{10,13}\b'],
    ),
    # API Key / Token
    PIIDetectionRule(
        name="api_key",
        pattern=r'(?:sk|api[_-]?key|token|secret|password|passwd)\s*[:=]\s*["\']?([^\s"\']+})["\']?',
        replacement=r'\1***REDACTED***',
        severity="CRITICAL",
        category="CREDENTIAL",
    ),
    # 邮箱地址（银行场景：可能含客户实名）
    PIIDetectionRule(
        name="email",
        pattern=r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        replacement=r'***@\1',
        severity="WARN",
        category="PII",
    ),
]

# 白名单：以下文件路径/变量名命中规则时不脱敏
PII_WHITELIST_PATTERNS = [
    r'test.*pii',           # 测试文件中的 PII 测试数据
    r'pii.*rule',           # PII 规则定义本身
    r'_\w*pii\w*_pattern',  # PII regex 字符串变量
]
```

**设计权衡**：

- **正则 vs ML**：正则满足银行业常见 PII 格式，不引入 ML 依赖（模型部署复杂度 + 隐私链路过长）。正则误杀率 < 0.1% 可接受（脱敏而非删除，信息不丢失）
- **银行卡号误杀风险**：13-19 位数字极容易误杀普通数字 ID。必须加 `exclusion_patterns` 排除已知非卡号模式，且 severity 仅为 WARN
- **规则可扩展**：`PIIDetectionRule` 为 dataclass，银行合规团队可追加自定义规则（如特定客户号格式），不修改核心代码

### 5.5 集成点与任务分解

| 任务 | 位置 | 描述 | 难度 | 预估 |
|------|------|------|:---:|:---:|
| **T56** — Prompt PII Redactor | `auto_engineering/pii/redactor.py`（新增） + `agents/base.py` | 在 `BaseAgent.execute()` 的 LLM 调用前：① `PIIRedactor.scan(messages)` 扫描 system + user content ② 命中规则 → 脱敏 + `logger.warning("PII detected in prompt: {rule_name}")` ③ 脱敏后的 messages 传给 LLM。**不修改 system prompt 模板**（规则文件本身，非 LLM 可读内容） | 低 | 1-2 天 |
| **T57** — Tool Result PII Scanner | `_truncate_tool_results()` 扩展 | 在现有截断函数中增加：① 每个 tool_result content 调用 `PIIRedactor.scan_text()` ② 命中 → 脱敏 + `logger.warning("PII in tool result: {rule_name}")` ③ 返回脱敏后的 `list[dict]`。**不改变函数签名**，调用方无感 | 低 | 1 天 |
| **G10** — PII Guardrail | `auto_engineering/loop/guardrail.py` + `auto_engineering/pii/guardrail.py` | 新增 `PIIGuardrail(Guardrail)`，post-agent 阶段扫描 developer 的 `files_changed` 全量内容。作为 T56/T57 的第二道防线——T56/T57 防 LLM 传输泄露，G10 防写入代码文件的泄露。P1 优先级，延后到 T56/T57 验证后 | 中 | 1-2 天 |

**T56/T57 的调用链路**：

```
BaseAgent.execute()
  │
  ├── 1. 构建 messages (system + user)
  │      └── T56: PIIRedactor.scan(messages) ← 插入点
  │
  ├── 2. while turn < max_tool_calls:
  │      ├── llm.create_message(system, messages, tools)
  │      ├── 执行 tools → tool_results
  │      └── T57: _truncate_and_scan_tool_results(tool_results) ← 插入点
  │
  └── 3. 返回 TaskResult
```

### 5.6 关键讨论点

**银行场景下的 PII 防护边界。** 银行 AI 辅助开发场景中，PII 风险集中在两个边界：① 用户需求描述可能含真实客户数据（输入边界）→ Prompt PII redaction 兜底；② LLM 生成代码时可能"编造"看起来像真实数据的测试数据（输出边界）→ Tool result PII scan + PII Guardrail 双层兜底。代码文件本身不含生产数据（规范已要求脱敏），但输入和输出两个边界的防护必须硬化为 middleware——规则层提示不够，需要代码层强制执行。

**正则 vs 规则层的分工。** 已有的 Hook `block-secrets-write.sh`（文件写入拦截）和 `engineering-practices.md` §4.5（编码规范）仍然是有效的第一道防线。T56/T57 补充的是"LLM 传输链路"这一层——这是规则层和 Hook 都覆盖不到的盲区（prompt 字符串在内存中构建，不经过文件系统）。三道防线互不替代：

| 防线 | 保护边界 | 触发时机 |
|------|---------|---------|
| engineering-practices.md §4.5 | 开发者编码行为 | 编码时（规范约束） |
| block-secrets-write.sh Hook | 文件写入 | 写入前（进程级拦截） |
| T56/T57 PII Middleware | LLM 传输链路 | 发送前 + 返回后（内存级拦截） |
| G10 PII Guardrail | 产出文件 | post-agent（框架级审计） |

---

## 6. P2 — 虚拟文件系统 & Sandbox

> **决策（2026-07-18）**：不做 Write sandbox。git 已经是天然的"sandbox + commit"两阶段隔离，再加一层文件沙箱是过度设计。只做 File access guardrail——低投入、高收益、不改变 developer 工作流。

### 6.1 差距

Auto-engineering 直接读写宿主仓库——这是故意的设计选择（developer 的产出就是真实代码文件），但 agent 可能误改非目标文件。Deep Agents 的虚拟文件系统解决的是"通用 agent 任务"的隔离问题，不适合"输出就是真实代码"的软件开发场景。

### 6.2 改进建议：只做 File access guardrail

| 优先级 | 改进项 | 描述 | 难度 | 风险 |
|:---:|------|------|:---:|:---:|
| P1 | File access guardrail | 新增 Guardrail，post-agent 检查 developer 的 `files_changed` 是否全在 `batch_plan.file_targets` 范围内。超出 → block + 报告越界文件列表 | 低 | 低 — batch_plan 已有 `file_targets` 字段 |

**为什么不做 Write sandbox**：
- git 提供完整的回滚能力（`git reset --hard`、`git diff`），与虚拟文件系统的"草稿→提交"等价
- 额外的 sandbox 层会改变 developer 工作流（增加"promote"操作），与 v5.6 Tick 纪律设计冲突
- Auto-engineering 的 developer 产出就是真实代码文件——sandbox 适得其反

### 6.3 实现要点

**集成位置**：`auto_engineering/loop/guardrail.py`，新增 `FileAccessGuardrail(Guardrail)`，挂载到 `DEFAULT_GATES` 或 post-developer hook。

**判定逻辑**：
```python
class FileAccessGuardrail(Guardrail):
    """检查 developer 的文件操作范围是否在 batch_plan 声明内."""

    def evaluate(self, state: EngineState) -> GuardrailResult:
        allowed = set()
        for batch in state.batch_plan:
            for task in batch.get("tasks", []):
                allowed.update(task.get("file_targets", []))

        changed = set(state.files_changed)
        out_of_bounds = changed - allowed

        if out_of_bounds:
            return GuardrailResult(
                status="block",
                reason=f"越界文件修改（不在 batch_plan file_targets 内）: {out_of_bounds}",
                suggestion="在 batch_plan 中声明 file_targets 或回滚越界修改",
            )
        return GuardrailResult(status="pass")
```

**设计约束**：
- `file_targets` 支持 glob 通配（`src/**/*.py`），用 `pathspec` 库做模式匹配
- 白名单：`.ae-state/`、`_scratch/` 下文件自动放行（不参与越界检查）
- 首次运行（无 batch_plan 历史）→ skip，不阻断

### 6.4 任务分解

| 任务 | 位置 | 描述 | 预估 |
|------|------|------|:---:|
| T62 — FileAccessGuardrail | `auto_engineering/loop/guardrail.py` | 实现 FileAccessGuardrail + 集成到 DEFAULT_GATES | 1 天 |
| T62a — glob 支持 | `auto_engineering/gates/` 或 guardrail 内部 | `pathspec` 库集成，支持 `.gitignore` 风格的 file_targets 匹配 | 0.5 天 |

---

## 8. 综合评估：改进矩阵

### 8.1 按优先级排序

| # | 改进项 | 优先级 | 难度 | 风险 | 收益 | 依赖 | 预估工作量 |
|---|--------|:---:|:---:|:---:|:---:|------|:---:|
| — | ~~Sub-agent context isolation~~ | — | — | — | — | Phase 17 T51a-T51f 恢复中 | — |
| 1 | Stage context offloading | **P0** | 中 | 低 | 高 | Phase 17 subagent 恢复（天然隔离，更简单） | 3-5 天 |
| 2 | Cross-tick developer session summarization | **P0** | 中 | 中 | 高 | #1 | 3-5 天 |
| 3 | Ollama adapter (模型无关) | **P0** | 低 | 低 | 高 | v8.0 Provider 抽象 | 1-2 天 |
| 4 | Prompt PII redaction | **P0** | 低 | 低 | 高 | 无 | 1-2 天 |
| 5 | Tool result PII scan | **P0** | 低 | 低 | 高 | #4 | 1 天 |
| 6 | 国产模型 adapter (GLM/通义/文心) | **P0** | 中 | 中 | 高 | #3 | 2-3 天 |
| 7 | OpenTelemetry tracing | **P1** | 中 | 低 | 中 | DebugTracer | 3-5 天 |
| 8 | File access guardrail | **P1** | 低 | 低 | 中 | 无 | 1 天 |
| 9 | Structured audit log (JSONL) | **P1** | 低 | 低 | 中 | DebugTracer | 1-2 天 |
| 10 | Prompt caching | **P1** | 低 | 低 | 中 | Anthropic 原生支持 | 0.5 天 |
| 11 | **Stage Checkpoint Gate**（DecisionGate 形态 3） | **P1** | 低 | 低 | 中 | TickOrchestrator `--pause-at-stage` | 1 天 |
| 12 | PII Guardrail (G10) | P1 | 中 | 低 | 中 | #4, #5 | 1-2 天 |
| 13 | Intermediate artifact offloading | P2 | 低 | 低 | 低 | #1 | 0.5 天 |
| 14 | LangSmith exporter（可选） | P2 | 低 | 低 | 低 | #5 | 1-2 天 |

> **#9 移除理由**：Sub-agent context isolation 不再是自己造的改进项——v5.1 原始设计即有此能力，Phase 17 恢复的是被 T10 误禁的 Claude Code 平台原生 subagent 隔离。恢复后 context 压力从"1 个 Agent 扛 7 个角色"变为"1 个主 Agent + 6 个独立 subagent 分摊"（详见 §2.5）。

### 8.2 风险矩阵

| 风险 | 可能性 | 影响 | 缓解 |
|------|:---:|:---:|------|
| Context offloading 丢失关键信息 | 中 | 中 | 摘要质量可配置；保留完整 offload 文件可回溯 |
| 模型无关适配引入 tool_use 格式兼容问题 | 中 | 中 | 先做 Ollama（兼容 OpenAI 格式），国产模型逐个验证 |
| PII 正则误杀正常代码 | 低 | 中 | 白名单 + 人工确认机制 |
| 过度借鉴导致架构复杂度膨胀 | 中 | 高 | 每个借鉴项先问"现有架构能否实现"，不盲目加层 |

---

## 9. 建议的 v5.7/v5.8 路线图

基于以上分析，建议分两个 Phase 推进：

### Phase 17 — 设计治理修复（当前 Phase，~3-5 天）

> 详见 §🚨 前置发现。恢复 6 角色独立 Agent 隔离 + Governance 规则扩展。

```
T49: 禁令块整段删除 — dev-loop.md L98-L105 + SKILL.md L41-L45 四行禁令移除
T50: 恢复外部搜索/MCP 能力 — dev-loop.md 加回 MCP 工具和搜索 skill 的允许指令
T51a: architect 恢复 Plan subagent — dev-loop.md Stage 1 改回 spawn subagent_type="Plan"
T51b: critic 恢复 code-reviewer subagent — dev-loop.md Stage 3 改回 spawn subagent_type="code-reviewer"
T51c: component_verifier 恢复 general-purpose subagent（Haiku）— StageRouter 组件验证阶段改回 spawn
T51d: plate_deep_audit 恢复 3× code-reviewer subagent（Sonnet）— B6.7a 并行审计恢复
T51e: system_verifier 恢复 general-purpose subagent（Haiku）— StageRouter 系统验证阶段改回 spawn
T51f: system_deep_audit 恢复 3× code-reviewer subagent（Sonnet）— B6.7a 全量审计恢复
T52a: design-document-inviolability.md 覆盖范围扩展到 commands/*.md + skills/*/SKILL.md + hooks/*.sh
T52b: B14 追加澄清 — Claude Code 内置 subagent 不属于"外部依赖"，禁令仅针对外部框架专属 agent
T52c: B14 追加澄清 — MCP 工具和外部搜索 skill 是信息获取工具，不在禁令范围
```

### Phase 18 — Context & 安全加固（P0 项，~7-11 天）

> Sub-agent 隔离已由 Phase 17 恢复。银行生产级定位要求模型无关 + PII 为 P0。

```
T53: Stage context offloading（每个 stage 完成后卸载全量 context 到文件）
T54: Cross-tick developer session summarization（tick>5 时压缩 developer 对话历史，仅 developer 需要）
T55: Ollama adapter（OpenAI 兼容格式，复用 v8.0 Provider 抽象）
T56: Prompt PII redaction（发送前正则扫描 + 脱敏，银行场景硬需求）
T57: Tool result PII scan（_truncate_tool_results 同步 PII 扫描）
```

### Phase 19 — 模型扩展 & 可观测性（P0+P1 项，~8-14 天）

```
T58: 国产模型 adapter（GLM/通义/文心，信创合规要求）
T59: 彻底平台无关（StandaloneDriver 完善，v7.0 路线图，银行内网部署）
T60: OpenTelemetry tracing（每个 stage/guardrail/gate 打 OTLP span）
T61: Structured audit log（LLM 调用完整 request/response JSONL）
T62: File access guardrail（developer files_changed 必须在 file_targets 内）
T62a: glob 支持 — pathspec 库集成，支持 .gitignore 风格的 file_targets 匹配（§6.4）
T63: Prompt caching（静态 prompt 片段标注可缓存，Anthropic 原生支持）
T64: Stage Checkpoint Gate（TickOrchestrator --pause-at-stage，DecisionGate 形态 3，§1.5）
```

### 战略储备（不入当前 Phase，后续评估）

```
PII Guardrail (G10)（待 #4 #5 验证后扩展为独立 Guardrail）
Intermediate artifact offloading（大文件 offload + prompt 摘要引用，P2 低优先级）
LangSmith exporter（OTLP bridge 就绪后作为可选插件）
Pre-planned Gate + Escalation Gate（DecisionGate 形态 1/2，§1.5，依赖形态 3 验证后再扩展）
```

---

## 10. 关键决策汇总

1. **角色独立 Agent 隔离恢复方案** → **已决策：方案 A（完整恢复）**。Phase 17 T51a-T51f 落表。

2. **Governance 规则扩展** → **已决策：本次一并修订**。Phase 17 T52a-T52c 落表。

3. **银行场景的优先级** → **已决策：Auto-engineering 定位为银行生产级框架**。模型无关（Ollama/国产模型，§3）和 PII middleware（§5）全部升级为 P0。彻底平台无关（StandaloneDriver）同步升级为 P0。

4. **§2 Context Management 改进建议** → **已决策：全部接受**。Phase 18 T53/T54 + Phase 19 T63 Prompt caching + 战略储备 Intermediate artifact offloading。

5. **§3 模型无关 & 平台无关** → **已决策：全部接受**。Phase 18 T55 + Phase 19 T58/T59。

6. **§4 可观测性** → **已决策：自建方案接受**。Phase 19 T60/T61，后续进一步优化。LangSmith exporter 入战略储备。

7. **§5 PII Middleware** → **已决策：按建议规划**。Phase 18 T56/T57 + 战略储备 G10 PII Guardrail。

8. **§6 Sandbox** → **已决策：只做 File access guardrail，不做 Write sandbox**。Phase 19 T62。

9. **§7 Production Maturity** → **已决策：去掉，不纳入规划**。

10. **ORCA 编排式范式 & HITL** → **已决策：提取可借鉴设计模式，不引入 ORCA 本身**。§1.4 五层能力映射（Task DAG/消息类型语义/DecisionGate/Coordinator escape hatch）+ §1.5 HITL 双向阻塞机制深度解析。Phase 19 T64 Stage Checkpoint Gate。

11. **分层组合战略 & 源码级内化** → **已决策：全部自建 + Deep Agents 源码内化**。Harness 层能力（PII/Provider/Context offloading）复用 Deep Agents Apache 2.0 源码，改造后纳入 `auto_engineering/`，零运行时依赖。纪律层（Tick/Gate/Guardrail/收敛/DecisionGate）保持原创。§0.1 含 7 项源码复用映射表。

12. **Phase 17/18/19 启动时间** → **待定**。Phase 17 已立项（T49-T52），Phase 18/19 启动时间待确定。

---

### 待办：Phase 19 完成后按能力覆盖矩阵回溯验证

> 来源：`docs/AI-Loop框架七方对比分析报告.html` §七（11 项能力覆盖矩阵，七方量化评分）。

Phase 17-19 全部开发完毕后，以**实际代码实现**为基准，按 11 项能力覆盖矩阵重新评分，对比讨论稿中的预期提升：

| 能力项 | 当前得分 | Phase 19 预期 | 验证方式 |
|------|:---:|:---:|------|
| 上下文隔离 | ✗ (0) | ✅ (1) | subagent spawn 日志确认 6 角色隔离 |
| 人在环 | ◐ (0.5) | ✅ (1) | `--pause-at-stage` 功能测试 |
| 多 agent 路由 | ✗ (0) | ◐ (0.5) | subagent 按角色路由验证 |
| 模型无关 | ◐ (0.5) | ✅ (1) | Ollama + 国产模型 adapter 集成测试 |
| PII 防护 | ✗ (0) | ✅✅ (2) | T56/T57 端到端 PII 扫描测试 |
| 可观测性 | ◐ (0.5) | ✅ (1) | OTLP export + audit JSONL 验证 |

**验收标准**：修正后总分 ≥ 17（当前 14.5 + 预期提升 2.5），纪律层 4 项满分（TDD/Gate/Guardrail/收敛）不退化。

---

_策略定调：学他们、造自己。LangGraph + Deep Agents 是设计参考源，不是迁移目标。借鉴设计模式，用自己的架构实现，不引入运行时依赖。这和借鉴 LangGraph/CrewAI/Superpowers 的模式完全一致。_
