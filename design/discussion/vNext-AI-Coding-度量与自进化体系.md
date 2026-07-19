# vNext 对标分析：AI Coding 度量与自进化体系

> 来源：`~/Documents/66-Project/ClaudeCode/AI Coding/AI-Coding-度量与自进化体系设计方案.md`（2026-07-07）
> 与主对标讨论稿 `vNext-LangGraph-DeepAgents-对标分析.md` 的关系：独立讨论主题，作为可观测性（§4）的深层设计输入
> 更新：2026-07-19 — 用户决策收敛（§8 四项决策已定案）+ **已整合到设计文档**（v5.6-Design-Loop.md 附录 F：Phase 20 开发就绪规格）
> 定位：Phase 20 设计输入（讨论稿使命完成，后续开发以附录 F 为权威规格）

---

## 0. 为什么需要这个主题

LangGraph+Deep Agents 对标分析 §4（可观测性与审计追溯）的改进建议是 OTLP tracing + 结构化审计日志——这些是"能看到数据"的基础设施。但可观测性的终点不是"看到"，而是"用数据驱动系统自进化"。

参考材料 `AI-Coding-度量与自进化体系设计方案.md` 设计了一套完整的度量指标体系（28 项指标、三级评价模型）+ 自进化引擎（7 步闭环），这正是 Auto-engineering 可观测性层的"上层建筑"——在 DebugTracer/OTLP 基础设施之上，决定"度量什么、怎么评价、如何自动优化"。

本讨论稿从 Auto-engineering 的视角审视这套体系：哪些可直接借鉴、哪些需适配裁剪、哪些不适用。

---

## 1. 参考材料核心框架摘要

### 1.1 评价体系（板块 A）

| 维度 | 核心内容 |
|------|---------|
| **设计原则** | 多维度不单一指标、结果导向不看出力、系统层级不度量个人、定量+感知双轨、AI 溯源标记 |
| **理论基础** | DORA 2024/2025 + SPACE + DevEx + DX Core 4 + Vella & Blincoe「中间环」 |
| **指标体系** | 6 大类 28 项：A 交付效率(6) / B 质量返工(5) / C 人机协作(5) / D 验证成本(4) / E 采纳使用(4) / F 感知体验(4) |
| **评价模型** | 三级（任务/团队/组织）+ 加权评分（质量返工 0.30 最高，呼应 DORA AI 悖论）|
| **ROI 模型** | 五类成本（上下文/推理/验证/返工/治理）+ 三级预算（任务/团队/组织）|
| **治理体系** | 五边界落地 + 四级风险分级 + 治理决策矩阵 |
| **数据模型** | 9 种采集事件 + 统一元信息 JSON schema（含 AI 溯源标记）|

### 1.2 自进化体系（板块 B）

| 阶段 | 内容 |
|------|------|
| **设计哲学** | 借鉴 darwin-skill 2.0：单一可调参数、双重评估、棘轮机制、独立验证、人在回路 |
| **七步闭环** | 观测 → 诊断 → 生成 → 人工审批 → 灰度应用 → 验证（棘轮 keep/revert）→ 沉淀回写 |
| **信号检测** | 趋势检测（Mann-Kendall）、突变检测（IQR）、比率异常（关联解耦）、成本告警 |
| **诊断分析** | 规则引擎 + 历史模式匹配 + 因果关联 |
| **可调参数** | 阈值(11 项)/上下文模板(8)/验证策略(6)/Agent 配置(5)/流程(4)/策略(3) — 安全红线不可调 |
| **棘轮机制** | keep（改善+无副作用）/ revert（退化自动回滚）/ stop（边际收益不足）|
| **人在回路** | L1 策略审查 / L2 灰度确认 / L3 组织推广 |
| **成熟度** | L1 个人辅助 → L5 自治运营，当前业界 ~80% 处于 L1-L2 |

---

## 2. 与 Auto-engineering 的关系映射

### 2.1 架构层次对应

```
参考材料的六层架构                    Auto-engineering 的层
─────────────────                    ─────────────────
评价层（度量指标+评价模型）    ←→     可观测性层（DebugTracer + OTLP + audit log）
治理层（五边界+分级策略）      ←→     Guardrail + Gate + stage 权限控制
                                    
自进化引擎（7 步闭环）         ←→     Loop 内部尚无对应层
                                    （最接近的是 plan_refine 回路，但那是需求级纠正，
                                      不是系统级「观测→诊断→参数调优」的自进化）
```

**核心差距**：Auto-engineering 有"观测"（DebugTracer）和"治理"（Guardrail/Gate），但两者之间没有闭环——观测到的信号不会自动触发治理参数调整。参考材料的自进化引擎填补的就是这个缺口。

### 2.2 指标映射：哪些已有、哪些缺失

| 参考指标类 | Auto-engineering 已有 | 缺失/需建设 |
|-----------|----------------------|------------|
| A 交付效率 | `tick_orchestrator.py` 记录 total_ticks、convergence 判定 | 无时间维度的周期指标（A1-A6） |
| B 质量返工 | Gate test/lint/audit 结果、critic findings | 无返工率统计（B4 AI 返工率是最关键的） |
| C 人机协作 | `plan_refine` 计数（反馈轮次的代理指标） | 无一次成功率、意图转化效率 |
| D 验证成本 | DebugTracer 记录 stage 序列 + 时间戳 | 无 token 消耗统计（**已定案**：Provider 层 hook 采集，见 §8 决策 3） |
| E 采纳使用 | 无 | Agent 驱动 vs Standalone 驱动使用量对比 |
| F 感知体验 | 无 | 需调查系统（非引擎范畴） |

### 2.3 自进化引擎 vs Auto-engineering 现有能力

| 自进化阶段 | Auto-engineering 现有对应 | 差距 |
|-----------|--------------------------|------|
| 1. 观测 | DebugTracer tick JSON + errors.jsonl | 缺少聚合/趋势检测/异常信号生成 |
| 2. 诊断 | 无 | 无根因分析能力 |
| 3. 生成 | 无 | 可调参数空间已在 §5.4 定义（8 项参数 + 自动化等级），待实现 |
| 4. 灰度应用 | 无 | 无 A/B 或灰度机制 |
| 5. 验证（棘轮） | `plan_refine` 有 refine 预算控制（现象类似） | 非通用棘轮机制，仅限需求纠正 |
| 6. 沉淀回写 | BEACON.md + PromptRegistry | 非自动化，人工写入 |

---

## 3. 借鉴策略：什么直接借鉴、什么适配裁剪、什么不适用

### 3.1 直接借鉴（设计模式层面的好东西）

| 借鉴点 | 来源 | 映射到 Auto-engineering |
|--------|------|------------------------|
| **棘轮机制（keep/revert/stop）** | darwin-skill 2.0 → §11 棘轮控制器 | Auto-engineering 的 `plan_refine` 已有分源/全局预算控制，可抽象为通用 `RatchetController`——任何参数调优都遵循 keep/revert/stop 三元判定 |
| **AI 溯源标记（ai_origin）** | §3.1 采集数据模型 | 每个 tick record 附加 `ai_origin`（agent_type/model/level），使所有度量可按"AI 参与程度"分组对比。这是度量体系的**基石**——没有这个标记，无法判断 AI 的增量效果 |
| **独立验证（子 agent 盲评）** | darwin-skill → §9.1 | B6.7a 的 plate_deep_audit 和 system_deep_audit 已经是 3 并行独立 subagent 审计。这个设计可以直接复用到自进化验证——变更效果由独立子 agent 评估，避免"自己改自己评"的偏差 |
| **人在回路分层审批** | §13 | 可与 Auto-engineering 的 Guardrail/Gate 体系融合——低风险参数自动调整（如阈值微调）→ 中风险需 TL 审批 → 高风险（Agent 权限/安全配置）双审批 |
| **信号检测规则** | §10 Phase 1 | 可在 DebugTracer 之上加一层 `SignalDetector`：趋势检测、突变检测、比率异常——把原始观测数据翻译为结构化信号 |

### 3.2 适配裁剪后借鉴

| 借鉴点 | 为什么需要裁剪 | 裁剪方向 |
|--------|--------------|---------|
| **28 项指标体系** | 参考材料面向"团队-组织"级 AI Coding 运营，Auto-engineering 是一个单工具/单 loop，很多指标在当前阶段不适用（如团队级聚合、组织 ROI、感知调查） | 裁剪为 **Auto-engineering 专属指标集**（见 §4），聚焦任务级指标。团队/组织级延后到多团队推广阶段 |
| **事件采集总线（Kafka/PubSub）** | Auto-engineering 是单项目 CLI 工具，不需要分布式事件总线 | 简化为本地结构化日志（扩展 DebugTracer）+ OTLP 导出，可被外部采集系统消费即可 |
| **三级预算模型（任务/团队/组织）** | 当前只有任务级 token 预算有意义 | 先做任务级 token 预算 + 超支告警，团队/组织级延后 |
| **治理五边界落地** | Auto-engineering 已有 Guardrail(9 道) + Gate(7+1 道) 覆盖任务/权限/验证边界 | 不重复设计，只做"度量输入→治理决策"的自动推荐链路（如"某类任务连续 5 次 P0 问题→降级风险等级"） |

### 3.3 不适用

| 项 | 理由 |
|----|------|
| **F 类感知调查（F1-F4）** | 需要组织级调查系统，非 Auto-engineering 工具范围 |
| **组织 ROI 看板** | 需要多团队/多项目数据聚合，当前阶段 YAGNI |
| **团队健康仪表盘** | 同上，等至少 3 个项目持续使用后再考虑 |
| **成本归因到团队/个人** | 违反"不度量个人"原则 + Auto-engineering 单用户工具不需要 |
| **IDE 遥测（Copilot/Codex API）** | Auto-engineering 是 CLI + Plugin，不绑定 IDE |
| **自愈管道（Self-Healing Pipelines）** | 参考材料 §17.2 的自愈管道处理技术故障（编译/测试失败），Auto-engineering 的 Gate 已经覆盖；自进化处理系统性退化（返工率/上下文质量），是互补关系非替代 |

---

## 4. Auto-engineering 专属度量指标集（裁剪后）

### 4.1 核心指标（Phase 可落地，5 项）— 2026-07-19 用户确认

| # | 指标 | 定义 | 数据源 | 优先级 |
|----|------|------|--------|:---:|
| M1 | **Loop 收敛效率** | 单需求完成所需 tick 数 | `total_ticks` / `ConvergenceJudge.evaluate()` 结果 | P0 |
| M2 | **Critic 打回率** | critic MAJOR verdict 占比 | `critic_verdict` = MAJOR 的 tick 数 / 总 tick 数 | P0 |
| M3 | **验证层级触发率** | 各验证层实际触发次数（component_verifier / plate_deep_audit / system_verifier / system_deep_audit） | StageRouter 阶段转换日志 | P1 |
| M4 | **Plan Refine 频率** | 回到 architect 重设计的次数 | `refine_source_count` / `refine_global_count` | P1 |
| M5 | **Token 消耗效率** | 有效产出代码行 / 总 token 消耗 | LLM API 层 token 采集（Provider 层 hook，侵入式） | P1 |

### 4.2 扩展指标（后续 Phase，6 项）

| # | 指标 | 定义 | 数据源 |
|----|------|------|--------|
| M6 | **Gate 通过率（按 gate 类型）** | 每道 gate 的 pass/block 比例 | `gate_results` |
| M7 | **Guardrail 拦截率（按 guardrail 类型）** | 每道 guardrail 的 pass/block/retry 比例 | `guardrail_results` |
| M8 | **AI 返工率** | developer 生成后被 revert/modify 的代码行占比 | Git diff + ai_origin 标记 |
| M9 | **需求理解精度** | gap_scan 发现的 architectural gap 数量 / 最终需 plan_refine 的数量 | gap_scan + plan_refine 记录 |
| M10 | **跨组件契约冲突率** | plate_deep_audit 发现的跨组件问题数 / 总组件数 | plate_deep_audit findings |
| M11 | **Agent 驱动 vs Standalone 收敛对比** | 同一需求的 Agent vs Standalone tick 数/ token 消耗/ MAJOR 频率差异 | 双驱动基准数据 |

---

## 5. 自进化引擎在 Auto-engineering 的实现路径

### 5.1 最小可用闭环（MVP 范围）— 2026-07-19 用户决策更新

参考材料 §9.2 的七步闭环是完整版，Auto-engineering 的 MVP 先做四步闭环：

```
观测（Signal Detector，基于 DebugTracer + audit log 数据）
  → 诊断（规则引擎，基于已知因果关系表）
    → 建议（输出治理建议给用户）
      → 低风险参数自动调整（阈值微调等，含棘轮 keep/revert 保护）
```

**分层自动化策略**（2026-07-19 用户决策）：

| 风险等级 | 参数范围 | 自动化程度 | 审批要求 |
|---------|---------|-----------|---------|
| **低风险** | 阈值微调（`max_refine_per_source` ±1、`max_iter` ±5）、token 预算警告线 | **自动调整 + 通知**，棘轮机制保护（退化自动 revert） | 无需审批，事后可追溯 |
| **中风险** | 策略变更（验证层裁剪阈值 LEAF/PLATE/FULL 判定调整、context offloading 策略切换） | **建议 + 用户确认** | 用户一键审批 |
| **高风险（安全红线）** | Guardrail 禁止跳过、Gate 最低通过标准、Agent 权限范围 | **不可自动调整** | 需设计文档变更 + 用户显式审批 |

**Why 低风险自动调整**：阈值微调的效果可以通过棘轮机制（keep/revert）自动验证——调整后指标改善 → keep 固化为新基线；指标退化 → revert 自动回滚。这类调整的 blast radius 小、可逆、有明确验证标准，人工审批是过度流程开销。

### 5.2 信号检测器（Signal Detector）

在 DebugTracer + audit log 之上增加信号分析层。双数据源分工：
- **DebugTracer tick JSON**：tick 计数、stage 序列、convergence 判定、gate/guardrail 结果 → M1/M2/M3/M4
- **Audit log JSONL + Provider token hook**：token 用量、模型版本、request/response 大小 → M5

```python
# 伪代码
class SignalDetector:
    def analyze(
        self,
        tick_history: list[TickRecord],       # 来自 DebugTracer
        token_records: list[TokenRecord],      # 来自 Provider hook + audit log
    ) -> list[Signal]:
        signals = []
        
        # M2: 趋势检测 — 最近 5 tick 的 MAJOR 频率上升
        if major_rate_trend(tick_history[-5:]) == "increasing":
            signals.append(Signal("critic_major_increasing", severity="WARN"))
        
        # M4: 突变检测 — 单 tick plan_refine 突然发生
        if tick_history[-1].refine_count > baseline.p95:
            signals.append(Signal("plan_refine_spike", severity="WARN"))
        
        # M1: 收敛异常 — tick 数超过同类需求基线 2x
        if tick_history[-1].total_ticks > baseline.median * 2:
            signals.append(Signal("slow_convergence", severity="CRITICAL"))
        
        # M5: 比率异常 — token 消耗效率低于基线 50%
        current_efficiency = tick_history[-1].loc_added / max(token_records[-1].total_input_tokens, 1)
        if current_efficiency < baseline.token_efficiency_median * 0.5:
            signals.append(Signal("token_efficiency_drop", severity="WARN"))
        
        return signals
```

### 5.3 诊断规则表（已知因果关系）

借鉴参考材料 §10 Phase 2 的信号-原因映射：

| 信号 | 关联指标 | 可能原因 | 建议动作 | 可自动调整的参数 |
|------|:---:|---------|---------|------------------|
| critic MAJOR 频率上升 | M2 | 需求规格模糊 → architect 产出不精确 → developer 实现偏差 | 检查需求/设计文档是否需要细化；触发 gap_scan 复审 | —（需人工判断） |
| plan_refine 频繁触发 | M4 | 设计文档与实现之间的差距累积，非单次问题 | 建议拆分需求为多个 Phase；或标注设计项为"分阶段实现" | `max_refine_per_source` ±1 |
| 某组件返工率持续 > 30% | M8(扩展) | 组件本身复杂度过高或设计规格有歧义 | 触发 plate_deep_audit 对该组件专项深度审计 | —（需人工判断） |
| token 消耗效率下降 | M5 | 上下文膨胀（冗余文件或过长的设计文档） | 检查 context 裁剪策略；触发 context offloading | token 预算警告线 |
| Gate test 持续 block | M6(扩展) | developer 生成代码质量下降（与 prompt 漂移或模型问题相关） | 检查 developer prompt 是否需要校准；检查模型版本 | `AE_MAX_TOOL_CALLS` +5 |
| 收敛 tick 数持续上升 | M1 | 需求复杂度被低估或 batch_plan 粒度过细 | 检查 batch 拆分策略；考虑合并小 batch | `max_iter` +10 |
| 验证层始终为 LEAF（跳过 deeper audit） | M3 | 设计文档层次简单，或深层 audit 未被触发 | 检查验证裁剪逻辑是否正确；手动触发一次 FULL | 验证裁剪阈值（建议确认） |

### 5.4 棘轮机制与可调参数空间 — 2026-07-19 用户决策更新

参考 darwin-skill 的 keep/revert，映射到 Auto-engineering 的参数管理：

| 场景 | 棘轮动作 |
|------|---------|
| 调整阈值后指标改善 | keep — 固化为新基线 |
| 调整阈值后指标退化 | revert — 自动回滚到上一个配置版本（git tag） |
| 调整后边际收益 < 最低有效阈值 | stop — 不堆微调，触发探索性变更提议 |

Auto-engineering 的可调参数范围（标注自动化等级）：

| 参数 | 当前值 | 可调范围 | 调整触发条件 | 自动化等级 |
|------|--------|---------|------------|:---:|
| `max_refine_per_source` | 2 | 1-4 | 同一组件 2 次 refine 仍不满意 | **自动** |
| `max_refine_global` | 4 | 2-8 | 全局 refine 频率高但收敛效果好 | **自动** |
| `AE_MAX_TOOL_CALLS` | 10 | 5-20 | developer 频繁触达上限 | **自动** |
| `max_iter` (StandaloneDriver) | 20 | 10-40 | 复杂需求提前截断 | **自动** |
| token 预算警告线 | 无 | 按需求复杂度分档 | 连续 3 次超支 | **自动** |
| 5 层验证裁剪阈值 (LEAF/PLATE/FULL) | 基于设计文档层次 | 可手动覆盖 | plate_deep_audit 发现大量跨组件问题时 | **建议确认** |
| context offloading 策略 | 每 stage 全量卸载 | 选择性卸载（仅大文件） | context 压力指标超标 | **建议确认** |
| Prompt 模板选择 | B12 PromptRegistry | 按需求类型匹配 | 特定需求类型反复失败 | **建议确认** |

**安全红线（不可自动调整）**：Guardrail 禁止跳过、Gate 最低通过标准、Agent 权限范围、PII 防护规则。

**棘轮配置版本化与 checkpoint 的关系**：

| 维度 | RatchetController 配置版本化 | SQLite checkpoint |
|------|---------------------------|-------------------|
| 存什么 | 可调参数快照（`max_refine_per_source` 等 8 项） | Tick 循环状态（EngineState 36 字段） |
| 存储方式 | git tag（`ae-config-v{N}`）+ JSON 配置文件 | SQLite WAL（`checkpoints.db`） |
| 生命周期 | 跨需求持久化（基线配置） | 单需求 tick 循环内 |
| 回滚方式 | `git checkout ae-config-v{N-1}` 恢复上一版配置 | `TickOrchestrator.restore()` 恢复上一 tick |
| 关系 | **互补非重叠**：checkpoint 管"循环到哪了"，配置版本管"参数是多少" | |

配置变更的棘轮回滚不依赖 checkpoint——配置是跨需求的全局基线，checkpoint 是单需求的会话状态。两者独立存储，互不干扰。

---

## 6. 与现有架构的集成点 — 2026-07-19 用户决策更新

| 集成点 | 现有模块 | 新增内容 |
|--------|---------|---------|
| 数据采集 | `DebugTracer` tick JSON + `audit_log` JSONL | 统一事件元信息 JSON schema（含 ai_origin 标记），双数据源：tick 快照 + LLM 调用记录 |
| Token 采集 | `providers/base.py`（`LLMProvider` Protocol）| `create_message()` 返回后 hook 记录 token 用量到 MetricsCollector（侵入式，Provider 层统一接口） |
| 信号分析 | 无 | `SignalDetector`（新增模块，读 DebugTracer + audit log 输出，产信号） |
| 诊断建议 | 无 | `Diagnoser`（规则引擎，信号→原因→建议映射表） |
| 自动调参 | 无 | `RatchetController`（新增模块，低风险参数自动调整 + keep/revert/stop 棘轮） |
| 配置管理 | `EngineState` + checkpoint | 可调参数版本化（git tag 配置快照，支持棘轮回滚） |
| 人在回路 | `AskUserQuestion`（已用） | 诊断建议通过 action JSON 的 `suggestions` 字段输出给 Agent；中高风险调整走 AskUserQuestion 审批 |
| 独立验证 | 3× code-reviewer subagent（Phase 17 恢复） | 复用到自进化效果评估——配置变更后的指标对比由独立子 agent 做 |

**MetricsCollector 独立模块**（2026-07-19 用户决策）：不扩展 DebugTracer，单独建 `auto_engineering/metrics/` 模块。
- DebugTracer 职责：per-tick 调度轨迹诊断（debug 导向），输出到目标项目 `_scratch/debug/`
- MetricsCollector 职责：跨需求的聚合趋势分析（analytics 导向），输出到项目自身 `_scratch/metrics/`
- 两者数据粒度不同：DebugTracer 是 tick 级快照，MetricsCollector 是需求级/项目级聚合
- 复用而非耦合：MetricsCollector 消费 DebugTracer 的 tick JSON + audit log JSONL 作为输入数据源
- Token 采集：在 Provider 层 `create_message()` 返回后 hook，统一写入 MetricsCollector（`LLMProvider` Protocol 保证所有 provider 走同一接口）

---

## 7. 推进优先级与时机 — 2026-07-19 状态更新

### 7.1 前置条件状态

| 前置条件 | 2026-07-18 状态 | 2026-07-19 状态 |
|------|------|------|
| **基础设施** | DebugTracer 已实现（Phase 15），但 OTLP + audit log 未就绪 | ✅ Phase 19 全部完成 — DebugTracer + OTLP tracing + Structured audit log 就绪 |
| **治理修复** | Phase 17 待启动 | ✅ Phase 17 全部完成 — 6 角色 subagent 隔离恢复 + B14 澄清 |
| **银行硬门槛** | Phase 18 待启动 | ✅ Phase 18 全部完成 — Ollama + 国产模型 + PII redaction + context offloading |
| **可观测性** | Phase 19 待启动 | ✅ Phase 19 全部完成 — OTLP + audit log + prompt caching + Stage Checkpoint Gate |
| **基线数据** | 10 需求基准数据集 | ⚠️ 仍为 10 需求，需更多真跑积累。**不阻塞 Phase 20 采集层建设** |

### 7.2 推进顺序

```
✅ Phase 17 (设计治理修复) — 已完成
✅ Phase 18 (Context & 安全加固) — 已完成
✅ Phase 19 (模型扩展 & 可观测性) — 已完成
→ Phase 20 (度量基础: M1-M5 核心指标 + ai_origin 标记 + Signal Detector + RatchetController 低风险自动调参)
  → Phase 21 (自进化扩展: 中风险参数建议确认 + 诊断规则学习)
    → Phase 22 (自进化完整: 全参数自动调参 + 成熟度 L3)
```

Phase 20 可启动。Phase 21-22 为后续扩展。

---

## 8. 用户决策（2026-07-19 已定案）

| # | 决策点 | 定案 | 理由 |
|---|--------|------|------|
| 1 | **度量指标 MVP 范围** | **保持 §4.1 的 5 项核心指标**（M1-M5），不增减 | 当前 5 项覆盖了收敛效率、质量返工、验证覆盖、设计迭代、资源消耗五个关键维度，足够诊断主要问题 |
| 2 | **自动化程度** | **低风险参数自动调整**（阈值微调类），中风险建议确认，高风险不可调 | 阈值微调 blast radius 小、可逆（棘轮 keep/revert）、有明确验证标准。人工审批对这类调整是过度流程开销。中高风险保持人在回路 |
| 3 | **Token 采集方式** | **侵入式 — Provider 层 hook**（`LLMProvider` Protocol 的 `create_message()` 返回后采集） | 所有 provider（Anthropic/OpenAI/Ollama/国产）走统一 Protocol 接口，一处 hook 覆盖全链路。比事后解析 audit log 更实时，比 Agent 层侵入更集中 |
| 4 | **模块组织** | **单独建 `auto_engineering/metrics/` — MetricsCollector 独立模块** | DebugTracer 是 debug 导向（per-tick 快照），MetricsCollector 是 analytics 导向（跨需求聚合）。职责不同、数据粒度不同、输出路径不同。MetricsCollector 消费 DebugTracer + audit log 作为输入数据源，不修改现有模块 |

### 8.1 决策影响分析

**对 Phase 20 范围的影响**：

| 影响 | 说明 |
|------|------|
| 新增模块 | `auto_engineering/metrics/` — `collector.py`（MetricsCollector）+ `signals.py`（SignalDetector）+ `diagnoser.py`（Diagnoser）+ `ratchet.py`（RatchetController） |
| 侵入点 | `providers/base.py` `LLMProvider` Protocol — `create_message()` 返回后加 token 采集 hook；各 provider 实现（anthropic/openai/ollama/glm/qwen）需统一调用 |
| 数据流 | DebugTracer tick JSON + audit log JSONL + Provider token hook → MetricsCollector → SignalDetector → Diagnoser → RatchetController（低风险自动）/ AskUserQuestion（中风险确认） |
| 存储 | `_scratch/metrics/` — per-requirement 聚合 JSON + 跨需求基线 JSON |
| 测试 | ~15-20 new tests（collector + signals + diagnoser + ratchet 各 3-5 tests） |

### 8.2 待后续决策

| 项 | 触发条件 |
|----|---------|
| 诊断规则从"手工映射表"升级为"历史模式学习" | 积累 50+ 需求诊断记录后 |
| 中风险参数也开启自动调整 | 低风险自动调整准确率 > 90% 且连续 30 需求无错误 revert |
| 组织级指标聚合（跨项目基线对比） | 至少 3 个项目持续使用 Auto-engineering |

---

_与 `vNext-LangGraph-DeepAgents-对标分析.md` 的关系：本稿是 §4 可观测性的深层设计展开。对标分析文档定稿后，两个讨论稿的核心结论合并更新到设计文档。_

---

## 9. 整合状态

**已整合到设计文档**（2026-07-19）：本讨论稿的全部决策点和设计内容已整合到 `design/v5.6-Design-Loop.md` **附录 F**（Phase 20 — AI Coding 度量与自进化体系，9 节开发就绪规格）。

**权威规格变更**：后续 Phase 20 开发以附录 F 为权威规格，本讨论稿不再与后续开发形成依赖关系。

**整合内容清单**：

| 讨论稿章节 | 附录 F 对应节 | 形式 |
|-----------|-------------|------|
| §4.1 核心指标 M1-M5 | F.3 MetricsCollector._compute_summary() | Python 伪代码 |
| §5.2 SignalDetector | F.4 SignalDetector（4 类检测 + 冷启动策略） | 完整类设计 |
| §5.3 诊断规则表 | F.5 Diagnoser（7 条规则代码化） | 完整类设计 |
| §5.4 棘轮机制 + 可调参数 | F.6 RatchetController + F.7 参数空间 | 完整类设计 + 配置表 |
| §6 集成点 | F.8 集成架构（8 集成点 + 生命周期 + 目录结构） | 集成矩阵 + 数据流图 |
| §7 推进顺序 | F.9.1 Phase 20 任务分解（T65-T69）+ 依赖关系 | 任务表 |
| §8 四项用户决策 | F.1 架构总览（设计原则）+ F.3 Module 设计决策 | 代码化 |

**借鉴的参考源码**：

| 来源 | 借鉴内容 | 应用到附录 F |
|------|---------|------------|
| 参考材料 §3.1 采集数据模型 | `ai_origin` 溯源标记（12→5 字段裁剪）+ 9→5 事件类型裁剪 | F.2.1 AIOrigin dataclass + F.2.2 度量事件类型 |
| 参考材料 §10 信号检测 | 趋势检测（Mann-Kendall）+ 突变检测（IQR） | F.4 SignalDetector（简化版滑动窗口 + 冷启动硬编码阈值） |
| 参考材料 §12 可调参数空间 | 8 项参数 + 安全红线 | F.7 可调参数空间（代码化为 Python dict + 自动化等级标注） |
| LangGraph `_loop.py` tick() | 每次 tick 产出一个结构化快照（`_emit` 模式） | F.3 MetricsCollector.record_tick_complete() 集成点 |
| LangGraph `debug.py` map_debug_tasks() | 结构化 payload 映射（过滤内部框架 key，只留用户有意义数据） | F.2.2 统一事件 JSON schema 设计 |
| LangGraph `runtime.py` Runtime | scoped context（每 run 独立 run_id/attempt 计数器） | F.3 MetricsCollector 需求级生命周期（begin/end）|
| darwin-skill 2.0 | keep/revert/stop 三元判定 | F.6 RatchetController.evaluate() |
