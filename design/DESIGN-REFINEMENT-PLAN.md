# 设计细化任务计划（开发启动前的必做设计工作）

> 创建：2026-07-09 | 来源：用户要求"启动代码开发前全面细化必须的设计工作，不允许以'后面再说'虚化设计，逐条目安排设计任务，像管理代码一样管理设计"
> 范围：`design/v5.6-Design-Loop.md`（3498 行）+ `INIT-LOOP-CONTRACT.md` + 现有代码基线
> 状态：**待用户审核任务计划** → 逐个 DS 任务执行 → 全部 DoD 通过 → 才允许进入实现 Phase 1

---

## 一、反虚化 —— 设计"完成"的定义（Design DoD）

一个设计条目**只有全部满足**以下才算"done"，否则退回细化，**禁止**进入实现：

1. **数据结构有具体 schema**：每个跨组件/跨 tick 传递的数据（EngineState 字段、batch_plan、coverage_map、result JSON）有字段名+类型+约束+示例，不留"list[dict]"无子结构。
2. **算法有决策表或伪代码**：每个判定/转换/映射有明确规则（如"如何判定组件 batch 全部完成"），不留"由 Agent 判断"这类把设计推给运行时的措辞。
3. **无未决措辞裸奔**：`待定/可选/后续/推迟/简化/骨架/TODO` 必须有**显式 scope 决策**背书（"YAGNI 明确不做" 或 "本期做，规格如下"），不允许无决策的模糊延后。
4. **可验收**：每个设计条目能翻译成一条可测行为（对应实现任务的验收标准）。
5. **设计-实现-代码三方一致**：设计文档描述与现有代码不一致时，按 `design-document-inviolability.md`——默认补代码，降级须审批。

**元规则**：本计划每个 DS 任务完成时，产出直接写回 `v5.6-Design-Loop.md` 对应章节（不另开影子文档），并在下方勾选 DoD。

---

## 二、缺口清单（深度分析结论）

分类：**P0 = 阻断实现/缺关键决策**；**P1 = 欠具体，开发者会被迫自行发明设计**；**P2 = 一致性/完整性复核**。

### P0 — 缺关键决策，必须先定

| # | 缺口 | 证据 | 影响 |
|---|------|------|------|
| G1 | **deep_audit 是 1 个 Agent 还是 3 个并行 Agent** —— 矛盾 | B6.5/B6.7 描述为**单 Agent 多维度**；B15/T27/`deep_audit.py`(agent_source: architecture/code_quality/engineering) 说**"3-agent 并行审计"** | DeepAuditGate 实现、成本、延迟、plate/system_deep_audit 规格全依赖此决策 |
| G2 | **B15 新 Guardrail（REDGuard/FreshGate）未进 B3 规格** | B3 只有 G1-G6；B15 是散文描述，无 timing/applies_to/检查逻辑/retry | Phase 6 T29/T30 无法实现（REDGuard 的"commit-time 对比"具体 git 操作未定义） |
| G3 | **B5.1 Gate 清单与代码不一致** | B5.1 列 7 道(…contract/test/coverage/build)**无 audit**；代码 `registry._build_default_gates` = safety/lint/type_check/**audit**/contract/test/build（coverage 恒 skip 在 7 道外）| Gate 数量/构成是核心契约，文档-代码漂移；B15 的 AuditGate 语义层 + 与 system_deep_audit 分层也需落到 B5 |

### P1 — 欠具体，开发者会被迫发明

| # | 缺口 | 证据 | 影响 |
|---|------|------|------|
| G4 | **BatchState 数据模型无字段/方法/状态转换规格** | T3 仅一行"新建 BatchState 数据模型(plates→components→batches)"；C.5 只 new 了它 | T7/T11/T12 全依赖"组件/板块完成"判定；无规格无法实现路由 |
| G5 | **batch_plan dict 子 schema 未定义** | B1.1 `batch_plan: list[dict] 0..20` 无子结构；但 `_determine_verification_layers` 读 `b["component"]`、BatchState 依赖 batch 结构 | 层次裁剪、BatchState、architect 产出契约都悬空 |
| G6 | **DesignDoc.parse() → plates/components/design_items 的识别算法未定义** | T4 一行"解析层次结构"；C.5 注"产出 plates/components/design_items(design_section,key_claims)" 但无 how | component_verifier 全靠它；文档不合预期结构时的行为未定义（[Q?] Haiku 覆盖准确率根源） |
| G7 | **coverage_map 缺失/偏离 → architect 重规划的输入契约未定义** | 验证层输出 MISSING/DIVERGED；T9/T13/T17/T19 路由到 architect，但"gap 如何变成 architect 输入 task/prompt"没写 | plan_refine 回路的数据流断裂 |
| G8 | **plan_refine 环路检测：4 个回源是否共享计数器未定义** | T9/T13/T17/T19 都可回 architect；`max_plan_refines=3` 但未说是全局共享还是分源计数 | [Q?] 无限 architect→developer 环路防护不明确 |
| G9 | **verifier/audit 用 Haiku 的误判 fallback 未定义** | B6.4/B6.6 用 Haiku；无"映射错误时升级 Sonnet / 人工复核"策略 | [Q?] Haiku 能力边界的兜底缺失 |
| G10 | **Tick 端到端延迟：预算/测量/降级无设计** | BEACON [Q?]；每 tick 独立进程 + Agent spawn | 高频路径性能风险无设计级约束 |

### P2 — 一致性/完整性复核（未发现明确缺陷，但需逐节过 DoD）

| # | 复核项 | 说明 |
|---|--------|------|
| G11 | B10 Pre-flight gap_scan 分级标准是否具体到可执行 | architectural/component/module 分级判据 |
| G12 | B9 ProgressTree（803-1035）完整性 | 大章节，需过 DoD |
| G13 | 全量"实现任务 ↔ 设计背书"覆盖审计 | 每个 T1-T35 是否都有完整设计+验收标准；无背书的任务=虚化 |

---

## 三、设计任务计划（像代码一样管理）

> 每个 DS：**目标 / 现状 / 验收标准（DoD）/ 解决缺口 / 阻塞的实现任务 / 依赖 / 类型 / 优先级**。类型：`决策`(需用户拍板) / `规格`(写清即可) / `复核`(审计完整性)。

### Wave 1 — P0 关键决策（必须最先，含用户决策点）

**DS-1 · deep_audit 编排模型定案** ｜ 类型：决策+规格 ｜ 优先级：P0 ｜ 解决 G1
- 目标：定案 plate_deep_audit / system_deep_audit / DeepAuditGate 是"单 Agent 多维度"还是"3 Agent 并行(architecture/code_quality/engineering)后合并"。
- 验收：① 明确 Agent 数与并行方式；② 若 3-agent，定义各自 scope + 合并去重规则 + agent_source 语义；③ 回写 B6.5/B6.7 + B15 #1 + 更新 `deep_audit.py` 定位说明；④ 与 D9 频率×范围矩阵、延迟预算(DS-9)自洽。
- 阻塞：T27（DeepAuditGate 实现）、Phase 6。
- 依赖：无（先行）。**需用户决策**（成本/延迟权衡）。

**DS-2 · B15 Guardrail 提升为 B3 级规格** ｜ 类型：规格 ｜ P0 ｜ 解决 G2
- 目标：把 REDGuard / FreshGate（及 RegressionGate 若定位为 Gate 则归 DS-3）写成 B3 表格同级规格。
- 验收：每个 Guardrail 有 name/timing/applies_to_stages/检查逻辑（REDGuard 的 git 操作序列：如何定位 task 对应测试 commit + 确认其曾 FAIL）/失败动作/retry 上限；REDGuard 与现有 G3/G4 关系澄清；回写 B3 表（G7/G8…）。
- 阻塞：Phase 6 T29/T30。依赖：DS-4（BatchState 提供 task↔commit 映射线索）。

**DS-3 · B5 Gate 清单对齐 + AuditGate 分层定案** ｜ 类型：规格+决策 ｜ P0 ｜ 解决 G3
- 目标：B5.1/B5.2 与代码对齐（audit gate 入列、coverage 恒 skip 的定位、"7+1"精确含义），并落 B15 的 AuditGate 语义层 + AuditGate↔system_deep_audit 分层。
- 验收：① B5.1 表精确反映 registry 实际 7 道 + DeepAudit 的 +1；② 明确 audit gate（正则）与 system_deep_audit（LLM）职责边界；③ RegressionGate 归属（Gate or Guardrail）定案；④ 三方一致（设计=代码或标记补代码）。
- 阻塞：Phase 6 T30/T31。依赖：DS-1（deep_audit 定位）。

### Wave 2 — P0/P1 核心数据模型与算法规格

**DS-4 · BatchState 完整数据模型** ｜ 类型：规格 ｜ P0 ｜ 解决 G4
- 目标：字段（plates/components/batches/游标）、方法（is_component_complete/is_plate_complete/advance/current_*）、完成判定规则、序列化（batch_state_json #26）、跨 tick 恢复。
- 验收：① 字段+类型+约束表；② "组件 batch 全部完成""板块所有组件完成""所有板块完成"三个判定的确定性算法（供 T7/T11/T12）；③ 序列化/反序列化契约；④ 新增 B1.x 小节。
- 阻塞：T3、T5-T8、DS-2。依赖：DS-5（batch_plan 结构）。

**DS-5 · batch_plan dict schema** ｜ 类型：规格 ｜ P0 ｜ 解决 G5
- 目标：定义 architect 产出的每个 batch dict 字段：`{component, files[], task/description, depends_on?, ...}`（≤5 files/batch 约束落地）。
- 验收：① 字段表+示例；② 与 `_determine_verification_layers` 的 `b["component"]`、BatchState、file 沙箱一致；③ 回写 B1.1 #6 + B6.1 architect output。
- 阻塞：T1/T2/T3、DS-4、层次裁剪。依赖：无。

**DS-6 · DesignDoc.parse() 契约与层次识别** ｜ 类型：规格+决策 ｜ P0 ｜ 解决 G6/G11
- 目标：定义"markdown 设计文档 → plates/components/design_items"的识别规则（标题层级映射？显式标注？）、design_item 的 design_section/key_claims 提取、**文档不符合预期结构时的行为**（报错/降级/要求用户标注）。
- 验收：① 解析输入/输出契约 + 层次映射规则（决策：靠标题层级 or 约定标记）；② design_item 抽取规则；③ 异常结构处理；④ 与 B10 gap_scan 复用关系；⑤ 回写 C.12 T4 + B10。
- 阻塞：T4、component_verifier、Pre-flight。依赖：无。**含用户决策**（层次识别约定）。

**DS-7 · 验证 gap → architect 重规划输入契约** ｜ 类型：规格 ｜ P1 ｜ 解决 G7
- 目标：定义 coverage_map(MISSING/DIVERGED) 与 deep_audit findings 如何转成 architect 的重规划输入（数据字段 + prompt 注入点）。
- 验收：① 4 个回源(T9/T13/T17/T19)统一的"gap→task"数据契约；② architect 消费该输入的 prompt 片段（走 B12 fragments）；③ 回写 B2 + B6.1 + C.5。
- 阻塞：T5/T7c、plan_refine 回路。依赖：DS-1、DS-6。

### Wave 3 — P1 决策与风险设计

**DS-8 · plan_refine 环路检测定案** ｜ 类型：决策+规格 ｜ P1 ｜ 解决 G8
- 目标：定案 plan_refine_count 是全局共享还是分源(component/plate/system)计数；定义超限后的终止语义。
- 验收：① 计数器语义决策；② 与 T10/T14/T20 stop 条件、ConvergenceJudge 一致；③ 回写 B2/B4 + EngineState #19。
- 阻塞：收敛正确性。依赖：DS-7。**需用户决策**。

**DS-9 · Haiku verifier 误判 fallback** ｜ 类型：决策+规格 ｜ P1 ｜ 解决 G9
- 目标：定义 component/system_verifier(Haiku) 映射不可靠时的兜底（升级 Sonnet 重试？置信度阈值？人工复核 hook？）。
- 验收：① fallback 触发条件 + 动作；② 与延迟/成本预算自洽；③ 回写 B6.4/B6.6。
- 阻塞：验证层可靠性。依赖：DS-1。**需用户决策**。

**DS-10 · Tick 延迟预算与降级设计** ｜ 类型：决策+规格 ｜ P1 ｜ 解决 G10
- 目标：给出单 tick 延迟目标（如 P50/P95 预算）、测量点、超预算时的降级/告警设计。
- 验收：① 延迟预算数值 + 测量方案（对应 Phase 5 测试）；② 超预算行为；③ 回写 A.1/C.2 + BEACON [Q?] 关闭或转为验收项。
- 阻塞：性能验收。依赖：DS-1（deep_audit 并行度影响延迟）。**需用户决策**（可接受阈值）。

### Wave 4 — P2 完整性复核（对照 DoD 逐节过）

**DS-11 · B10 Pre-flight 规格复核** ｜ 类型：复核 ｜ P2 ｜ G11 → 已并入 DS-6 部分，剩余 gap_scan 分级判据 + research tier 检索细节过 DoD。
**DS-12 · B9 ProgressTree 复核** ｜ 类型：复核 ｜ P2 ｜ G12 → 过 DoD，重点看序列化(#27)、plan_refine 动态同步、折叠/聚合算法是否具体。
**DS-13 · 全量"实现任务↔设计背书"覆盖审计** ｜ 类型：复核 ｜ P1 ｜ G13
- 目标：对 Phase 0-7 每个 T-task 核对"是否有完整设计章节 + 可验收标准"，无背书者列为新 DS 或补规格。
- 验收：产出"T-task → 设计章节 → 验收标准"对照表（回写 C.11 或 C.12 附表），无空白项。
- 依赖：DS-1~DS-10 完成后做（它们补齐主要背书）。

---

## 四、执行顺序与依赖图

```
Wave 1 (P0 决策)      DS-5 ─┐
  DS-1 ──┬── DS-3           ├─ DS-4 ──┐
         └── DS-2 ←DS-4     │         │
  DS-6 ───────────────────┐ │         │
Wave 2 (数据模型)         │ │         │
  DS-5 → DS-4 → DS-2      │ │         │
  DS-6 → DS-7 ←DS-1       │ │         │
Wave 3 (决策/风险)        ▼ ▼         ▼
  DS-7 → DS-8    DS-1 → DS-9   DS-1 → DS-10
Wave 4 (复核)
  DS-11 / DS-12 / DS-13(最后, 依赖 DS-1~10)
```

**用户决策点（4 处）—— 已定案（2026-07-09）：**

| 决策 | 选择 | 对 DS 的影响 |
|------|------|-------------|
| **DS-1 deep_audit 编排** | **3 Agent 并行**（architecture / code_quality / engineering，并行后合并去重）| DS-1 规格须含：3 子 Agent 各自 scope + 合并去重规则 + agent_source 语义 + **Tick action 契约**（Agent 在 deep_audit stage 如何 spawn 3 并行 subagent 并写回合并 findings）；成本 3× Sonnet/审计、延迟增加 **由用户接受**，DS-10 延迟预算须据此计（LLM 时间不计入 Python 编排开销）|
| **DS-6 层次识别** | **混合**：标题启发 + 可选 HTML 注释标记消歧 + Pre-flight gap_scan 兜底 | DS-6 规格须定义：标题层级默认映射规则、`<!-- component: X -->` 标记语法、解析不确定 → gap_scan 报 architectural gap 的触发条件 |
| **DS-8 plan_refine 计数** | **分源 ≤2 + 全局 ≤4** | DS-8：EngineState 需 4 个分源计数器 + 1 全局；T10/T14/T20 stop 条件按此改；同层第 2 次未解决即停 |
| **DS-9 Haiku 兜底** | **Sonnet 只复核 MISSING/DIVERGED 条目** | DS-9：verifier 输出负判定后、触发 architect 前，插入 Sonnet 窄范围复核；假阳由 system_deep_audit 兜底 |
| **DS-10 Tick 延迟**（并入 DS-9 问）| **Python 编排开销 P95<2s + 超标只告警不中断**（2026-07-09 定案）；LLM/gate 时间由既有 timeout 兜底、单独计；3-agent 并行 LLM 墙钟作独立观测项 | DS-10：Phase 5 加 Python 编排开销测试（测量点=读 SQLite→验证→Guardrail→Gate→ConvergenceJudge→写 action JSON 的墙钟）；3-agent 并行的 LLM 墙钟时间纳入"审计 tick 延迟"单独观测项，不计入 P95<2s 预算 |

> DS-1 说明：用户选择 3 Agent 并行（我原推荐单 Agent）。据此，plate_deep_audit / system_deep_audit / DeepAuditGate 统一按 3-agent 并行编排；`deep_audit.py` 的 `agent_source` 字段保留并成为权威语义（非清理对象）。

**放行标准**：Wave 1-3 全部 DS 通过 DoD + DS-13 覆盖审计无空白 → 才 unlock 实现 Phase 1。5 个决策点（DS-1/6/8/9/10）已全部定案，均转入"写规格"。

**Wave 1 执行补记（2026-07-09，spec-writing 阶段发现）：**

| 项 | 内容 | 状态 |
|----|------|------|
| RegressionGate 归属 | 写 DS-3 时发现 B15 暂标"新 Gate"，但其 revert→restore 改工作树=有状态，与无状态并行 Gate 不兼容。依 BEACON #36 先例定案为 **Guardrail**（B5.5/B3 G9）。不改决策 #47 意图，仅纠技术归属 | ✅ 用户确认 (2026-07-09) |
| batch_plan 结构澄清 | 代码 `task_factory` 用扁平 v5.0 结构（batch=单 task），v5.6 设计需嵌套（batch=一组 TDD task）。按设计优先标为 Phase 1 代码缺口，非降级 | 已记 B6.1a |
| BatchState 2 处 sketch bug | ①仅 design-doc 模式建 BatchState（batch_plan 模式崩）②current_batch_idx 全局/相对二义。已在 C 章 sketch 修正 + B1.1a 定权威语义 | 已修 |
| B5.1 gate 清单漂移 | 原表列 coverage 遗漏 audit，与 registry 代码 + BEACON #10 不符。已对齐（audit 入列、coverage 标 remote-only）| 已修 |

---

## 五、进度跟踪表

| DS | 标题 | 类型 | 优先级 | 状态 | DoD 勾选 | 阻塞的实现任务 |
|----|------|------|--------|------|---------|--------------|
| DS-1 | deep_audit 编排模型定案 | 决策+规格 | P0 | ✅ 完成 (B6.7a, 3-agent) | ☑ | T27 / Phase6 |
| DS-2 | B15 Guardrail → B3 级规格 | 规格 | P0 | ✅ 完成 (B3 G7/G8/G9 + B3.1-B3.3) | ☑ | T29/T30 |
| DS-3 | B5 Gate 清单对齐 + AuditGate 分层 | 规格+决策 | P0 | ✅ 完成 (B5.1/B5.2/B5.5) | ☑ | T30/T31 |
| DS-4 | BatchState 完整数据模型 | 规格 | P0 | ✅ 完成 (B1.1a) | ☑ | T3/T5-T8 |
| DS-5 | batch_plan dict schema | 规格 | P0 | ✅ 完成 (B6.1a) | ☑ | T1/T2/T3 |
| DS-6 | DesignDoc.parse() 契约+层次识别 | 规格+决策 | P0 | ✅ 完成 (B10.4a, 混合) | ☑ | T4 / verifier |
| DS-7 | gap → architect 重规划输入契约 | 规格 | P1 | ☐ 待办 | ☐ | T5/T7c |
| DS-8 | plan_refine 环路检测定案 | 决策+规格 | P1 | ☑ 决策已定(分源≤2+全局≤4)·规格待写 | ☐ | 收敛正确性 |
| DS-9 | Haiku verifier 误判 fallback | 决策+规格 | P1 | ☑ 决策已定(Sonnet复核负判定)·规格待写 | ☐ | 验证层可靠性 |
| DS-10 | Tick 延迟预算+降级 | 决策+规格 | P1 | ☑ 决策已定(Python开销P95<2s)·规格待写 | ☐ | 性能验收 |
| DS-11 | B10 Pre-flight 规格复核 | 复核 | P2 | ☐ 待办 | ☐ | Phase 0 |
| DS-12 | B9 ProgressTree 复核 | 复核 | P2 | ☐ 待办 | ☐ | T4b |
| DS-13 | 实现任务↔设计背书 覆盖审计 | 复核 | P1 | ☐ 待办 | ☐ | 全部 Phase |

---

_本计划是设计细化的管理主表。每个 DS 完成后：更新本表状态 + 勾 DoD + 设计产出回写 v5.6-Design-Loop.md 对应章节。全部通过前不进入实现。_
