# 2026-09-08 真实 Claude L4：首轮稳定进入业务 Gap Gate

## 运行事实

- 使用最终 Build `5.8.0-rc.5+sha256.23a3a4b44e7d6f29`，从 Voice Clone 原始项目的
  隔离副本执行一次设计驱动命令。
- 宿主没有被 stdout idle watchdog 误杀，也没有产生 Stop Report；Core 创建并保持同一
  `gap_review` Action，Build Identity 与运行态一致。
- 首轮完成 `gap_scan`，发现 1 个阻断性架构缺口，产品目录尚未被修改，Loop 正确等待
  用户决策。

## 发现的真实业务缺口

设计 §7.1 规定录音优先输出 `audio/webm`、降级 `audio/mp4`，而 §5.1 的 MiniMax
上传约束只允许 `mp3/m4a/wav`。因此录音→克隆主路径没有可执行的格式转换合同。

这是业务设计缺口，不是宿主崩溃。当前 Gate 合法选项为：

- `Research`：先验证浏览器端转码、资源体积、兼容性和 API 接受范围；
- `Fill`：明确并实现转码路径后再进入 Architect；
- `Defer` 被 Core 禁用，因为它会留下核心功能不完整。

MiniMax 官方上传文档确认 `voice_clone` 文件只接受 `mp3/m4a/wav`；MDN 的
`MediaRecorder.isTypeSupported()` 只说明浏览器是否能录某个 MIME，不等于服务端接受；
浏览器端 `ffmpeg.wasm` 方案需要额外 Web Worker 和自托管 WebAssembly 资源。

## 结论

本次运行证明 T811/T812/T813 后的宿主边界不再首轮崩溃，并能把原先遗漏的真实业务
设计问题暴露为可解释的用户 Gate。该 Gate 未获选择前不得修改产品代码、代替用户选项
或宣称 L4 完成。

## 验证

- `3150 passed, 1 skipped`，总覆盖率 `90%`；
- Ruff、mypy、compileall、`make check-gate`、`git diff --check` 通过；
- Codex/Claude archive smoke 均通过，Build Identity 为
  `5.8.0-rc.5+sha256.23a3a4b44e7d6f29`。
