# Checkpoint 契约修复 — 根因 + 步骤清单（含验收标准）

> 创建：2026-07-11 | 触发：Phase 9 A1/A3 根因（超快修范畴）| 用户定案方向：① 反序列化目标改 EngineState
> 前置调查：`_scratch/reports/2026-07-11-checkpoint-status-rootcause.md`
> 范围：`loop/checkpoint/_serialization.py` deserialize 分派 + `cli/status.py` A1 字段名 + 6 checkpoint 失败验收基线

---

## 1. 根因（统一，经验证）

**6 个 checkpoint 失败 + A1 + A3 读侧 = 同一根因**：`deserialize_state`（`_serialization.py:63-90`）**无条件**把每个 checkpoint dict 路由到 `deserialize_loop_state` → `CheckpointEnvelope(**business_fields)`：

| 输入形状 | 现行为 | 后果 |
|---------|--------|------|
| 非 envelope dict（`step` 为 string，如 `_fake_state`）| `CheckpointEnvelope(step="developer")` → pydantic ValidationError（step 需 int）→ 包成 CheckpointError | **6 checkpoint 测试失败** |
| production EngineState checkpoint | 强构造 CheckpointEnvelope，丢 `critic_verdict`/`thread_id`/`batch_state_json` | **A1 status 恒空** + **A3 读侧断链** |
| CheckpointEnvelope（migration/历史）| 正常 | ✅（需保留） |

**证据**：单跑 `test_file_store_persists_across_connections` → `checkpoint_envelope.py:228 CheckpointEnvelope(...)` 抛 `step` 校验错。`_fake_state` 存 `{"round":n,"step":str,"status":str}`，断言 `ck.state == state`（dict 恒等）。

## 2. 修复方向（用户定案 ①，细化为 shape-aware dispatch）

`deserialize_state` 改为**按 dict 形状三路分派**：

```
1. "channels" in data   → deserialize_loop_state → CheckpointEnvelope   （migration/历史）
2. "thread_id" in data  → EngineState.from_dict → EngineState           （production 主循环状态）
3. else                 → 返回原始 dict                                  （plain/partial，不强构造）
```

**分派 marker 已验证不重叠**（`asdict(EngineState())`）：
- EngineState asdict：有 `thread_id`，**无** `channels` 键
- CheckpointEnvelope model_dump：`model_dump` 恒发 `channels` 键，**无** `thread_id`
- plain 测试 dict（`round`/`step`/`status`）：两者皆无 → 落 raw dict

**为何不能全走 EngineState.from_dict**：`from_dict` 静默忽略未知键（`state.py:298-303`）→ plain dict `{round,step,status}` 会得 `EngineState(round=..)`（丢 step/status），且 `EngineState != dict` → 破坏 `ck.state == state`。故 plain dict 必须回 raw dict。

## 3. 步骤清单（TDD Red→Green→Refactor，每步一 commit）

### Step 1 — RED：deserialize 三路分派测试
- 新增 `tests/test_checkpoint_serialization_dispatch.py`（或并入现有 serialization 测试）：
  - `plain dict {round,step:str,status}` → `deserialize_state(serialize)` 返回 `== 原 dict`
  - `EngineState asdict`（含 critic_verdict/thread_id/batch_state_json 非默认值）→ 返回 `EngineState` 且三字段保真
  - `CheckpointEnvelope model_dump` → 返回 `CheckpointEnvelope`（channels 重建为 Channel 实例）
- **验收**：plain + EngineState 两分支 RED（envelope 分支应已绿）

### Step 2 — GREEN：`deserialize_state` 加三路分派
- `_serialization.py:63-90`：`json.loads` 后按 §2 分派；保留 `CheckpointError` 仅用于 envelope 分支真异常
- **验收**：Step 1 三测试绿 **+ 6 个 checkpoint pre-existing 失败绿**（test_checkpoint_store×5 + e2e×1）

### Step 3 — A1：`status.py` 读 `critic_verdict`
- `status.py:73`（dict 分支）`state.get("verdict","")` → `state.get("critic_verdict","")`
- object 分支 `getattr(state,"verdict","")` → `getattr(state,"critic_verdict","")`
- RED：`test_cli_status` 断言「EngineState checkpoint → status.verdict 非空」
- **验收**：A1 测试绿 + `test_cli_status_extended::test_collect_status_json_state_as_dict_branch` 绿（fallback raw-dict 策略恢复）
- 注：输出 JSON key 仍为 `verdict`（对外契约 §B13.2 不变），仅读取源字段改 `critic_verdict`

### Step 4 — 回归 + A3 定界
- 全量 suite：8 pre-existing 失败 → **剩 ≤1**（仅 `plugin_contract --format` 独立 CLI 漂移，与本根因无关，归 #73）；**零新增失败**
- A3 定界：`batch_state_json` 是 EngineState 字段 → 本修复令其 **读侧（load 后 round-trip）自动保真**；**写侧**（tick_orchestrator 存前 populate `batch_state_json`）属 tick 接线，归 **Phase 3 T9/T10**，不在本任务
- **验收**：全量绿（除 plugin_contract --format）；`ae status` 真跑显示非空 verdict/thread_id

## 4. 验收基线（本修复关闭的 pre-existing 失败）

> ⚠️ **执行后修正（2026-07-11）**：原表把 e2e 归为 deserialize 根因 —— **错误**。实测 clean main 上 e2e 从不因 deserialize 失败，真根因是 orchestrator.run() finally close 调用方传入的 :memory: store（独立 store 生命周期 bug），另立 commit 5983bca 修（改测试用文件 store）。修正后基线见下表「实际」列。

| 失败 | 数量 | 计划预期 | 实际 | Commit |
|------|:---:|:---:|:---:|--------|
| `test_checkpoint_store`（deserialize CheckpointError）| 5 | ✅ Step 2 | ✅ | 2fc8950 |
| `test_cli_status_extended`（verdict 源字段）| 1 | ✅ Step 3 | ✅ | 89d850a |
| `test_full_cycle_checkpoint_save_round`（e2e）| 1 | ✅ Step 2（误判）| ✅ **独立根因**（store 生命周期，非 deserialize）| 5983bca |
| `plugin_contract --format`（独立 CLI 选项漂移）| 1 | ❌ 归 #73 | ❌ 归 #73 | — |

**结果**：8 pre-existing 失败 → 1（仅 plugin_contract）；1704 passed，零新增失败。

## 5. 风险与设计合规

- **migration.py 兼容**：走 `"channels" in data` 分支 → 仍构造 CheckpointEnvelope，历史迁移路径不受影响
- **消费者安全**（前置报告 §4）：无消费者硬依赖 `load().state` 必为 CheckpointEnvelope（show 容忍 dict/对象；resume 用独立 --state-file）
- **design-inviolability**：本修复是「补代码使 deserialize **真能保真** EngineState」，对齐设计意图（EngineState 是主循环权威状态，checkpoint 应保真存取），**非降级**。不翻转任何 BEACON 决策
- **dispatch marker 稳健性**：Step 2 前加断言验证 `asdict(EngineState())` 无 `channels` 键（防未来字段命名冲突）
