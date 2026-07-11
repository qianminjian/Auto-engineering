# Phase 3 T9 — TickOrchestrator CLI 接线执行子计划

> 创建：2026-07-11 | 触发：Phase 3 关键路径（v5.6 Tick 引擎未接入任何运行入口）
> 权威设计：`v5.6-Design-Loop.md` §A.1（Python 永不调 LLM）/ B13（CLI 契约）/ C.3（file-bridge）/ C.5（tick）
> 范围：T9（--init/--tick CLI + 跨进程 restore + A3 写侧）。T9b(progress CLI)/T10(command 重写)/T10c(PR backend)/T10d(语义移除) 后续独立。

---

## 1. 根因（为何 Tick 引擎端到端跑不通）

`TickOrchestrator.init()/tick()` 假定 `self._state`/`_router`/`_judge`/`_batch_state`/`_progress_tree`/`_design_doc` 都在**内存**。但 v5.6 进程模型是**每次 `--tick` 独立进程**（§A.1 表：「每次 Python 调用是独立进程，从 SQLite 恢复状态」）。当前**无任何 restore 路径** → 新进程 `self._state = None` → `tick()` 立即崩。

**耦合确认**：A3 `batch_state_json` 零写（`_display_progress` 只写 `progress_tree_json`），且无 restore → 写而不读回是半措施。故 A3 写侧必须与 restore 一起落地。

## 2. CLI 契约（B13，L198-202 权威）

| 命令 | 行为 | 输出 | 退出码 |
|------|------|------|:---:|
| `ae dev-loop --init "req" [--design-doc <path>]` | 初始化 loop，返回第一个 action | action JSON (stdout) | 0/1 |
| `ae dev-loop --tick --result <file>` | 处理一个 tick，返回下一个 action | action JSON (stdout) | 0/1 |
| `ae dev-loop --status` | 查询当前 tick 状态 | state JSON | 0 |
| `ae dev-loop --resume <id>` | 从 checkpoint 恢复 | action JSON | 0/1 |
| `ae dev-loop "req"` | v5.5 legacy 调试（连续 while，调 LLM）| RunResult JSON | 0/1/2/130 |

- action JSON 到 **stdout**（契约）；进度/日志到 **stderr**（`_display_progress` 已遵守，L1007）。
- legacy `ae dev-loop "req"`（无 --init/--tick）保留 → v5.5 路径（T10d 退役时再移除，本任务不动）。

## 3. 步骤清单（TDD Red→Green，每步一 commit）

### T9a — TickOrchestrator 跨进程 restore（核心）
新增 `TickOrchestrator.restore(project_root, checkpoint_store, *, checkpoint_id=None) -> TickOrchestrator`（无 id → load_latest）：
1. 构造实例（同 `__init__` injectables）。
2. `ck = store.load_latest()` 或 `load(checkpoint_id)`；无 → raise `AEError(CHECKPOINT_NOT_FOUND)`。
3. `self._state = EngineState.from_dict(ck.state)`（ck.state 经 deserialize 已是 EngineState；若为 EngineState 直接用，若 dict 则 from_dict — 兼容两形）。
4. `self._round_history = ck.history or []`。
5. rehydrate：
   - `_batch_state` ← `BatchState.from_dict(json.loads(state.batch_state_json))` if 非空 else None。
   - `_progress_tree` ← `ProgressTree.from_dict(json.loads(state.progress_tree_json))` if 非空 else None。
   - `_design_doc` ← `DesignDoc.parse(state.design_doc_path)` if 非空 else None。
   - `_router = StageRouter()`；`_judge = ConvergenceJudge(ConvergenceConfig(max_iterations=<持久化的 max_rounds 或默认5>))`；`_gates = _load_default_gates()`；`_checkpoint_mgr = CheckpointManager(store)`；`_guardrail = guardrail or GuardrailChain.default()`。
   - `_last_batch_id ← _resolve_batch_id()` 派生或存 state（若无字段则 None，tick 内重算）。
- **max_rounds 持久化**：EngineState 无 max_rounds 字段 → 决策：restore 用默认 5（与 init 默认一致）；如需精确恢复，另立小任务加字段（本步不扩 schema）。
- **RED**：`test_tick_orchestrator_restore_roundtrip` — init(req) → 手动 setattr batch_state → save → `restore()` 新实例 → `_state.thread_id`/`_batch_state.current_batch_id()` 保真。
- **验收**：restore 后 `_state`/`_batch_state`/`_progress_tree`/`_design_doc` 非 None 且字段保真。

### T9b — A3 写侧（_save_checkpoint 前序列化 batch_state）
`_save_checkpoint` 或其调用点前：`if self._batch_state: self._state.batch_state_json = json.dumps(self._batch_state.to_dict(), ensure_ascii=False)`；progress_tree_json 同理兜底（`_display_progress` 已写，但非每 tick 展示 → 在 save 前补写保证一致）。
- **RED**：`test_batch_state_persisted_on_save` — init → 有 batch_state → tick/save → 直接读 checkpoint.state.batch_state_json 非空 + round-trip == batch_state。
- **验收**：save 后 batch_state_json 非空；配合 T9a restore → 跨 tick 游标不归零（关闭 A3 写侧 + T22 跨 tick 恢复）。

### T9c — CLI --init/--tick/--result/--status/--resume
`cli/__init__.py` dev_loop 命令加 flags；`cli/dev_loop.py` 加 `_run_tick_init/_run_tick_step/_run_tick_status/_run_tick_resume`：
- `--init`：construct TickOrchestrator（真实 checkpoint_store=.ae-state/checkpoints.db）→ `init(req, design_doc_path, max_rounds)` → `click.echo(json.dumps(action))`。
- `--tick --result <file>`：`TickOrchestrator.restore(...)` → `tick(Path(result_file))` → echo action JSON。
- `--status`：restore → 输出 state JSON（复用 status.py 契约或 _state 摘要）。
- `--resume <id>`：restore(checkpoint_id=id) → `_build_action()` → echo。
- 互斥校验：--init 与 --tick 不可同时；--tick 必须带 --result；缺失 → click 错误 + 退出码 1。
- **RED**：`test_cli_dev_loop_init_emits_action` / `test_cli_dev_loop_tick_requires_result` （CliRunner，stub checkpoint_store 或 tmp .ae-state）。
- **验收**：`--init` stdout 是合法 action JSON（含 action/stage/thread_id）；`--tick` 无 --result → 退出码≠0 + 错误信息；legacy `ae dev-loop "req"` 仍走 v5.5（回归）。

### T9d — 回归 + 接线证据
- 全量 suite：零新增失败。
- 端到端证据：`ae dev-loop --init "x" --project-root <tmp>` 真跑输出 action JSON（stderr 允许进度）；`--tick --result <fake_result.json>` 推进一个 stage。
- **验收**：total 1704+ passed；tracker Phase 3 T9 ✅ + A3 写侧 ✅。

## 4. 红线/边界

- **不动 legacy**：`ae dev-loop "req"`（无 flag）保留 v5.5，T10d 才移除（避免破坏活跃路径，design-inviolability）。
- **不扩 schema**（除非必要）：max_rounds 恢复用默认值；如需精确另立任务加字段（经确认）。
- **文件桥安全**：--result 文件读走 `_read_and_validate`（已有 C.3.5 error_code 契约）。
- **无新依赖**：全部用现有 EngineState/BatchState/ProgressTree/DesignDoc.from_dict/to_dict（需先确认这些 from_dict/to_dict 存在——T9a 第一步验证）。

## 5. 前置验证（编码前必做）

确认序列化 API 存在且可 round-trip。**执行时修正（2026-07-11）**：实际 API 是 `BatchState.to_json/from_json`（非 `to_dict/from_dict`）、`ProgressTree.to_dict/from_dict`、`DesignDoc.parse`——均存在。`BatchState.from_json(s, design_doc, batch_plan)` 原依赖 `EngineState.batch_plan`(#6) 跨 tick 存活来重建 plates，但 `clear_stage_fields` 在 architect→developer 清空 #6 → 序列化改为**自包含**（batch_state_json 内嵌轻量 batch_plan seed，plates 仍不持久化）。此为「补代码使持久化真能保真」非降级（主设计决策"不存 plates"保留）。
