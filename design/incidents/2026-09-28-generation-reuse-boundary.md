# 2026-09-28 跨会话 Worker generation 复用边界

## 事实

事故报告修复后，Loop 已能在同一 Action 内用绑定 native result 修复损坏的私有 artifact；继续审计发现另一条恢复边界仍不严谨：`bind_worker_execution_identity` 在跨宿主接管时曾把“文件存在”当作旧 generation 可复用的证据。无效 native JSON、半成品文件或已清理 lease 后遗留的旧文件，可能因此反复占用同一代路径。

## 根因

generation 选择把三种事实混为一谈：

1. 文件存在，只能证明有字节落盘；
2. 私有业务 outcome 合法，证明业务事实可继续等待 Host attestation；
3. native result 通过唯一 parser，证明可复用原生结果交接。

跨会话只能复用第 2 或第 3 类事实；第 1 类必须进入新 generation。原生 parser 还曾把空对象 `{}` 当作裸业务 payload，进一步放大了误判。

## 修复

- `worker_evidence.py` 增加唯一私有 business envelope parser，并拒绝空 native 对象。
- 跨会话且仍有 lease 时，只复用通过 canonical parser 的 native 或私有业务 artifact；否则递增 generation。
- lease 已由 Stop Report 清理时，扫描当前 Action 绑定的预期 artifact 路径；最新代可验证则复用，否则使用新 generation，保留旧证据。
- 同宿主会话仍保留当前 generation，由既有 `record → finalize → validate → submit` repair 合同处理，不新增循环。

## EARS 验收

- While a new host takes over an Action, when the latest artifact is malformed or empty, the system shall allocate a higher execution generation and preserve the old bytes.
- While a new host takes over an Action, when a private business outcome or native result passes its canonical parser, the system shall reuse that generation without respawning completed work.
- While the same host session continues an Action, when repair is possible, the system shall retain the current generation and use the existing record boundary.

## 验证

- generation/lease/invalid-native 定向回归：7 passed。
- CLI、Assembler、Execution Control、架构和产品 evidence 回归：270 passed。
- Ruff、mypy、`make check-gate`：通过。
