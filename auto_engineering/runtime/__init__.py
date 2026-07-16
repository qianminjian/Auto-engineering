"""Agent 运行时 — 借鉴 AutoGen _single_threaded_agent_runtime.py.

核心类（Phase 2+ 实现）:
    AgentRuntime — Agent 注册 + 任务执行 + Guardrail 中间件
    CancellationToken — 协作式取消令牌 (Phase 03 整合)

⚠️ 双驱动共享资产 (v7.0 T33b, BEACON #54): 本执行栈 (agents/ + runtime/ + tools/ +
loop/round.py) 是 Driver A (Claude Code Agent 填 result) 与 Driver B (StandaloneDriver,
v7.0 进程内自带 key 调 LLM) 的共享引擎, 且 `ae agent` CLI 已独立依赖。退役 v5.5
orchestrator 循环时不得连带删除本执行层 —— Driver B 复用 v5.5 执行栈
(`_step_2e_run_agent` → run_round/AgentRuntime/BaseAgent) 作 tick 填充器。
详见 design/v5.6-Design-Loop.md 附录 C §2.3.
"""

from .cancellation import CancellationToken
from .runtime import AgentRuntime

__all__ = ["AgentRuntime", "CancellationToken"]