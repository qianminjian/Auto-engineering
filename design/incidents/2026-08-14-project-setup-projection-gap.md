# Project Setup 投影通道真跑事故

> 日期：2026-08-14｜线程：`6d79b6ad-17ea-41a6-ba86-cbe5c5831ed3`｜状态：根因已确认

## 现象

真实 Codex 插件完成 `project_setup`，Result 预校验通过，但 Tick 在
`TickKernel.compile_commit` 抛出 `UNMAPPED_PROJECTION_CHANNEL: current_stage`，未进入
`gap_scan`。业务项目的 test、lint、typecheck 和 build 均已通过，故障属于 Loop 内核。

## 已核实事实

- EventStore 只持久化了 `LoopInitialized → ProjectSetupRequired → ActionIssued`，失败 Tick
  没有留下部分事件或覆盖 active Action。
- `EVENT_CHANNELS` 已声明 `StageAdvanced` 独占 `current_stage`，因此不能用通用 fallback
  补映射掩盖问题。
- 现有 project setup 单测使用进程内且无 EventStore 的 Orchestrator，没有覆盖 CLI 独立恢复、
  Profile 重探测、显式事件提交和 projection replay 的组合。
- 按报告步骤新增真实 CLI/EventStore 两进程测试后，当前源码可正常进入 `gap_scan`，没有
  复现 projection 错误。
- 故障线程 ActionSnapshot 的 Runtime Vector 是 `action_contract_version=1.0`、
  `engine_build_id=5.8.0-rc.5`；当前源码应为合同 1.1 和内容寻址 Build Identity。
- Codex 本地 Marketplace 缓存包含被复制的 `.venv/bin/ae`，其 shebang 指向源码目录
  `.venv/bin/python3`，而 `scripts/ae-run` 原先无条件优先执行该逃逸入口。

## 根因

插件元数据和 Skill 来自新缓存，但 Python Core 实际由复制进缓存的旧虚拟环境入口启动，
形成“新插件外壳 + 旧 Core 运行时”。因此报告中的 projection 异常属于旧合同实现，不能通过
修改当前 `current_stage` registry 修复。SemVer 相同进一步掩盖了运行时来源漂移。

## 修复

1. `ae-run` 校验 `.venv/bin/ae` 的 shebang 必须词法绑定当前插件 `.venv`。
2. 拒绝逃逸入口后，使用插件专属 `.ae-runtime`，并以 `uv run --frozen --project` 按当前
   插件 `uv.lock` 创建运行时。
3. 删除不受控全局 `ae` fallback；没有可信 venv/uv 时 fail-closed。
4. 新增真实 CLI `init → project_setup → validate → tick → gap_scan` 回归，证明当前
   EventStore/StageAdvanced 路径本身成立。

## 修复边界

只修 Loop 的运行时来源隔离与 CLI 轨迹测试；不修改 Voice Clone 项目，不恢复 legacy
checkpoint 双写，不把 `current_stage` 注册为通用 fallback，也不迁移合同 1.0 的活动 Action。
