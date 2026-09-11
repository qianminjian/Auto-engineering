# 2026-09-08 真实 Claude：外层宿主身份继承导致平台漂移

## 运行事实

- 在最终 Build 的 Voice Clone 隔离副本中，首轮 `gap_scan` 已稳定进入真实业务
  `gap_review`，没有发生首轮崩溃。
- 为提交 Gap 决策而直接调用 `ae-run --tick` 时，Core 按当前进程环境把后续 Action
  绑定为 `codex`；随后由 Claude 恢复，Stop Report 记录为 `platform=codex`。
- 现场环境同时存在外层 Codex 的 `CODEX_THREAD_ID`，而 `detect_host()` 的环境检测
  因此得到了错误宿主身份。原项目未被修改，问题在隔离副本中复现。

## 根因

`ae-host-run` 已经是宿主边界，却没有把“实际执行命令的 basename”绑定为子进程的
权威宿主身份。只依赖环境探测会把外层宿主的信号带入内层宿主，造成 Action、lease、
resume 和 Stop Report 的平台漂移。

## 修复

- `claude`/`claude-code` 命令自动绑定 `AE_HOST_PLATFORM=claude-code`，并清理 Codex
  竞争信号；`codex` 对称处理 Claude 信号。
- 用户显式设置的平台与命令冲突时，在创建 marker、lease 或运行宿主前稳定拒绝。
- 回归覆盖外层 `CODEX_THREAD_ID`、真实 Claude 命令和显式冲突三种边界。

## 验证

- `tests/test_host_process_exit.py`：27 passed。
- 修复后的完整 Build、安装和真实 Claude Gap 流程仍需重新构建后复验。
