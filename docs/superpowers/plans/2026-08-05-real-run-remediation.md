# Plan: v5.8 真跑问题整改

> **For agent execution:** follow this plan task-by-task and keep the tracker current.

## Goal

修复 2026-08-05 真跑暴露的状态、路径、交互和门禁可观测性问题，同时把业务缺口转化为可验证的 Architect refine 任务。

## Tasks

### 1. 事实与协议基线

- 读取并锁定 `design/v5.8-2026-08-05-real-run-remediation-spec.md`。
- 在 `design/IMPLEMENTATION-TRACKER.md` 登记本轮 P0/P1 任务。
- 为单 gap review、EventStore status、相对设计路径各添加先失败的回归测试。

### 2. 恢复与状态

- 修改 `TickOrchestrator.init/restore`：以项目根规范化设计文档路径；兼容历史相对路径。
- 修改 `cli/status.py`：优先 EventStore active projection，保留旧 checkpoint fallback。
- 修改 `dev_loop.run_tick_status`：文档失效返回稳定 CLI error code/消息。

### 3. Gap Review 与计划覆盖

- 扩展 EngineState 的 gap review cursor（保持旧 checkpoint 可反序列化）。
- ActionBuilder 只编译当前 gap；GapReviewHandler 接受单项 Result 并继续队列。
- Architect refine 校验 finding_ref 覆盖，阻止“报告已发现但计划无任务”。

### 4. Gate 与宿主协议

- 结构化 Gate subprocess 诊断，避免 `exit=-1` 无上下文。
- ContractGate 按适用性返回 N/A；真实跨模块契约缺失才 hard-fail。
- 更新 `commands/dev-loop.md` 与 Skill，明确 Tick continuation 和 single-gap 交互。

### 5. 验证与交付

- 串行运行相关 pytest（`--no-cov --timeout=60`），再运行全量测试/静态检查。
- 检查 diff、Spec、Tracker、BEACON 状态一致。
- 报告仍需真实宿主重跑；本次不直接修改外部 Voice Clone 业务源码。

