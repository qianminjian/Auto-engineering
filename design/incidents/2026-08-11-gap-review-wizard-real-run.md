# 2026-08-11 Gap Review 向导与主链路真跑事故

## 事实来源

- 外部报告：`voice_clone_for_auto_CC_Design/_scratch/real-run-report-gap-review-wizard.md`。
- 线程：`a291ff5c-3f45-4cca-a084-110b1e047190`。
- Tick 2 `gap_scan` 从 44 个标题识别 8 个 gap；Tick 3 `gap_review` 返回
  `WAIT_USER/gap_decisions_required`，但 Action 只给批量 gaps 与统一 resolution。
- Critic 对 B01 返回 `MAJOR` 后，下一 developer Action 曾触发事件重放投影不一致。
- 本事故资产只保留脱敏协议事实，不依赖外部测试项目持续存在。

## 修复结论矩阵（2026-08-12）

| ID | 当前判断 | 代码证据与处理 |
|---|---|---|
| AE-01/02 | resolved | Core 单项持久化 wizard；增强 gap 证据、影响、推荐、选项与阻塞规则 |
| AE-03/04 | resolved | `batch_title` 与 `plate_keys[]` 分离；Action 注入 `valid_plate_keys`，旧 `component` 只读兼容 |
| AE-05 | resolved | `StageAdvanced` reducer 清理来源 Stage 临时字段；真实 EventStore MAJOR→Developer 回归通过 |
| AE-06 | resolved | `stage-result.schema.json` 接受并投影 `strengths/assessment`；Critic expected format 同步 |
| AE-07 | resolved | 声明范围内 untracked/无 Git 文件可作为证据；不相关文件拒绝；setup 禁止隐式 Git 变更 |
| AE-08 | resolved | 有证据时预检 ESLint 9 flat config 与 Vitest jsdom 直接依赖；其余框架能力不猜测 |
| AE-09 | resolved | T429 已将静态 contract 扫描降为 advisory，可执行 contract test 才权威通过 |
| AE-10 | resolved | 已知投影异常输出 `STATE_PROJECTION_MISMATCH` Error Action；未知异常继续 fail-closed |

## 设计不变量

1. Gap Review 是 Core 持久化的单项向导，不依赖宿主聊天内存保存进度。
2. 每次 Action 只聚焦一个 gap，提供证据、问题、影响、推荐、理由、置信度与合法选项。
3. 当前 gap 未形成合法决策时不得移动游标；恢复必须回到同一 gap。
4. Research 与 Fill 必须绑定原 gap；最终审计保留推荐与用户决策，不伪造默认选择。
5. 人类可读标题与 Core 稳定路由标识分离；Schema、expected_format、运行时白名单同源。
6. 新项目可用未跟踪文件作为 developer 变更证据，但 Core 不隐式 stage、commit 或改 Git 历史。
7. 所有修复必须覆盖 EventStore 提交、重放、跨进程恢复与结构化错误边界。

## 关闭标准

- AE-01 至 AE-07 有 RED→GREEN 回归或明确证明已由既有任务关闭。
- Gap wizard 在 Claude/Codex 共用 Action 上语义一致，用户一次只需决定一个 gap。
- Critic MAJOR→Developer、Research→当前 gap、无 Git/未跟踪新项目均有真实轨迹。
- 全量、coverage、Ruff、mypy、规则同步和双宿主 archive smoke 通过。

## 关闭证据（2026-08-12）

- AE-01~10 均已修复或由 T429 的既有权威语义确认关闭。
- 444 项相关组合回归通过；全量测试运行至 100%（1 skipped）；coverage 90%。
- Ruff、mypy、规则同步与 `git diff --check` 通过。
- 同一 release archive 的 Claude Code/Codex smoke 均通过；真实产品长跑仍由发布门禁独立跟踪。
