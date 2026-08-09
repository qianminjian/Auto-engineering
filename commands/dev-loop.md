---
name: dev-loop
description: Auto-Engineering v5.8 宿主无关确定性会话 Tick-Based 开发循环
---

# Auto-Engineering dev-loop — 组长执行手册

你是 Loop 组长。Python 引擎负责确定性路由、门禁和收敛；你负责执行 action，
并在需要隔离角色时调用当前宿主原生子代理能力。

> Authority: BEACON #39、#64、#91、#101
> Spec: `design/v5.6-Design-Loop.md`

## 铁律

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `ae-run dev-loop --tick` VALIDATION.
You may NOT edit code before Python outputs {"action":"developer"}.
You may NOT declare done before Python outputs {"action":"done"}.
Violating the letter of this rule is violating the spirit of this rule.
<!-- FRAGMENT:iron_law_gatekeeper END -->

不得跳过或伪造 Gate、子代理执行及验证证据。Git commit、push、PR 只有获得用户
明确授权后才能执行。

## 驱动循环

```text
1. action = ae-run dev-loop --init "<requirement>" [--design-doc <path>]
2. while action.extensions.ae.execution_control.disposition == "CONTINUE":
     print "[Tick N | stage <action.stage>] ..."
     control = action.extensions.ae.execution_control
     if control.disposition == "ERROR":
         report action.error_code + action.message
         STOP
     if action.action == "gate" and control.disposition == "WAIT_USER":
         ask only the options returned by Core, submit the selected gate result
         continue
     if action.action in {"gate", "skip"}:
         action = ae-run dev-loop --tick
         continue
     if control.disposition == "HANDOFF_REQUIRED":
         stop all work in the old session
         create a fresh host session and load only action.capsule
         submit {stage:"session_claimed", claim_token, session_id, host}
         if native session handoff is unavailable: fail closed
         continue with the original active Action returned by Core
     read action.instruction
     if action.stage == "gap_review":
         ask Fill/Research/Defer for every item in action.gaps, in order
         accumulate locally, then submit one complete decisions array for this Tick
         never prefill defaults for gaps that the user has not reviewed
     if action.spawn exists:
         validate HostCapabilities against action.spawn
         if action.spawn.count == 1:
             invoke one worker with action.subagent_prompt
         else:
             read prompt_ref, verify prompt_hash, invoke worker[i]
             require worker[i] to overwrite action.spawn.agents[i].receipt_path,
             recording requested_effort and actual_model (or "unknown")
             collect all receipts, then merge using action.subagent_prompt
         collect real output and build result using action.expected_format
     else:
         execute developer work inline
     ensure result.stage == action.stage
     validation = ae-run dev-loop --validate-result <result-file>
     if validation.action == "error":
         repair the same result file; do not advance or create another Action
         continue
     action = ae-run dev-loop --tick --result <result-file>
3. if control.disposition == "WAIT_USER": ask only for control.reason_code
4. if control.disposition == "TERMINAL": report action.verdict and fresh evidence
```

宿主只按 `extensions.ae.execution_control` 决定继续或停止：`CONTINUE` 必须在提交当前
Result 后立即读取下一 Action；`WAIT_USER` 只询问 `reason_code` 对应的真实决策；只有
`TERMINAL`、`ERROR` 或 `HANDOFF_REQUIRED` 可结束当前自动驱动。Core 不运行后台
daemon，不得把“已输出一个 Action”当作完成。

`STATE_RECONCILIATION_REQUIRED` 是旧状态与本次显式设计文档冲突的用户决策点。
只展示 Core 给出的“重新初始化 / 修复状态并继续”，用户选择前不编辑项目；不得自动
恢复旧 Action、物理删除 `.ae-state` 或替用户选择。
Result 使用 `gate_id=state_reconciliation` 和 Core option id
（`reinitialize` / `reconcile`），`causation_id` 必须绑定当前 Gate message。

启动时不要把设计文档路径作为 requirement 传入。正确写法是：

```bash
ae-run dev-loop --init "实现 Voice Clone 页面" \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

如果设计文档就是唯一需求，可省略 requirement；此时默认执行设计文档的全部内容：

```bash
ae-run dev-loop --init \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

若 requirement 本身看起来是现有 Markdown 文件路径，宿主应停止并要求补充
`--design-doc`，不得继续创建 `design_doc_path=null` 的 architect Action。

## CLI 契约

| 命令 | 输出 |
|---|---|
| `ae-run dev-loop --init "req" [--design-doc <path>]` | 首个 action JSON |
| `ae-run dev-loop --validate-result <file>` | 无副作用 Result 预校验 |
| `ae-run dev-loop --tick --result <file>` | 下一个 action JSON |
| `ae-run dev-loop --status --format json` | 状态 JSON |
| `ae-run dev-loop --resume <id>` | 恢复后的 action JSON |
| `ae-run status --format json` | 统一状态 JSON |

## Spawn 纪律

1. 先读取 `action.instruction`，再读取 `action.spawn.count`、
   `action.spawn.parallel` 和 `action.spawn.effort`。
2. 将 `action.spawn.effort` 视为抽象推理强度。适配层将其映射为宿主支持的
   推理控制；默认使用最低够用的经济档，复杂架构、安全或跨模块故障才提高。
3. 检查 `HostCapabilities.subagents`；并行任务还需检查
   `HostCapabilities.parallel_subagents`。
4. 能力满足时：单 Worker 使用 `action.subagent_prompt`；多 Worker 必须逐个使用
   `action.spawn.agents[i].prompt_ref`（读取后校验 `prompt_hash`），并让每个
   Worker 覆写自己的
   `action.spawn.agents[i].receipt_path`。
   Receipt 超过 Action 策略声明的上限时完整结果进入内容寻址 Artifact Store，
   receipt 仅传有界摘要和 SHA-256 `artifact_ref`；本手册不复制策略默认数字。
5. 多 Worker 的 `action.subagent_prompt` 仅供 Team Lead 合并输出；全部 receipt
   有效后才可覆写共享总 proof，Worker 不得竞争写共享 proof。
6. 能力不足时，报告 `HOST_CAPABILITY_UNAVAILABLE` 并停止，不得 inline 替代
   强制 spawn，也不得把 `"spawned"` 伪造为 true。
7. 按 `action.expected_format` 从真实输出提取字段；只有真实 spawn 完成后才写
   `"spawned": true`。

Codex 宿主必须使用当前会话的实际工具清单完成能力绑定：存在
`collaboration.spawn_agent` 即表示单 Worker 原生能力可用；将 `action.spawn.effort`
传给 `reasoning_effort`，其中 `xhigh` 不得静默降级。并行 Action 按
`action.spawn.count` 创建独立 Agent。不得因为当前回复尚未调用子代理就判定能力不存在；
工具已暴露时，只有真实调用明确失败后才可报告 `HOST_CAPABILITY_UNAVAILABLE`。当
`execution_control.disposition == "CONTINUE"` 时，不得在调用前向用户交回控制。

## 上下文交接

引擎会在 architect、developer、critic 完成后写入 `.ae-state/offload/`。
developer 开始前读取 architect offload，critic 开始前读取 developer offload；
具体路径以 `action.instruction` 为准。

`session_rollover` 只用于异常恢复，不是正常 compaction 或自由文本 recap。旧执行
实例不得继续执行工作；
新会话只读取可校验 ResumeCapsule，提交 `session_claimed` 后才能恢复。宿主无原生
会话创建/接管能力时必须返回 `HOST_SESSION_HANDOFF_UNAVAILABLE`，不得把完整历史
复制到新会话，也不得在旧会话继续。

## 完成状态

| verdict | 含义 |
|---|---|
| GOAL_ACHIEVED | 目标达成，汇报验证结果 |
| QUALITY | 达到质量标准但触及轮次上限 |
| STAGNANT | 多轮没有实质进展 |
| HARD_LIMIT | 达到最大轮次 |
| REFINE_LIMIT | plan_refine 回路超限 |

## 失败透明

- 命令非零退出：读取并报告错误，不静默降级。
- `action == "error"`：报告 `error_code` 和 `message`。
- 连续两次不可恢复错误：停止并建议运行 `ae-run doctor`。

<!-- FRAGMENT:red_flags START -->
## Red Flags — STOP，不要继续，向用户报告

- 我正准备在 Python 输出 {"action":"developer"} 前编辑代码
- 我正准备在 Python 输出 {"action":"done"} 前宣布完成
- 命令执行失败了，我正准备静默切换到手工模式继续
- 宿主原生子代理能力不可用，我正准备自己手工模拟这个 stage
- 我正准备跳过 --tick 自己推进到下一个 stage
- critic 返回 MAJOR，我正准备忽略 findings 直接进收敛

以上任何一条都意味着：停止。向用户报告失败原因 + 状态 + 选项。禁止静默降级。
<!-- FRAGMENT:red_flags END -->
