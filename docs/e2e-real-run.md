# Auto-Engineering 端到端真跑指南

> 创建：2026-06-26 | 阶段：v2.2 FINAL
> 位置：`docs/` = 永久资产
> 决策依据：`design/BEACON.md` 决策 11/12/19

## 前置

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # 必需（v2.0 模式）
uv sync                                    # 或 pip install -e .
ae --version                               # 验证安装
```

## 单 Agent 测试

```bash
ae dev-loop "写一个 hello world Python 函数" --use-v2 --max-rounds 1
```

预期输出：stage 进度（architect → developer → critic）→ Gate 验证 →
checkpoint 保存 → 最终 summary。无 API key 时加 `--use-v1` fallback。

## 多 Agent 测试

```bash
ae dev-loop "重构 init 模块加 pytest fixture" --use-v2 --max-rounds 5
```

预期：多 Round（Orchestrator 调度 architect/developer/critic/qa）→
Gate（safety/lint/type_check/contract/test/coverage/build）→ RoundResult 写入
checkpoint。`docs/api-reference.md` 有完整参数。

## 故障排查

| 现象 | 排查 |
|------|------|
| `PydanticSerializationError` | 见 `docs/troubleshooting.md` §1 |
| `AgentToolsNotConnected` | 加 `--use-v2` 或设 `--project-root` |
| 子 agent 卡死 | `.claude/rules/agent-spawn-timeout.md`（3 层防护） |
| atdo 报告虚化 | `docs/atdo-runtime-smoke-policy.md` + `scripts/atdo_smoke.py` |
| init 模块导入失败 | 见 `docs/troubleshooting.md` §5（Phase I 拆分后入口） |

## 引用

- `docs/api-reference.md` · `docs/troubleshooting.md` · `docs/production-deployment.md`
- `design/BEACON.md` 决策 11/12/19
