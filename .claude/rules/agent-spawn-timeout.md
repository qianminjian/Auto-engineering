---
name: agent-spawn-timeout
description: Agent tool 调用超时管理 — 防止 agent 卡死时无限等待
type: feedback
---

# Agent Spawn Timeout 管理

**规则：所有 Agent tool 调用必须遵守 3 层超时防护。**

**Why:** 2026-06-26 7 小时会话中，agent spawn 卡死 7 小时未返回，编排器僵死。修复 P0.1 + Phase G 期间出现 agent 卡死需立即 kill + 重试，但当时未设任何超时机制。

**How to apply：**

## Layer 1 — Progress Display（强制，spawn 前 30 秒内必做）

```
[Auto-Phase N/M: name | Step X/Y: description]
⚙️  Spawning gsd-executor，预计 8-12 分钟
⏱️  超时阈值: 15 分钟 (Phase TDD), 25 分钟 (Phase 文档同步)
```

**禁止**：直接调 Agent tool 不输出 ProgressDisplay。

## Layer 2 — 心跳协议（agent spawn 期间）

每个 agent spawn 期间：
- **5 分钟内**：无输出 → 输出 `[Heartbeat 5min] agent 仍在工作`
- **10 分钟内**：无输出 → 输出 `[Heartbeat 10min] agent 仍在工作, state.json 无变化`
- **15 分钟内**：无输出 → **主动 kill + 重试**（见 Layer 3）

## Layer 3 — 超时干预（15 分钟强制 kill + 重试）

```python
# 伪代码：检测 agent 卡死
if elapsed_minutes > 15:
    # 1. 检查 state.json 是否有新 commit
    result = subprocess.run(['git', 'log', '--oneline', '--since=10min'], capture_output=True)
    if not result.stdout:
        # 2. 检查 phase status 是否变化
        status = phase_state.get_current_phase()
        if status == previous_status:
            # 3. 主动告知用户卡死, 让用户决策
            log("⚠️ Agent 卡死超时（15min），请用户决策：重试 / 跳过 / 终止")
            return AskUserQuestion(["retry", "skip", "abort"])
```

## Bash 命令 timeout 规则

```bash
# 长命令必须 timeout 包裹（防卡死）
timeout 30 .venv/bin/python -c "..."
timeout 60 .venv/bin/pytest tests/test_xxx.py -v --no-cov

# phase-state.js 命令（秒级返回），timeout 10 兜底
timeout 10 node /Users/minjianq/.agents/skills/atdo/scripts/phase-state.js ...
```

## 与项目其他规则的关系

- `.claude/rules/pytest-memory-management.md` — pytest 资源控制（防内存爆）
- `.claude/rules/agent-spawn-timeout.md` — Agent tool 控制（防卡死）
- `.claude/rules/` 下规则文件，AI 自动 @ 引用加载

## 反例（本次会话发生）

- ❌ spawn agent 前无 ProgressDisplay
- ❌ spawn agent 期间无心跳输出
- ❌ 7 小时未返回仍等待，未主动 kill
- ❌ 用户两次中断询问才意识到问题

## 正例（本规则生效后）

- ✅ spawn 前必输出 ProgressDisplay + 预估时间
- ✅ spawn 期间每 5 分钟输出一行心跳
- ✅ 15 分钟无进展主动告知用户决策（kill / 重试 / 跳过）
- ✅ Bash 命令 timeout 包裹