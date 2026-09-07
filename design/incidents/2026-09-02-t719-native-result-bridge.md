# T719：原生 Worker 回包暂存通道验收记录

日期：2026-09-02
候选 Build：`5.8.0-rc.5+sha256.5d371f6ebe89bbdd`
范围：原生 Worker 回包 → `record-worker-outcome` → Finalize/Validate/Tick

## 结论

本轮实现已把原生回包暂存纳入唯一 Worker 回写边界：

- `record-worker-outcome` 固定模板保留 Action 绑定的 `--native-result-file`，并提供
  `--native-result-stdin` 作为原生 envelope 的原样输入通道。
- Assembler 先校验 Worker、Action 根路径、native/outcome 路径绑定，再以 bytes 原子暂存；
  后续仍使用同一个 native envelope 解析、业务 schema、宿主事实合并和 Result 生成链路。
- 空输入、越界路径、畸形 JSON 和宿主字段污染仍 fail-closed，不改变 Action identity，
  不增加 Python Supervisor、第二个 loop 或人工协议。

## 验证证据

- 定向：6 passed，覆盖原样 bytes、空输入、越界路径、CLI stdin 到私有 outcome 的纵向链路，
  以及 Codex/Claude 两套 Host Action 模板。
- 全量（排除一次网络抖动的 Release 安装测试）：`2829 passed, 1 skipped`。
- 覆盖率：`90%`。
- Ruff、mypy、compileall、静态审计、规则同步、`git diff --check`：通过。
- Release archive smoke：Codex/Claude 均通过；Build Identity 与 content SHA 一致。
- Release 集成测试网络重试：`test_codex_release_minimal_tick_chain` 通过。

## 真实宿主边界

同日新的 Codex 真实启动实际加载的是用户插件缓存中的旧 Build
`5.8.0-rc.5+sha256.c43110857b179eb6`，不是本轮候选 Build；因此旧 runner 拒绝
`--native-result-stdin`，该次不能作为 T719 产品 L4 证据。该宿主仍按 Core 合同处理了
Prompt hash mismatch 和同 Action 修复，没有重跑 Worker 或手工写 shared outcomes。

后续真实 L4 必须先用安装验收确认宿主加载的 Build Identity 等于最终候选制品的
`5d371f6ebe89bbdd70e79426286fc3bae05c3db5212c9dba1b2d761f06e5b57f`，再运行等价黄金项目；
archive smoke 和旧缓存真实运行均不得替代该证据。
