# Voice Clone V1 黄金设计摘录

## 当前版本架构

- V1 是 Vite、React、TypeScript 实现的纯前端 SPA。
- 浏览器直接调用 MiniMax API，不把同源 BFF 作为 V1 前置条件。
- API Key 只保存在 React 运行时内存，不写入 localStorage、日志或仓库。
- 开发遵循 RED → GREEN → REFACTOR。

## 当前范围义务

- 目录覆盖 entry、container、component、hook、api、utility、type、style 八层。
- 设计覆盖 11 个组件。
- 测试计划目标为 17 个测试文件、127 个测试用例。

## 后续改进

- 同源 BFF 是未来安全改进，不得自动提升为 V1 阻断要求。
