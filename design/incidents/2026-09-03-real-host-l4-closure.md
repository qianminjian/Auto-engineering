# 2026-09-03 真实双宿主 L4 收敛记录

## 结论

候选 Build `5.8.0-rc.5+sha256.861234fbacd6a5c2` 已在全新临时项目分别通过 Codex 与 Claude Code 原生入口的真实 L4。两条轨迹均由设计文档输入连续运行到 `TERMINAL/GOAL_ACHIEVED`，没有人工续接、Python Supervisor 或第二套协调循环；所有生成的 Host outcome journal 均为 `accepted`。

本记录不把 Core 的终态误报为发布通过：本轮宿主命令没有同步产出 `scripts/product_acceptance.py` 所要求的完整 usage、machine claims 和 evidence artifact hash，因此 A008 仍需补齐发布证据包。

## 运行与事实

| 宿主 | 全新项目 | 阶段轨迹 | Core 结果 | Build Identity |
|---|---|---|---|---|
| Codex | `/private/tmp/ae-real-golden-repair-quz3TX` | gap_scan → architect → developer → critic → component_verifier → system_deep_audit | `TERMINAL/GOAL_ACHIEVED` | `5.8.0-rc.5+sha256.861234fbacd6a5c2` |
| Claude Code | `/private/tmp/ae-real-claude-repair-H4c77T` | gap_scan → architect → developer → critic → component_verifier → system_deep_audit | `TERMINAL/GOAL_ACHIEVED` | `5.8.0-rc.5+sha256.861234fbacd6a5c2` |

两条轨迹的 EventStore 最后事件均为 `LoopCompleted`；Codex 产生 4 个 accepted outcome journal，Claude Code 产生 7 个 accepted outcome journal。最终 `dev-loop --status --format json` 的 `runtime_revision.engine_build_id` 均与候选 Build 一致。

## 本轮修复对应的真实验证

T751 修复了真实宿主在首次 Coordinator assembly rejection 后容易中断的三处问题：

1. 首次 rejection 之前已认证的 Worker facts 不再从 journal 丢失。
2. 多 Worker partial snapshot 只允许以未改变的事实追加，不能覆盖当前完整结果。
3. Core error 或 rejection 时不提前删除 Action work files，修复包可继续提交；只有 Core 接受后才清理。

## 后续发布动作

使用同一候选 Build 重新运行结构化 evidence collector，至少绑定 Marketplace 来源、`source_build_id`、完整内容摘要、Build Identity preflight、usage 数字证据、machine claims、action receipts 和 artifact hash；随后串行执行：

```bash
python3 scripts/product_acceptance.py \
  --evidence <codex-evidence.json> \
  --evidence <claude-evidence.json> \
  --archive <candidate-release.tar.gz>
```

只有该命令返回双宿主 `L3/L4: pass`，才可关闭 A008 和发布门禁。

## 2026-09-05 T781-T782 宿主合同复验

候选 `5.8.0-rc.5+sha256.da7bae7c9ba1fef7` 的代码质量门禁为全量
`2978 passed, 1 skipped`、覆盖率 `90%`、Ruff/mypy/compileall/git diff check 通过，
Codex/Claude archive smoke 与安装验收均通过。

本轮新增两条确定性边界：

1. final43 真实 Claude Worker 已完成代码和测试，但把 `batch_id` 放在私有 envelope 顶层，
   Core 以 `WORKER_BUSINESS_BOUNDARY_VIOLATION` 拒绝，证明宿主不能替 Worker 扁平化或手工重构业务结果。
2. final44 真实 Claude 使用了 root-bound native-result 的绝对路径表示，旧 Hook 误以字符串差异
   拒绝；T782 改为在项目根内规范化比较，越界路径仍拒绝。final45 随后证明另一条边界：
   Coordinator 把额外 Worker 正文拼接到固定 `native_launch_prompt`，Hook 正确拒绝并记录
   `HOST_WORKER_ATTESTATION_MISSING` Stop Report；该轨迹不计为 L4 成功。

因此当前结论仍是：Core 单 Tick、单 Coordinator、同 Action repair 和 fail-closed 语义没有被
放宽；剩余阻断属于真实宿主必须原样消费机器合同，以及完整 usage/native-result/product evidence
尚未形成，不允许用手工修复或前缀匹配掩盖。

## 2026-09-03 当前候选复验补充

候选 Build `5.8.0-rc.5+sha256.4e1ccf77725f8355` 的新鲜真实轨迹结果如下：

| 宿主 | 结果 | 证据 | 发布门禁结果 |
|---|---|---|---|
| Codex | `TERMINAL/GOAL_ACHIEVED` | Architect/Developer/Critic 三阶段 usage 均绑定真实 Action；缓存输入约 `10.46M` | 拒绝：超过 `1.5M` |
| Claude Code | `TERMINAL/GOAL_ACHIEVED` | 三阶段 usage 均绑定真实 Action；CLI 结构化回报真实成本 `11.79290725 USD` | 拒绝：超过 `2 USD` |

本轮还发现两个会造成“看起来中断”的具体边界：

1. `ArchitectHandler` 原先没有声明 token 采集，导致架构阶段事实缺失；已修复并由回归测试与真实 Codex/Claude 轨迹验证。
2. Claude 一次结构化输出轨迹在 Architect 结果合同修复阶段提前结束。Core 已保留同一 Action 和 accepted Worker journal，但 Host Driver 仍需把 repair action 持续提交到 Core 接受，不能依赖模型自行决定是否继续。

因此当前判断是：代码级循环和同 Action recovery 已通过；产品发布仍被真实预算及 Host Driver 持续驱动门禁阻断，不能把 `TERMINAL` 直接表述为发布通过。

## T753 最新候选 Claude 复验

候选 Build `5.8.0-rc.5+sha256.00ab0a955abaf90e` 在全新项目
`/private/tmp/ae-real-claude-t753-final-lOqkSq` 的 Claude 原生入口完成连续 6 ticks：
`project_setup → gap_scan → architect → developer → critic → done`。EventStore 最后事件为
`LoopCompleted`，Core verdict 为 `GOAL_ACHIEVED`，Developer 5/5 测试通过，Critic
`APPROVE`，且设计文件摘要未改变。

该轨迹仍不能关闭 A008：plain Claude 入口没有在项目 `.ae-state` 形成 Usage Ledger，
`scripts/collect_product_evidence.py` 对同一项目和 Build 返回 `USAGE_MISSING`。这不是运行
失败，而是产品证据不完整；必须由 Host Adapter 采集并绑定真实 Action usage 后，才能进入
`product_acceptance.py`，禁止用 CLI 文本、估算费用或人工补写数字替代。

## T753：宿主返回边界补强

为处理上述 Claude 结构化轨迹提前结束问题，Host Action 现携带统一的
`host_execution.continuation` 合同。宿主调用返回（包括空结果、非零退出或模型提前给出
成功文本）后，必须先执行 `ae-run dev-loop --status --format json`；若 Core 仍返回
`CONTINUE` 或仍存在 active Action，只能按 `resume_active_action` 恢复同一 Action，继续
其已绑定的 finalize/validate/submit 或 Worker 操作。

这条规则是宿主返回边界的 fail-closed 闸门：不能把进程退出当作 Loop 终态，不能重跑已经
落盘的 Worker，也不能启动第二个 Coordinator。它不把 Python 变成长驻任务驱动器，不改变
单 Tick/单 Coordinator 设计，也不放宽真实缓存和费用预算门禁。

## T753 后最新候选包

T753 的工作文件运行时修复随后重新构建候选包：
`5.8.0-rc.5+sha256.00ab0a955abaf90e`。该包在宿主调用 Action 前预创建
`outcomes/coordinator_result/result` 的父目录，并对真实路径执行项目根约束检查；这个动作不
写 EventStore、不创建 Result、不伪造 Worker outcome。前一轮真实 Codex T753 轨迹使用前一版
候选包已到 `TERMINAL/GOAL_ACHIEVED`，新包的 Codex/Claude 双宿主产品证据和预算门禁仍待
串行复验，因此 A008 继续保持进行中。

## T754：真实 Codex 组件身份错误的结构化收口

在候选 `5.8.0-rc.5+sha256.00ab0a955abaf90e` 的真实 Codex 轨迹中，Critic 原生回包的
`assurance_bundle.component_verification.component` 使用了业务模块名
`counter_canary`，而 Core 当前 canonical 组件是 `Goal`。旧实现先写入了错误的
`ComponentCompleted` 事实，随后 guardrail preview 才抛出原始
`COMPONENT_IDENTITY_MISMATCH` traceback；宿主靠恢复重试后才最终到达终态，这正是“容易
中断”的典型边界。

修复后的行为是 fail-closed 且可恢复：`TransitionContext` 将当前 Core 组件身份显式交给
Critic；Assurance 在产生任何领域事件前严格比较 expected/actual component。不一致只返回
`ASSURANCE_COMPONENT_IDENTITY_MISMATCH`，保留同一 Action 的 Coordinator repair，不自动
改名、不写错误完成事实。同时，`native_outcomes_are_ready` 已下沉到 `worker_evidence`
canonical 边界，Host-only 或损坏的 shared `outcomes.json` 不能被提升为原生完成结果；Assembler
只可修复工作副本，Outcome Journal 仍是事实源。

本轮代码验证：候选 Build `5.8.0-rc.5+sha256.1e0973e2a69cf49a`；全量
`2882 passed, 1 skipped`，覆盖率 `90%`，Ruff/mypy/compileall/check-gate 通过。A008 的
真实双宿主复验仍需绑定该新 Build；发布门禁继续拒绝缓存/成本证据超限或缺失的结果。

## T755：Setup 命名漂移修复后的真实复验

T755 将 Node `LocalProbeProvider` 的 `type_check` 纳入 canonical 别名集合，修复了
“Action 指导宿主写入 `type_check`，Profile 却只识别 `typecheck`”这一直接导致
`PROJECT_SETUP_RETRY_EXHAUSTED` 的实现缺陷。该修复后重新构建候选：
`5.8.0-rc.5+sha256.2470e8991e9c3dbc`，并分别安装到 Codex/Claude 本地产品入口。

### Codex

全新项目 `/private/tmp/ae-real-codex-t755-fix1-JNeSN9` 的 Setup 已不再因
`type_check` 缺失而耗尽：宿主按合同建立了 Python `pyproject.toml`、pytest smoke、
`src/__init__.py`，并在唯一一次 Setup 修复中使 pytest、ruff、mypy、wheel build 全部通过。
随后 Codex API 的响应流连续发生 TLS/HTTP 断开，宿主最终 `turn.failed`；回查 Core 仍为
`project_setup_required`，active Action 与 `resume_active_action` 完整保留，未伪造
`TERMINAL`，也未创建第二个 Loop。该部分属于外部传输阻塞，不归因于 Core 状态机。

### Claude Code

第一次使用含歧义的极简设计输入时，Claude 正常到达 `gap_review / WAIT_USER`，原因是设计
未定义方法签名；这验证了用户 Gate 仍然不会被宿主自动代选。随后使用明确签名、类型约束和
测试行为的设计输入，在全新项目 `/private/tmp/ae-real-claude-t755-fix2-o4iNnU` 完成：
`project_setup → gap_scan → architect → developer → critic → done`，Core 状态为
`GOAL_ACHIEVED`，30/30 测试、mypy、ruff 通过，无用户 Gate、无 traceback、无第二套循环。

对该项目运行真实证据收集器返回 `CLAUDE_COST_EVIDENCE_MISSING`。因此 Claude 的 Core L4
已验证，但产品证据尚不完整；没有真实成本数值时不得调用 `--cost-usd` 人工补数，也不能
关闭 A008。候选 Build 的双宿主发布门禁仍保持 fail-closed。

## T756：Gap Scan 阻断无可执行设计层次

T755 的 Codex 复验暴露了另一个更深的契约漏洞：只有 H1 的非结构化 `design.md` 被解析为
没有任何 plate 的设计文档，Gap Scan 却可以用 synthetic `document`、空 gaps 和空
`valid_plate_keys` 进入 Architect。这样既违反“设计文档必须有可执行 H2/H3 或 `ae` 层次”的
既有规则，也会把缺少输入的问题推迟到 Architect，造成宿主反复修复、看似 Loop 中断。

T756 在 Core 的 `validate_gap_analysis` 增加确定性闸门：显式设计文档没有可执行层次且没有
架构 gap 时，同一 Gap Scan Action 直接返回 `GAP_SCAN_DESIGN_STRUCTURE_INVALID`，保留
当前 Loop/Action 供宿主修复；不增加路由 fallback，不放宽 `plate_keys` 非空约束，也不把
Python CLI 变成按任务长驻驱动器。若确有架构 gap，仍沿用原有 Gap Review 流程。

实现与验证：新增回归测试先确认旧行为会错误进入 Architect，再修复至 GREEN；当前工作树
全量 `2883 passed, 1 skipped`，覆盖率 `90%`，`check-gate`、mypy、compileall 和
`git diff --check` 通过。候选 Build 为 `5.8.0-rc.5+sha256.14156d71899d48e2`，归档包
在 Codex 与 Claude 两个宿主的安装验收和 archive smoke 均通过。

### 当前候选的真实宿主结果

Codex 在全新项目 `/private/tmp/ae-real-t756-l4-sBMHRf` 使用结构化设计文档完成
`project_setup → gap_scan → architect → developer → critic → done`，Core 最终为
`TERMINAL/GOAL_ACHIEVED`；独立验收 16/16 通过，ruff、mypy、compileall 通过，设计文档
摘要保持不变，未创建第二个 Loop。此次 Core 结果为 `core_verified_product_unverified`，
因为产品成本/用量证据仍未齐备。

Claude 在全新项目 `/private/tmp/ae-real-t756-claude-nbrjWE` 使用同一候选包时，仍在
Setup 阶段因宿主将 `tests/test_smoke.py` 误判为不允许的范围而连续重试，最终保持
`WAIT_RESOURCE/PROJECT_SETUP_RETRY_EXHAUSTED`，没有伪造终态，也没有进入业务 Architect。
这是宿主 Setup 驱动问题，不是 T756 Core 闸门缺陷。

当前产品证据收集器结果为：Codex `USAGE_MISSING`，Claude `TERMINAL_ACTION_MISSING`。
因此 A008 继续保持进行中；在真实 Claude 终态、两宿主 usage/machine claim 以及产品证据
包全部形成前，不得宣称双宿主产品验收完成或发布候选通过。

## T757：真实 Claude 暴露 Assurance 结构合同不可执行

T757 先修复了 Setup 对合法 Python toolchain smoke 使用 `subprocess`、`sys` 的误判，
然后在新制品 `5.8.0-rc.5+sha256.b07ecc8689b562fa` 上重新运行真实 Claude。Setup、
Gap Scan、Architect、Developer 均能推进；但 Critic 的 `expected_format` 是压缩描述字符串，
没有可复制的 JSON 骨架。宿主因此把 `dimensions[*].findings` 误当成
`system_audit.findings`，并遗漏 `component_verification.component`，Core 正确返回
`ASSURANCE_BUNDLE_INVALID` 并保留同一 Action。

宿主随后连续多轮猜测字段、重写 coordinator result，并重复 finalize/validate/tick，
仍停留在同一 Action；这不是 Core 状态推进错误，而是“机器合同可校验、但对宿主不可执行”
导致的恢复环。T757 已在 ActionBuilder 给 Critic 下发可复制的严格 JSON 示例，并在 Core 错误
中指出两个精确字段路径和修复建议；新增回归与 Assurance 定向回归通过。

本次真实轨迹还确认两个待处理边界：原生 Claude Agent 返回后，宿主没有直接把原始 tool
envelope 送入 `--native-result-stdin`，而是手工重建 native result/outcome；同一 Developer
 Action 内的 B1 Worker 越过自己的 task 目标提前修改了 B2 文件，实际证据显示宿主在一个
invocation 下又创建了嵌套 Worker；当前批次级 allowlist 不能替代 invocation 边界。前者继续
作为 Host Driver 执行纪律与机器化接入问题，T758 已收口为明确禁止嵌套 Agent/Task/协作
调度，并要求 native envelope 无法逐字节转交时立即 `HOST_EVIDENCE_INVALID`；不能靠放宽
校验、人工补字段或增加第二套 task loop 解决。

## T759：产品证据不得从 Core 终态推断原生回包完整

T758 后的真实 Claude 轨迹已经可以稳定完成 `project_setup → gap_scan → architect →
developer → critic → done`，并取得 `TERMINAL/GOAL_ACHIEVED`。但检查 `.ae-state` 发现只有
Critic 留下 native result 暂存，Architect/Developer 仅有私有业务 outcome；同时 usage ledger
没有可供产品门禁消费的完整数字。旧 collector 只依据事件、accepted journal 和 Core done
生成 artifact，并把 `manual_protocol_repairs=0`、`traceability_complete=true` 当作固定事实，
这会把“Core 收敛”错误提升为“宿主回写完整”。

T759 将 collector 改为对每个 Spawn Worker 读取 Action-bound `native_result_path`，校验文件
存在、非空、UTF-8 JSON，并将 `action_message_id/worker_id/path/sha256/bytes` 固化为
`native_result_manifest`；缺失或损坏直接返回 `NATIVE_RESULT_EVIDENCE_MISSING/INVALID`。
验收器同时校验清单结构和重复身份。新增回归后全量 `2887 passed, 1 skipped`、覆盖率
`90%`，双宿主 archive smoke 通过；对本次真实 Claude 项目运行 collector 已按预期
`NATIVE_RESULT_EVIDENCE_MISSING` 阻断。A008 继续保持进行中，不能伪造 artifact、usage 或成本。

## T760：Gap Scan 明确实现边界与 Claude 成本事实闭环

T759 后的 Claude 复验暴露了一个更早的确定性问题：设计文档已明确 `Counter` 的接口、行为
和测试要求，但 Gap Scan 仍以“源码/测试文件不存在”为证据提交了两个设计 Gap，Core 因此
合法进入 `gap_review/WAIT_USER`。这不是用户真正需要做的设计选择，而是把实现状态误当成
设计状态，直接增加了人工停点、Tick 和 token 消耗。

T760 在 Gap Scan 校验层复用 `DesignDocParser` 生成的 DesignItem，对 H3 下的正文条目识别
API、行为和测试契约信号；明确契约章节若被标为 `clarity=missing`，同一 Action 返回
`GAP_ANALYSIS_IMPLEMENTATION_MISCLASSIFIED`，让宿主修正为 clear 并继续 Architect。
普通背景段落仍可作为真正的 vague/partial Gap，不放宽设计缺口 Gate。

同时，产品证据收集不再接受 CLI 的人工 `--cost-usd`。Claude 必须提供原始
`stream-json` 输出，由 `usage_attestation` 解析最终 `total_cost_usd` 与完整 token 字段，
并把文件名、SHA-256、字节数和来源写入 artifact；缺失、截断或字段不全统一
`CLAUDE_COST_EVIDENCE_MISSING`。新增回归覆盖 37 项采集/验收测试和 123 项纵向 Host/E2E
测试；A008 仍需新候选双宿主真实终态，不能用本次旧运行的 `$9.96` 成本或手工数字通过预算。

## T761：宿主预算耗尽绕过 Stop Hook，留下 CONTINUE lease

在新候选 `5.8.0-rc.5+sha256.bf75b4785c1c4bca` 的真实 Claude 运行中，使用原生
`--output-format stream-json --max-budget-usd 2`，宿主最终返回 `is_error=true`、
`stop_reason=budget_exhausted`、实际 `total_cost_usd=2.02827`。这是宿主确实结束，不能被
当作 Loop 成功；超过 2 美元的一个推理单位属于宿主预算边界行为，产品证据仍按预算失败。

但退出后 Core 状态仍是 `project_setup` 的 `project_setup_required/CONTINUE`，
`.ae-state/host-runtime/active-lease.json` 仍存在，且没有 Stop Report。根因不是 Core
多建了一条循环，而是 Claude `-p` 这条退出路径没有执行现有 `Stop` hook；旧实现没有
`SessionEnd` 生命周期边界，因此无法把“宿主结束但 Core 尚未终态”记录为机器事实。

T761 增加 Claude `SessionEnd` hook 与共享 `HostStopReport`：仅当同会话持有不可让出的
`CONTINUE` lease 时，按 Action/thread/session/build 生成有界 JSON，记录事件原因，条件清理
匹配 lease，并返回稳定 `HOST_SUPERVISOR_PROTOCOL_ERROR`。不会推进 Tick、伪造 Result、重启
Worker 或引入 Python Supervisor；异会话、终态/等待 lease 不会被误清理。产品 collector
现在将该报告计入 `unexpected_stops`，恢复后的终态也不能被包装成“无中断成功”。

本次实现定向回归 `90 passed`，但 `SessionEnd` 是否在目标 Claude `-p` 预算退出路径稳定触发，
仍需在新制品上做一次真实宿主验证；在此之前 A008 保持未关闭。

## T762：原生生命周期 Hook 仍不能覆盖硬限制退出

在 T761 的 `SessionEnd` 与 `StopFailure` 都注册后，真实 Claude `-p` 预算退出仍然表现为：
原始 stream-json 有 `is_error=true`、`terminal_reason=budget_exhausted`，但项目只留下
`CONTINUE` lease，没有 Stop Report。这与 Claude 文档关于硬限制/会话结束前 Hook 可能来不及
执行的说明一致；因此 Hook 是加固路径，不是可靠的进程退出通知。

T762 增加 `scripts/ae-host-run` 进程边界适配器。它接收 `--project-root`、`--output` 和
`--` 后的宿主命令，保存原始宿主输出，进程退出后调用一次
`auto_engineering.host.process_exit`。该模块只读取最终回包的 session/reason，校验它与
当前 lease 一致，再复用 HostStopReport 条件清理 lease；不创建 Action、不调用 Tick、不启动
Worker，并原样返回宿主退出码。真实临时项目用该适配器已生成 Stop Report 并清理残留 lease。

因此，L3/L4 的非交互 Claude 入口必须使用适配器；产品 evidence 的 `host-output` 指向它保存
的原始 stream-json 文件。直接 `claude -p` 只能作为诊断实验，不能作为无中断产品验收证据。

## T762 收口：final8 候选与真实边界验证

候选 `5.8.0-rc.5+sha256.4d2512b0d5112e2d` 已完成代码收口：全量
`2905 passed, 1 skipped`，覆盖率 `90%`，Ruff、mypy、check-gate 通过；Claude Code 与
Codex 的归档 smoke 均通过，并已安装到本机两个宿主。旧的 `hooks-cc.json` 已删除，Claude
生命周期入口统一为 `hooks/hooks.json`，非交互运行统一经过 `scripts/ae-host-run`。

真实 Claude 边界测试证明适配器行为正确：预算退出保留宿主原始非零退出码，生成绑定
Action/thread/session/build 的 Stop Report，并只清理同会话 lease；随后在同一临时项目恢复时
复用原 active Action，未重新创建 Python Supervisor、第二套 Tick 或伪造 Worker 事实。由于
真实预算运行仍在宿主预算边界退出，尚未得到双宿主完整 native-result manifest、终态和可信
usage evidence，A008 继续保持进行中。

对该真实项目执行 final7 的 evidence collector，实际返回
`NATIVE_RESULT_EVIDENCE_MISSING`；这证明 collector 在缺少完整原生 Worker 回包时确实
fail-closed，而不是把 Core 状态、宿主退出码或人工补录数字当作产品成功证据。

## T763-T764：产品成本门禁与证据策略和 Loop 预算职责分离

复核发现产品验收器曾把 Claude 成本上限 `$2.0` 写死在 validator 内，而设计决策 D55
规定默认预算策略为 soft，显式 hard limit 只能是外部策略。该硬编码会把“验收命令预算太小”
误判为“Loop 产品失败”，也无法支持完整 L4 的真实测量。

T763 保留默认 `$2.0` 兼容行为，同时新增 `--max-claude-cost-usd`，在单宿主和双宿主
验证链路中只校验并传递一次，拒绝 NaN、无穷和负数；L4 手册要求把本次策略显式留档。
T764 进一步把同一策略写入 collector 生成的外层 evidence 和内容寻址 artifact；validator
校验两层声明一致，旧版缺少该字段的 artifact 仍保持读取兼容。该变更没有放宽 Loop 的
运行时事实，也没有引入第二个 Coordinator 或重试循环。
