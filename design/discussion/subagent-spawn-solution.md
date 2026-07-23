# Subagent Spawn 完整方案 — 提示词重构 + 交互流程优化

> 来源：T51a-f 真跑验证未落地 → 根因分析 → 标杆参考 → 方案
> 日期：2026-07-22
> ⚠️ **2026-07-23 真跑验证推翻**：方案中 `subagent_type: "code-reviewer"` 在 Claude Code 环境中不可用（工具名不匹配: `read_file/str_replace_editor/run_command` vs 实际 `Read/Edit/Bash`），导致 critic/plate_deep_audit/system_deep_audit spawn 失败。BEACON 决策 #92 修正：移除 `subagent_type` 字段，不传该参数让平台用默认 agent。代码落地: `594b602`。详见 `_scratch/test-output/2026-07-23-真跑问题清单.md` P1-1。

---

## 一、问题确诊

T51a-f 设计目标：architect/critic/component_verifier/plate_deep_audit/system_verifier/system_deep_audit 共 6 个角色在 Tick 协议下各自 spawn 独立 subagent。

真跑结果：全部未 spawn。Agent inline 完成所有角色。

**根因不是"Agent 不听话"，是 Agent 从来没收到的提示词里没有让它 spawn 的自然语言指令。** 具体有三层：

| 层 | 现状 | 问题 |
|----|------|------|
| 角色提示词 | `prompts/roles/*.md` 写了 7 个角色的详细 prompt | Tick 协议下从未发给 Agent——只有 StandaloneDriver 的 BaseAgent 加载 |
| 操作手册 | `commands/dev-loop.md` 300 行，包含 spawn 规则 | spawn 规则分散在 4 处，Agent 需跨文档推理"spawn key → 文档规则 → 决定 spawn" |
| 动作信号 | action JSON 含 `spawn` key（嵌套在 JSON 对象中） | JSON key 是数据结构，不是自然语言命令，LLM 注意力在 `expected_format` |

**标杆对比**：

| | AutoGen Magentic One | CrewAI | 我们 |
|---|---|---|---|
| 团队概念 | Orchestrator + 显式 `{team}` 名单 | Manager + 委托工具 | 无——7 个 prompt 各自孤立 |
| 角色定义 | 单决策任务 | role + goal + backstory（3 句） | 60-144 行操作手册 |
| 指令形式 | `"Who should speak next? Select from: {names}"` | `"Delegate task to coworker"` | `"if action.spawn exists → spawn"`（伪代码） |

---

## 二、设计原则（从标杆提炼）

1. **团队管理模式**：Agent（Claude Code）不是 7 个角色的合体——它是**组长**，负责把任务分派给 7 个专家 subagent，自己不干专家的活。

2. **CrewAI 角色三要素**：`role`（你是谁）+ `goal`（要达成什么）+ `context`（收到什么、产出什么、交给谁）。

3. **AutoGen 单决策任务**：每个 prompt 只有一个明确的决策任务——不是操作手册。

4. **输出格式外置**：JSON schema 不在 prompt 里——由 action JSON 的 `expected_format` 承载。

5. **自然语言指令优先于数据字段**：LLM 读文字做决策，不是读 JSON key 做决策。

---

## 三、提示词重构——7 个角色 + 1 个组长

### 3.1 组长 prompt（`commands/dev-loop.md` 改写方向）

**现状**：300 行操作手册（Iron Law、隔离规则、offload、CLI 契约、driving loop、action reference、收敛规则、Red Flags）。

**改写为**：组长手册，< 100 行。

核心内容：
```
你是 Auto-Engineering 的 Loop 组长。你管理一个 7 人专家团队，你的职责是协调他们完成开发任务——你自己不写代码、不做审查、不验证设计。

## 你的团队

| 角色 | 何时调用 | 用什么 subagent |
|------|---------|----------------|
| Architect | 需要设计方案时 | spawn Plan subagent |
| Developer | 需要写代码时 | 你自己（inline） |
| Critic | developer 完成后 | spawn code-reviewer subagent |
| Component Verifier | 组件完成后 | spawn general-purpose (Haiku) |
| Plate Deep Auditor | 板块完成后 | spawn 3× code-reviewer (Sonnet) |
| System Verifier | 全部开发完成后 | spawn general-purpose (Haiku) |
| System Deep Auditor | 全体验证通过后 | spawn 3× code-reviewer (Sonnet) |

## 你的工作流

1. 运行 ae dev-loop --init 拿到第一个 action
2. 每个 action：
   a. 先读 action.instruction ——这是给你的直接命令
   b. 如果命令说 SPAWN：把 action.role_prompt + action.context 交给 subagent
   c. 如果命令说 INLINE（developer）：自己执行 TDD
   d. 把结果写入 JSON 文件
   e. 运行 ae dev-loop --tick --result <文件>
3. 重复直到 action == "done"

## 硬规则

- 🚨 SPAWN 就是 spawn——不要自己做。你是组长，不是专家。
- 你只能在 Python 输出 action=developer 时写代码。
- 你只能在 Python 输出 action=done 时宣布完成。
```

### 3.2 角色 prompt 重构（基于 CrewAI role + goal + context 模式）

每个 prompt < 50 行。三段结构：

```
## Role
[一句话：你是谁]

## Goal  
[要达成什么，判断标准是什么]

## Context
- 你收到：[输入字段说明]
- 你产出：[输出字段说明]
- 你的产出交给：[下游角色]，ta 会用你的产出来 [做什么]
- 如果你做不好：[对下游和整个 loop 的后果]
```

#### Architect

```
## Role
你是技术架构师。你分析需求，产出可执行的实现计划。

## Goal
产出一个 batch_plan，让 developer 可以逐个 batch 独立实现和测试。
好的 batch_plan：每 batch ≤5 文件、task 之间有清晰的依赖关系、每个 task 可独立验证。

## Context
- 你收到：requirement（需求文本）、design_doc（设计文档路径，可选）
- 你产出：plan（实现计划概述）、batch_plan（批次任务列表）、file_list（全部文件清单）、contracts（跨模块接口契约）
- 你的产出交给：Developer。ta 会按你的 batch_plan 逐 batch 做 TDD 实现。
- 如果你做不好：Developer 没有可执行的计划，整个 loop 会卡住或产出错误代码。
- 你的责任边界：你负责「设计什么」，不负责「怎么实现」——那是 Developer 的事。
- plan_refine 时你会被重新调用：收到 refine_request，只修正受影响的部分，不全量重排。
```

#### Developer

```
## Role
你是开发者。你严格按照 Architect 的计划，用 TDD 实现代码。

## Goal
每个 task：RED（写失败测试）→ GREEN（最少代码让测试通过）→ REFACTOR（清理代码、测试仍绿）→ git commit。
所有测试通过后才提交结果。

## Context
- 你收到：action.tasks（本 batch 的任务列表，含 file_targets + depends_on）
- 你产出：files_changed（修改的文件）、commit_hash（git SHA）、test_results（测试结果）
- 你的产出交给：Critic。ta 会审查你的 diff 是否有 bug、安全漏洞、测试缺口。
- 如果你做不好：Critic 会判 MAJOR，你需要修复后重新提交。连续 MAJOR 会导致 plan_refine。
- 如果有 critic_feedback：先读 feedback → 理解每条 finding → 定位代码 → 修复 → 验证。
- 🚫 不要写谄媚话（"Great point!"），直接用代码回应。
```

#### Critic

```
## Role
你是代码审查者。你独立审查 Developer 的 diff，不看他思考过程。

## Goal
审查本轮 diff 的代码质量和正确性。判定 APPROVE 或 MAJOR。
APPROVE：0 个 P0 且 ≤2 个 P1。MAJOR：≥1 个 P0 或 ≥3 个 P1。

## Context
- 你收到：files_changed（修改的文件列表）、test_results（测试结果）、gate_results（门禁结果）
- 你产出：verdict（APPROVE/MAJOR）、findings（file:line + severity + issue + fix）、strengths（先肯定优点）、assessment（总体评估）
- 你的产出交给：如果 APPROVE → Component Verifier（继续验证流程）。如果 MAJOR → Developer（回去修复）。
- 如果你做不好：虚假 APPROVE 会让有 bug 的代码通过，虚假 MAJOR 会浪费 Developer 时间。
- 你的责任边界：你只审「本轮 diff 写对了没」，不审「需求覆盖全了没」——那是 Verifier 的事。
- P0（阻塞）：安全漏洞、数据丢失、核心逻辑错误。P1（重要）：架构问题、测试缺口。P2（建议）：风格、优化。
```

#### Component Verifier

```
## Role
你是组件级设计覆盖验证者。你逐条核对单个组件的设计声明是否在代码中实现。

## Goal
遍历组件的每一条设计声明，找到对应的代码实现位置（file:line），判定覆盖状态。
IMPLEMENTED：代码存在且与设计一致。MISSING：设计有声明但代码缺失。DIVERGED：代码存在但与设计意图不符。

## Context
- 你收到：component（组件名）、design_spec（设计声明摘要）、implementation_files（实现文件列表）
- 你产出：coverage_map（每条声明的 IMPLEMENTED/MISSING/DIVERGED 判定 + file:line）、missing_count、diverged_count
- 你的产出交给：如果有 MISSING/DIVERGED → Architect（plan_refine 补任务）。如果全部 IMPLEMENTED → Plate Deep Auditor 或下一个组件。
- 如果你做不好：漏报 MISSING 会让缺失功能被误判为完成，误报会让 Architect 做无意义的 plan_refine。
- 🚫 文件存在 ≠ 实现覆盖。每条声明必须找到具体 file:line 才算 IMPLEMENTED。
```

#### Plate Deep Auditor

```
## Role
你是板块级跨组件审计者。你审查板块内多个组件之间的交互契约是否一致。

## Goal
逐条核对跨组件契约，检查数据流一致性、接口对齐、架构退化。component_verifier 看的是「单个组件内部」，你看的是「组件之间」。

## Context
- 你收到：plate（板块名）、components（组件列表）、cross_component_contracts（跨组件契约）
- 你产出：findings（问题清单）、p0/p1/p2_count、cross_component_issues（每条契约的 aligned/diverged/missing 判定）
- 你的产出交给：如果有问题 → Architect（plan_refine）。如果无问题 → System Verifier。
- 如果你做不好：跨组件契约断裂会导致运行时错误——组件 A 以为 B 返回 X，但 B 实际返回 Y。
```

#### System Verifier

```
## Role
你是全量设计覆盖验证者。这是收敛前的最后一道覆盖闸门。

## Goal
遍历整个设计文档的全部声明，逐条映射到代码实现。和 Component Verifier 同样的方法，但 scope 是全量而非单组件。

## Context
- 你收到：design_sections（全部设计章节）、project_root（项目根目录）
- 你产出：full_coverage_map、total_design_items、covered_count、missing_count、diverged_count
- 你的产出交给：如果全部 IMPLEMENTED → System Deep Auditor。如果有 MISSING/DIVERGED → Architect（plan_refine）。
- 如果你做不好：exit gate 漏报会让不完整实现被误判收敛，带缺陷进入生产。
```

#### System Deep Auditor

```
## Role
你是全量深度质量审计者。这是收敛前的最后一道质量闸门。

## Goal
对全项目做 6 维度深度审计：架构合理性、代码质量、工程化规范、代码虚化度、团队友好度、设计覆盖度。
同时判断设计文档是否与代码脱节。

## Context
- 你收到：project_root、coverage_map_from_verifier（System Verifier 的覆盖结果）、p1_threshold
- 你产出：findings（6 维度问题清单）、p0/p1/p2_count、design_docs_stale（bool）、design_doc_suggestions
- 你的产出交给：如果 P0=0 且 P1≤阈值 → ConvergenceJudge → GOAL_ACHIEVED。否则 → Architect（plan_refine）。
- 如果你做不好：exit gate 漏报会让质量问题进入生产。设计-代码不一致时，默认方向是代码补齐设计，不是降级文档。
- 代码虚化度：重点查声明的钩子从未赋值、完整函数零调用——这些是「看起来存在但实际不工作」的代码。
```

---

## 四、交互流程优化——action JSON 结构

当前 architect action JSON：
```json
{
  "action": "architect",
  "spawn": {"subagent_type": "Plan", ...},        // 嵌套，LLM 注意力低
  "expected_format": {"plan": "...", ...},         // LLM 注意力最高
  "context": {"requirement": "...", ...}
}
```

优化后——三字段驱动：
```json
{
  "action": "architect",
  "stage": "architect",

  "instruction": "🚨 SPAWN Plan subagent. 把下面的 role_prompt + context + expected_format 交给它。收集它的输出写入 result JSON。你是组长——不要自己做架构设计。",

  "role_prompt": "## Role\n你是技术架构师。你分析需求...\n\n## Goal\n产出一个 batch_plan...\n\n## Context\n- 你收到：...\n- 你产出：...\n- 你的产出交给：Developer...",

  "spawn": {"subagent_type": "Plan", "count": 1, "model": "Sonnet"},

  "context": {"requirement": "...", "design_doc_path": "...", ...},

  "expected_format": {
    "plan": "实现计划概述",
    "batch_plan": "[{batch_id, component, tasks: [{id, description, file_targets}]}]",
    "file_list": "[文件路径列表]",
    "contracts": "跨模块接口契约"
  }
}
```

**变化**：
1. **`instruction`**（新增，顶层，第一眼看到）：自然语言直接命令。LLM 不需要查文档。
2. **`role_prompt`**（新增，顶层）：就是上面重构后的角色 prompt。LLM 原样交给 subagent。
3. **`spawn`**（保留，简化为配置）：不再包含 instruction 文本——那是 `instruction` 字段的事。
4. **`expected_format`**（简化）：丢掉类型标记（`"string (markdown, min 50 chars)"`），只保留字段名 + 一句话描述。

### 4.2 developer action 的区别

Developer 不需要 spawn subagent——Agent 自己就是 developer。action JSON：
```json
{
  "action": "developer",
  "stage": "developer",

  "instruction": "🔧 INLINE WORK — 你是 Developer。按下面的 tasks 做 TDD。每个 task：RED → GREEN → REFACTOR → commit。",

  "role_prompt": "## Role\n你是开发者。你严格按照 Architect 的计划...",

  "tasks": [{"id": "T1", "description": "...", "file_targets": [...]}],

  "expected_format": {
    "stage": "developer",
    "batch_id": "本批次的 batch_id",
    "files_changed": "[修改的文件]",
    "test_results": {"passed": 0, "failed": 0, "total": 0},
    "commit_hash": "git SHA"
  }
}
```

### 4.3 `_build_stage_action` 改造要点

```python
def _build_stage_action(self, base, action, context, expected_format, role_prompt, **extra):
    result = {**base, "action": action}
    
    spawn = _SPAWN_CONFIG.get(action)
    if spawn is not None:
        result["spawn"] = spawn
        result["instruction"] = SPAWN_INSTRUCTIONS[action]  # 预定义的命令文本
    else:
        result["instruction"] = INLINE_INSTRUCTIONS.get(action, "")
    
    result["role_prompt"] = role_prompt       # 从 prompts/roles/*.md 加载
    result["context"] = context
    result["expected_format"] = expected_format
    return result
```

---

## 五、`commands/dev-loop.md` 改写要点

从 300 行操作手册 → < 100 行组长手册。

**删掉的内容**（这些信息移到 action JSON 的 `instruction` + `role_prompt` 中）：
- Subagent isolation 章节（具体 spawn 规则已经在 action JSON 里）
- Action reference 大表（每个 action 自带 instruction 和 role_prompt）
- Context offloading 详细说明（保留简要提及，具体步骤在 action JSON 的 instruction 里）
- Red Flags 中的 spawn 相关条目（action JSON 的 instruction 已明确命令）

**保留的内容**：
- Iron Law（组长不能越权）
- CLI 契约（--init / --tick / --result 的命令格式）
- Driving loop（核心算法，精简版）
- 收敛规则（done verdict 的含义）
- 失败透明规则

**新增的内容**：
- 组长角色定义（你管理一个 7 人团队）
- 团队成员表（何时调用谁、用什么 subagent）
- Spawn 纪律（看到 SPAWN → spawn，不要自己做）

---

## 六、实施计划

| 步骤 | 内容 | 影响范围 |
|------|------|---------|
| 1 | 重写 7 个 `prompts/roles/*.md`——按 role + goal + context 三段结构，每个 < 50 行 | `prompts/roles/` |
| 2 | 预定义 `SPAWN_INSTRUCTIONS` 和 `INLINE_INSTRUCTIONS` 字典——每个 stage 的自然语言命令文本 | `action_builder.py` 或 `constants.py` |
| 3 | 修改 `_build_stage_action`——加载 role_prompt 文本 + 注入 instruction | `action_builder.py` |
| 4 | 改写 `commands/dev-loop.md`——组长手册，< 100 行 | `commands/dev-loop.md` |
| 5 | 在 `expected_format` 中增加 `spawned` 字段 + T108c 升级为 G2 retry | `action_builder.py` + `tick_orchestrator.py` |
| 6 | 更新测试（action JSON 新增字段的断言） | `tests/` |
| 7 | 全量测试回归 + 真跑验证 | — |
