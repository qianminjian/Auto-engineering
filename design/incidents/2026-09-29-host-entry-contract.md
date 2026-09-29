# 2026-09-29 真实宿主入口输入契约事故

## 结论

本次 Claude Code Canary 没有进入 Loop 的 Worker 或 Stage 执行阶段。宿主收到的是没有
具体业务范围、没有显式设计文档路径的泛化口号，随后先调用 `dev-loop --status`。新项目
没有活动 EventStore thread，因此 Core 正确返回 `EVENT_THREAD_NOT_FOUND`；外层适配器按
“禁止 status-first、不得自动创造第二个 Coordinator”的合同退出。它不是 Tick 死循环，
也不是 EventStore、Worker 或 watchdog 崩溃。

## 原始证据

- 宿主命令：`/auto-engineering:dev-loop "执行设计驱动工程闭环，严格遵守 Action 合同。"`
- 运行时：安装后的 `5.8.0-rc.5+sha256.ef5b27f4d7b5e45a`，未加载工作区源码插件。
- 首个可见 Core 行为：`dev-loop --status`。
- Core 返回：`EVENT_THREAD_NOT_FOUND`，没有活动 thread。
- 适配器结果：`Core 状态回查失败，禁止自动续驱动`，退出码 `75`。
- 事实边界：没有创建 Action、没有 Worker、没有 Result、没有 Tick 事实；只创建了项目
  运行时 bootstrap 和原始宿主 stream。
- 资源影响：本次真实宿主尝试消耗约 `70,981` input tokens、`740` output tokens，
  记录成本约 `$0.721933`；该成本属于入口契约失败，不应归为 Core 运行失败。

## 根因分层

1. Runbook 使用了“执行闭环”口号，却没有把 Canary 的具体 requirement 和 `design.md`
   明确交给宿主。
2. Skill/Command 虽然规定首个 Core 命令必须是 `--init`，但没有把“泛化输入不得执行
   status”写成可检验的入口拒绝规则，模型在输入不足时自行选择了 status-first。
3. 真实验收缺少一个静态契约测试，未能阻止 Runbook 漂回泛化命令。

## 修复与不变设计

- Runbook 明确要求 fixture 使用 `design.md`，并把具体 requirement、`--design-doc design.md`
  和“首个命令必须 init”写入真实 Claude 命令。
- Skill/Command 对缺少具体 requirement 或设计文档的请求返回
  `HOST_ENTRY_INPUT_REQUIRED`，禁止 status/find/rg 探路。
- `EVENT_THREAD_NOT_FOUND` 保持原语义：只有显式 `--init` 才能在新项目创建第一条
  EventStore thread；不增加旧 Supervisor、Round、第二套恢复逻辑或隐式自动初始化。
- 真实宿主需要重建同一制品并重新执行 L3；本事故证据不能计入 L3/L4 通过。

## 验收

While a fresh real-host Canary has `design.md` and a concrete requirement, when the host starts
the dev-loop Skill, the first Core operation shall be `dev-loop --init ... --design-doc design.md`;
when either input is missing, the host shall report `HOST_ENTRY_INPUT_REQUIRED` before any status
probe; no `EVENT_THREAD_NOT_FOUND` from a status-first attempt shall be counted as a Loop crash.

## 修复后复跑

使用 T899 Build `5.8.0-rc.5+sha256.1bc6c3d3af954990`、全新项目和显式 `design.md` 重新
执行后，Core 创建了 thread `b68bd553-29b5-4b00-ad40-3d4f1597d6f5`，首个 active Action
为 `project_setup_required`，`runtime_identity.status=match`。这证明入口已经进入
`--init`，没有再发生 status-first 的 `EVENT_THREAD_NOT_FOUND`。随后外部模型连续只产生
thinking 事件，未执行 project setup 工具；`ae-host-run` 在 30 秒 idle、2 次有界恢复后
以 `HOST_PROCESS_IDLE_TIMEOUT` 结束，并保留 `CONTINUE` Stop Report。这是外部宿主进展
不足，不是 Core 中断或状态损坏。
