# Auto-Engineering 故障排查

> 创建：2026-06-26 | 阶段：v2.2 FINAL
> 位置：`docs/` = 永久资产
> 决策依据：`design/BEACON.md` 决策 11/12/18/19

## 1. `PydanticSerializationError` (loop/state)

**症状**：`Checkpoint.state` 序列化失败，循环引用报错。

**根因**：v1.0 无 Protocol 类型契约。v2.2 Phase G 用 `LoopStateProtocol`
+ `Generic[T]` 替代 `state: Any`，旧 db 可能含 Any-typed state。

**修复**：

1. 确认 Python 3.12+：`python3.12 -c "import sys; print(sys.version)"`
2. `rm -rf .ae-checkpoints/`（仅本地开发态）
3. 重跑 `ae dev-loop "<req>"` 生成 v2.2 checkpoint

引用：BEACON 决策 G.3 + `auto_engineering/loop/types.py`

## 2. `P0.1 Agent Tools 未连接` (v1.0 兼容)

**症状**：`ae dev-loop --use-v1` 报 `AgentToolsNotConnected`。

**根因**：v1.0 走 `LoopEngine` + `AgentRuntime`，旧路径未注册
`ToolRegistry`（项目根 sandbox 失效）。

**修复**：v1.0 路径仅向后兼容，新功能请用 v2.0：
`ae dev-loop --use-v2`。若必须 v1.0，确保 `--project-root` 指向
有效 git 仓库。引用：BEACON 决策 12 + `_build_runtime()` P1.9 修复。

## 3. 96GB 内存爆炸事故

**症状**：3+ subagent 并行扫描 `references/` 时 macOS 触发
`vm-compressor-space-shortage` 强制重启。

**根因**：2026-06-24 atdo Phase 02 spawn 3 subagent 同时建立 file tree
index（参考源码已迁出项目根）。

**防护**：禁止并行多 subagent 扫描 `$AE_REFS_DIR/`；禁止 `Read` 整个
框架 / `ls -R` / `find` 无过滤；三步法：`grep` 定位 → 50-200 行 `Read`
→ 立即丢弃；单次 / 小批量加载。

引用：`CLAUDE.md` §⚠️ + `.claude/rules/agent-spawn-timeout.md`（BEACON 19）

## 4. `TDD 标签错位` (atdo runtime smoke)

**症状**：atdo Plan 报告 SUCCESS 但实际功能未完整实现（Phase 02 虚化）。

**根因**：agent 用空 `LoopState()` / 空 `gate_results={}` 绕过真实场景。

**修复**（BEACON 18）：save/load 必须真跑 round-trip；Orchestrator 集成
必须真跑 Gate + 真调 LLM evaluator；CLI 集成必须真 `subprocess` 验证
`help` + `exit code`；测试严禁用空状态绕过。

工具：`scripts/atdo_smoke.py`。引用：`docs/atdo-runtime-smoke-policy.md`。

## 5. `init module 大文件` (Phase I 拆分后入口)

**症状**：旧 `auto_engineering.init.scaffold` 单文件路径失败。

**根因**：v2.2 Phase I 拆为 8 模块（config 3 + scaffold 4 + 入口）。

**入口**：

```python
from auto_engineering.init import InitWorker, AnswersMap
from auto_engineering.init.config import AnswersLoader
from auto_engineering.init.scaffold import TemplateEngine
```

## 引用

- `design/BEACON.md` 决策 11/12/18/19
- `CLAUDE.md` §⚠️ · `.claude/rules/agent-spawn-timeout.md`
- `docs/atdo-runtime-smoke-policy.md`
