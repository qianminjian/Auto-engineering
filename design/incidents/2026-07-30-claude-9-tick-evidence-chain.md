# Claude Code 9-Tick 真跑证据链分析

> 运行日期：2026-07-30｜分析日期：2026-07-30
> 状态：根因已确认，Phase 71 自动门禁完成，待真实产品复验
> 严重度：P0（自动运行连续性与审计证据可信度）
> 证据来源：目标项目 `_scratch/reports`、`_scratch/debug`、`_scratch/prompt-log`

## 1. 结论

本次运行只完成 B1 后在 Tick 9 输出 `session_rollover/tick_limit`。该停机来自
Phase 70 之前的插件构建：原始 Action 没有 `context_manifest`，Worker 仍内联
`subagent_prompt`，并保留固定 8 Tick session 限额。固定 Tick 停机、正常会话交接
和主要 Prompt 重复已由 T341-T349 修复，不能据此认定当前源码仍会在 Tick 9 停机。

真跑证据同时确认当前源码仍有三个独立缺陷：

1. DebugTracer 文件使用 0-based 编号，和 Action/metrics 的 1-based Tick 错位。
2. 首次 Architect 计划未把 task 总数物化到设计进度树，出现 total=0、done=5。
3. Prompt/debug 制品缺少引擎版本；Phase 70 改用 `prompt_ref` 后，Markdown 仍只展示
   旧内联 `prompt`，无法审计 Worker 引用。

## 2. 关键证据

| 证据 | 观察 | 判断 |
|---|---|---|
| Tick 9 Action | `session_rollover`, reason=`tick_limit` | 旧固定 Tick 行为 |
| Prompt Action | 无 `context_manifest`/`prompt_ref` | 运行构建早于 Phase 70 |
| Debug 文件 | `tick-0000` 内 Action tick=2；`tick-0007` 内 Action tick=9 | Debug 编号少 1 |
| Progress tree | system `total_tasks=0`, `done_tasks=5` | 首次 plan 未同步 task totals |
| Batch plan | 9 batches / 37 tasks | 总任务数来源明确，不应为 0 |
| Prompt JSON/MD | 无 engine version | 无法仅凭制品确认插件构建 |
| Worker 日志渲染 | logger 只读取 `agent.prompt` | 新 `prompt_ref` 会显示 0 chars |

Prompt JSON 共 9 份，最大单份约 15 KB；三次 Research 各约 7 KB，Developer Action
约 15 KB。本次样本没有宿主 input/cache/output usage，不能推断账单成本或
auto-compaction 是否发生。

## 3. 非问题与边界

- 报告中的 contract Gate FAIL 是“当前没有契约定义”的信息性结果；其他强制 Gate
  已通过，不能仅凭该字段认定 Core 绕过失败 Gate。
- Research 分三个 gap 逐 Tick 执行符合 Phase 0 状态机；重复的稳定角色指令由宿主
  cache 和 Phase 70 ContextManifest 观测，不以减少 Research 正确性换成本。
- 本报告不修改目标 voice clone 项目，不把 archive smoke 当真实产品复验。

## 4. 根因与任务

| 根因 | 修复任务 | 验收出口 |
|---|---|---|
| Debug 调用传入原始 0-based `tick_no` | T351 | Debug/metrics/Action 使用同一 1-based 编号 |
| `from_design_doc()` 后未应用首次 batch totals | T352 | 37 tasks 聚合到组件、板块和系统 |
| 诊断制品不声明构建版本 | T353 | JSON/Markdown 显式 engine/protocol version |
| Logger 未适配 `prompt_ref` | T353 | 展示引用和 hash，不重新内联正文 |
| 发布证据不足 | T354 | 全量、双宿主 archive 后再安装 rc.3 真跑 |

## 5. 关闭标准

1. 回归测试先稳定复现上述三个缺陷，再由实现转绿。
2. 全量测试、Ruff、mypy、规则同步和双宿主 archive smoke 通过。
3. 发布候选版本提升，真实 Claude Code 安装信息与 Prompt/Debug 制品版本一致。
4. 下一次真实运行不少于 150 Tick，零人工交接、零输入超限、进度守恒；宿主未暴露
   compaction 信号时记录 unknown，不自行推断。
