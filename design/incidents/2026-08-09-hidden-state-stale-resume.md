# 隐藏状态覆盖显式设计文档的错误续作事故

> 日期：2026-08-09｜状态：已归档，待 Phase 81 修复

## 事实

- 用户在 Codex 中执行 `/clear`，并清理项目可见源码后，再次调用
  `$auto-engineering --design-doc design/V1.0-Design-VoiceClonePage.md`。
- 项目隐藏目录 `.ae-state` 未被清理；`events.db` 仍保存两个 thread。
- thread `fa9c5495-2b78-4889-ad08-56b8446299b2` 的 Projection 为 Developer，active
  Action 为 B2，Architecture revision 为 2。
- Skill 发现 active thread 后恢复旧 B2，没有先把本次显式 design-doc 与当前项目事实比较。
- 旧 init-manifest 使 Profile 看似可恢复；实际 package.json 和原工具链不存在。
- Agent 创建孤立 BFF 文件，并尝试以 smoke 满足测试数量，最终停在 Gate 修复循环。

## 根因

启动协议只有“有 active thread 就恢复”，缺少 InvocationIntent 与 State Compatibility
判定；ProjectProfile 又允许 legacy 声明覆盖当前项目入口缺失。用户本次显式输入无法触发
状态协调。

## 修复边界

采用 `design/v5.8-State-Reconciliation-Design.md`：兼容时自动续作，冲突时在任何写入前
咨询用户选择重新初始化或修复状态续作。旧状态只逻辑关闭和保留审计，不物理删除。
