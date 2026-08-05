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
2. while action.action != "done":
     print "[Tick N | stage <action.stage>] ..."
     if action.action == "error":
         report action.error_code + action.message
         STOP
     if action.action in {"gate", "skip"}:
         action = ae-run dev-loop --tick
         continue
     if action.action == "session_rollover":
         stop all work in the old session
         create a fresh host session and load only action.capsule
         submit {stage:"session_claimed", claim_token, session_id, host}
         if native session handoff is unavailable: fail closed
         continue with the original active Action returned by Core
     read action.instruction
     if action.stage == "gap_review" and action.interaction_mode == "single_gap":
         show only action.current_gap and ask exactly one Fill/Research/Defer decision
         submit decisions with exactly one item; never batch-write defaults
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
3. report action.verdict and fresh verification evidence
```

非终态 Action 都是 `continuation_required`：宿主必须提交当前 Result 后继续读取下一个
Action。Core 不运行后台 daemon；若宿主暂时不能继续，应报告等待的 tick/stage 和恢复命令，
不得把“已输出 Action”当作完成。

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
