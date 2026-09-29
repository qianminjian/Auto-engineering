# 2026-09-29：宿主启动运行时与标准输入边界复盘

## 结论

T895/T896 已完成代码修复和回归验证，但本次真实宿主只证明启动阻断被前移问题修复，尚未证明 Voice Clone 产品 L4。当前唯一设计仍是“宿主 Agent 驱动 + Python 单 Tick + EventStore 唯一事实源”；没有新增 Supervisor、Round 或第二个 EventStore。

## 证据链

1. T895 的真实复现是外层 `scripts/ae-host-run` 把父进程 stdin 继承给非交互 Codex。宿主输出 `Reading additional input from stdin`，尚未创建 EventStore Action，随后状态回查得到 `EVENT_THREAD_NOT_FOUND`。修复为子进程固定 `</dev/null`，结构化 Worker 输入仍只能通过 Action 合同和受控文件传递；新增回归验证父 stdin 不会进入宿主。
2. T896 的真实复现是 `scripts/ae-run` 即使项目 `.ae-state/.ae-runtime` 已有可导入依赖，仍每次执行 `uv run --project`，先访问不可读的用户 uv cache；临时缓存又因网络不可用下载 `hatchling`，所以首个 `--init` 前停止。修复后，运行时只有在本地指纹同时绑定插件绝对路径和 `build-info.content_sha256` 时直连；缺失或不匹配才进入一次有界 uv bootstrap，绝不执行未知旧运行时。
3. 初始修复 Build `5.8.0-rc.5+sha256.7521e68f4ed3b49e` 已安装到 Codex、Claude Code；后续 T897/T898 修复后的 Build `5.8.0-rc.5+sha256.ef5b27f4d7b5e45a` 已重新安装两宿主并通过双方 archive smoke。新鲜项目用 `UV_OFFLINE=1` 完成 `build-info --expect-build-id`，随后在 `PATH` 不含 `uv` 时仍成功复用项目运行时；Codex 实际 cache runner 预检也成功。预检必须使用宿主实际加载的插件路径；Release staging 路径与 Codex cache 路径不同而被拒绝，是 fail-closed 的正确行为，不得手工改写指纹。
4. 真实 Codex Canary 越过 `uv cache/PyPI` 阻断后，宿主自身出现模型缓存、插件 manifest 和外部模型调用无结构化输出；在有界等待后停止，未产生首个 Action。该结果记录为宿主外部资源/无输出证据，不能计为 L3/L4，也不能归因于 Core 已崩溃。
5. 该 Canary 又暴露 watchdog 的启动阶段漏洞：`active-lease.json` 不存在时，idle 条件被 `lease_present` 短路，`--max-idle-seconds` 对首个 `--init` 前的沉默无效，宿主可能一直等到更大的总时限。T897 删除这个错误豁免；无 lease 仍不产生任何 Loop 事实，但宿主沉默超过 idle 上限会得到 `HOST_PROCESS_IDLE_TIMEOUT` 并被有界终止。
6. T898 的回归进一步发现 watchdog 的退出竞态：宿主已经写出终态并退出时，watchdog 在 `sleep(1)` 返回后仍可能继续做 idle 判断，留下伪 `idle-timeout` marker。现在只有二次确认宿主 PID 仍存活时才写 protocol/idle/timeout marker；合法 native-wait 的启动宽限仍由已绑定 Claude lease 和 observation 合同控制。

## 当前验收边界

- 自动化：`check-gate` 通过；`tests/test_ae_run.py` 26/26；`tests/test_ae_run.py + tests/test_host_process_exit.py` 73/73。
- T897 定向回归：`tests/test_watchdog.py` 30/30，新增无 lease 启动沉默超时测试。
- T898 定向回归：`tests/test_watchdog.py + tests/test_host_process_exit.py` 共 77/77，覆盖无 lease 启动封口、Claude native-wait 延迟观察和宿主自然退出竞态。
- 全量串行回归主体：`2993 passed, 31 failed, 1 skipped`；31 项均为临时 Git 仓库初始化命中 `/usr/bin/git` 的 macOS Xcode license 退出 69，使用 `/opt/homebrew/bin/git` 的独立 `git init` 已通过，未发现 T896 业务回归。
- 未完成：双宿主新鲜真实 L3/L4、Voice Clone 业务 Gate、Recovery Canary 因果证据和产品 evidence；不得据此关闭 P0-E2E。

## 后续唯一顺序

1. 在宿主实际 cache runner 上先做候选 Build preflight。
2. 再执行一次真实 Codex/Claude `ae-host-run`，要求产生首个 EventStore Action；宿主无结构化输出只进入 `WAIT_RESOURCE`/Stop Report，不启动第二循环。
3. 只有真实 Action→ResultAccepted→TERMINAL 和业务 Gate/evidence 完整后，才允许更新 P0-E2E 为完成。
