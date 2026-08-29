# 2026-08-29 真跑：终态、Gap 策略与浏览器能力边界

## 事实

本轮外部业务项目已完成页面、单元测试、lint、类型检查和构建；部分真实外部依赖和业务链路
没有执行，因此该结果不能作为 Loop 完成或产品发布证据。
前台 Supervisor 曾在没有用户 Gate 的情况下退出，而 Core 仍持有 active Action；此前同一
Architect Action 的重复宿主回执已由 T559 修复为 journal 恢复/Coordinator-only repair。
“全部 Research”策略能够逐项向导收集 Gap，但必须对可能改变 binding design 的建议单独 Gate。
浏览器驱动与系统浏览器能力存在差异；该差异属于外部项目环境边界，不应被误判为 Loop
或业务代码失败。

## 根因与设计判断

1. `done` 过去只表达 Core 收敛，缺少业务验收覆盖率和未验证项，容易被宿主误读为产品完成。
2. `remaining_recommendations` 过去只比较推荐 resolution，没有验证推荐是否会改变绑定设计。
3. ProjectProfile 过去只解析 lint/typecheck/test/build，未把浏览器 E2E 命令和运行时能力作为
   有界、只读的前置事实。
4. 外部项目的构建产物纳入 lint 是项目自身配置问题，本项目不把某个前端工具链写死；Loop
   只消费 ProjectProfile 的命令和能力证据。

## 本次修复

- 所有 `done` Action 输出 `acceptance_summary`，明确 `scope=core`、覆盖率、未验证项和
  `release_eligible=false`；产品验收脚本拒绝缺失该边界的终态 artifact。
- Gap recommendation 增加 `requires_user_approval` 约束；字段缺失或为 true 时不生成自动
  决策，伪造的 `thread_policy` Result 返回 `GAP_REVIEW_POLICY_REQUIRES_APPROVAL`。
- ProjectProfile 识别 `browser_e2e` 命令；Action 上下文执行无副作用预检，报告可用的浏览器
  运行时替代来源或 `BROWSER_RUNTIME_MISSING`。

## 关闭标准

- 自动回归、类型、lint、文档同步和 schema 检查全部通过。
- 新 Build 在 Claude Code 与 Codex 分别验证 Gate 等待、同 Action repair、终态摘要和能力
  预检；外部业务链路仍必须以独立 L4 证据确认，不能由 Core 结果替代。
