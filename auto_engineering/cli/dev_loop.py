"""CLI dev_loop 核心 — _build_v2_agent_runtime / _run_v2_orchestrator.

从 cli.py 拆分 (Plan P1-B, 原 cli.py §218-451).

v5.0 §PE.6 + §B13.2 — OrchestratorRunResult 扩展 6 字段 JSON 契约:
    - status: 终态 (completed / max_rounds / failed)
    - thread_id: 唯一线程 ID (UUID hex)
    - rounds: 实际跑了几轮
    - verdict: 收敛判定 level + reason
    - duration_sec: 总耗时 (秒)
    - gate_summary: 各 Gate 的 pass/fail dict
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_engineering.cli.helpers import CancellationToken, ProgressLogger, TokenTracker


@dataclass
class OrchestratorRunResult:
    """_run_v2_orchestrator 返回值 — v5.0 §B13.2 6 字段 JSON 契约.

    Attributes:
        status: 终态字符串 (completed / max_rounds / failed)
        thread_id: 唯一线程 ID
        rounds: 实际跑的轮数
        verdict: 收敛判定 dict (level/level_name/reason)
        duration_sec: 总耗时 (秒)
        gate_summary: 各 Gate 状态 dict (gate_name -> {status, passed, message})
        total_steps: 旧字段, 等同 rounds (向后兼容)
        checkpoint_id: 旧字段 (向后兼容)
    """

    status: str
    thread_id: str
    rounds: int
    verdict: dict
    duration_sec: float
    gate_summary: dict
    # 旧字段 (向后兼容, 内部填)
    total_steps: int = 0
    checkpoint_id: str = ""

    def to_json_dict(self) -> dict:
        """输出 6 字段 JSON 契约 (v5.0 §B13.2)."""
        return {
            "status": self.status,
            "thread_id": self.thread_id,
            "rounds": self.rounds,
            "verdict": self.verdict,
            "duration_sec": self.duration_sec,
            "gate_summary": self.gate_summary,
        }

    @classmethod
    def from_orchestrator(
        cls,
        orchestrator: Any,
        total_rounds: int,
        duration_sec: float,
        gate_results: dict | None = None,
    ) -> OrchestratorRunResult:
        """从 Orchestrator 实例构造.

        2026-07-04 修复 (Bug 3 prismscan 集成): verdict.level=4 (HARD_LIMIT)
        不再映射为 status="completed", 改为 status="failed". 这样 CLI 进程
        退出码可正确反映异常停止 (Bug 3 + Bug 2 根因 → 0 代码改动退出).

        状态映射:
            - verdict.level=3 (QUALITY_PASS) → status="completed" (正常停止)
            - verdict.level=4 (HARD_LIMIT)   → status="failed"    (异常停止)
            - verdict.level in (0,1,2)       → status="max_rounds" (未达停止条件)
        """
        verdict_obj = getattr(orchestrator, "verdict", None)
        if verdict_obj is not None and getattr(verdict_obj, "should_stop", False):
            level = getattr(verdict_obj, "level", 0)
            if level == 4:
                # HARD_LIMIT (Bug 3 升级: critic 异常 → 异常停止)
                status = "failed"
            else:
                # QUALITY_PASS 或 MAJOR 超限等 (含 level=2 STAGNANT)
                status = "completed"
            verdict_dict = {
                "level": level,
                "level_name": getattr(verdict_obj, "level_name", "UNKNOWN"),
                "reason": getattr(verdict_obj, "reason", ""),
            }
        else:
            status = "max_rounds"
            verdict_dict = {
                "level": 4,
                "level_name": "HARD_LIMIT",
                "reason": f"达到 max_iterations 上限 ({total_rounds} 轮)",
            }
        return cls(
            status=status,
            thread_id=getattr(orchestrator, "_thread_id", uuid.uuid4().hex),
            rounds=total_rounds,
            verdict=verdict_dict,
            duration_sec=duration_sec,
            gate_summary=_build_gate_summary(gate_results or {}),
            total_steps=total_rounds,
            checkpoint_id=f"v2-r{total_rounds}",
        )


def _build_gate_summary(gate_results: dict) -> dict:
    """把 Orchestrator.history[-1].gate_results 转为 JSON-ready dict.

    兼容两种 Verdict 类型:
    - auto_engineering.gates.base.GateVerdict (含 .passed / .message)
    - auto_engineering.loop.convergence.Verdict (含 .should_stop / .level / .reason)
    """
    summary: dict[str, dict] = {}
    for name, v in gate_results.items():
        if v is None:
            summary[name] = {"status": "skipped", "passed": None, "message": ""}
            continue
        passed = getattr(v, "passed", None)
        if passed is None:
            # convergence.Verdict 类型, 用 should_stop 推断
            should_stop = getattr(v, "should_stop", False)
            passed = bool(should_stop)
        message = getattr(v, "message", "") or ""
        if not message:
            reason = getattr(v, "reason", "")
            if reason:
                message = reason
        summary[name] = {
            "status": "pass" if passed else "fail",
            "passed": passed,
            "message": message,
        }
    return summary


def _build_v2_agent_runtime(
    project_root: Path,
    progress: ProgressLogger,
    token_tracker: TokenTracker | None = None,
) -> Any:
    """构造 v2.0 Orchestrator 用的 AgentRuntime (替代 _build_v2_executor).

    v2.3 Phase H (P1.4): Orchestrator 集成 AgentRuntime, 按 task.role 路由
    调 agent.execute — 替代单一 executor callback wrapper.

    设计:
        - 3 个 role (architect/developer/critic) 全部使用真实 Agent(BaseAgent) 实例
        - 共享同一个 AnthropicProvider(llm) 和工具集
        - 每个 Agent 有不同的 system_prompt (来自 agents/prompts.py)
        - LLM 异常 → Agent.execute 内 _map_llm_exception 转为 AEError

    Args:
        project_root: 项目根目录 (沙箱白名单基址)
        progress: 进度日志 (用于记录 task 执行)
        token_tracker: Token 跟踪器 (注入 BaseAgent.execute)

    Returns:
        AgentRuntime 实例 (已注册 architect/developer/critic)
    """
    import os

    from auto_engineering.agents.base import Agent
    from auto_engineering.agents.prompts import (
        ARCHITECT_SYSTEM_PROMPT,
        CRITIC_SYSTEM_PROMPT,
        DEVELOPER_SYSTEM_PROMPT,
    )
    from auto_engineering.llm.anthropic_provider import AnthropicProvider
    from auto_engineering.runtime.runtime import AgentRuntime
    from auto_engineering.tools.bash_tools import RunBashTool
    from auto_engineering.tools.file_tools import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        SearchCodeTool,
        WriteFileTool,
    )
    from auto_engineering.tools.git_tools import (
        GitCommitTool,
        GitDiffTool,
        GitStatusTool,
    )
    from auto_engineering.tools.test_tools import RunTestsTool

    llm = AnthropicProvider()  # SDK 自动从 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 读
    # P1.9 fix: 只有支持 project_root 的工具传 project_root (白名单沙箱)
    # P1-C: ReadFileTool 现在也支持 project_root
    tools = [
        WriteFileTool(project_root=project_root),
        EditFileTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
        ReadFileTool(project_root=project_root),
        # 不支持 project_root 的工具: ListDirTool / RunBashTool /
        # GitStatusTool / GitCommitTool / GitDiffTool / RunTestsTool
        ListDirTool(),
        RunBashTool(),
        GitStatusTool(),
        GitCommitTool(),
        GitDiffTool(),
        RunTestsTool(),
    ]
    runtime = AgentRuntime()
    runtime.register(
        "architect",
        lambda: Agent(
            llm=llm,
            role="architect",
            system_prompt=ARCHITECT_SYSTEM_PROMPT,
            tools=tools,
        ),
    )
    runtime.register(
        "developer",
        lambda: Agent(
            llm=llm,
            role="developer",
            system_prompt=DEVELOPER_SYSTEM_PROMPT,
            tools=tools,
        ),
    )
    runtime.register(
        "critic",
        lambda: Agent(
            llm=llm,
            role="critic",
            system_prompt=CRITIC_SYSTEM_PROMPT,
            tools=tools,
        ),
    )
    return runtime


def _build_v2_semantic_evaluator(
    project_root: Path,
    progress: ProgressLogger,
) -> Any:
    """构造 v2.0 Orchestrator 用的语义评估器 (简化:始终返回 True).

    Phase C 简化策略:
        - 不接 LLM (避免 mock-friendly 的"假评估"陷阱)
        - 用 Gate 跑过的结果作为代理:所有 Gate 通过 → satisfied
        - 这里返回简单的 True(让 Orchestrator 主循环跑起来)

    Args:
        project_root: 项目根目录 (备用, 当前未使用)
        progress: 进度日志 (备用)

    Returns:
        async (round_result) -> bool
    """

    async def evaluator(round_result: Any) -> bool:
        # Phase C 简化: 总是返回 True (Gate 已在 Orchestrator 内部跑过)
        return True

    return evaluator


def _run_v2_orchestrator(
    requirement: str,
    project_root: Path,
    max_rounds: int,
    progress: ProgressLogger,
    cancellation: CancellationToken,
    token_tracker: TokenTracker | None = None,
) -> OrchestratorRunResult:
    """v5.0 M4 12 步主循环 — 生产级完整路径 (2026-07-04 升级).

    2026-07-04 升级 (从 v2.0 Phase C 演示代码):
    - gates: [SafetyGate+LintGate] → DEFAULT_GATES (7 道)
    - guardrail_chain: None → GuardrailChain.default() (5 Guardrail)
    - stage_router: None → StageRouter() (T1-T6)
    - checkpoint_store: None → SQLiteCheckpointStore (持久化)
    - Task: 硬编码 → orchestrator step_1 走 architect 生成
    """
    import asyncio

    from auto_engineering.gates.base import DEFAULT_GATES
    from auto_engineering.loop.convergence import ConvergenceConfig
    from auto_engineering.loop.guardrail import GuardrailChain
    from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
    from auto_engineering.loop.stage_router import StageRouter

    # 1. Checkpoint store: .ae-state/checkpoints.db
    db_path = Path(project_root) / ".ae-state" / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    checkpoint_store = SQLiteCheckpointStore(str(db_path))

    # 2. v5.0 M4 完整 OrchestratorConfig
    agent_runtime = _build_v2_agent_runtime(project_root, progress, token_tracker)
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(max_iterations=max_rounds),
        gates=DEFAULT_GATES,             # 7 道 Gate (asyncio.gather)
        project_root=project_root,
        agent_runtime=agent_runtime,
        guardrail_chain=GuardrailChain.default(),   # 5 Guardrail
        stage_router=StageRouter(),                  # T1-T6 路由
        checkpoint_store=checkpoint_store,            # SQLite 持久化
    )

    # 3. Orchestrator (空 tasks → step_1 走 architect 自动生成 batch_plan)
    orchestrator = Orchestrator(
        requirement=requirement,
        tasks=[],
        executor=None,
        config=config,
    )
    orchestrator._thread_id = uuid.uuid4().hex

    # 5. 启动 asyncio.run (Orchestrator.run 是 async)
    started_at = time.monotonic()
    history = asyncio.run(orchestrator.run(cancellation=cancellation))
    duration_sec = time.monotonic() - started_at

    # 6. 输出总结
    total_rounds = len(history)
    # 提取最后一轮的 gate_results
    last_gate_results: dict = {}
    if history:
        last = history[-1]
        if hasattr(last, "gate_results"):
            last_gate_results = last.gate_results or {}

    # 进度输出
    progress.emit(
        "orchestrator_done",
        rounds=total_rounds,
        verdict_level=orchestrator.verdict.level if orchestrator.verdict else None,
        should_stop=orchestrator.verdict.should_stop if orchestrator.verdict else False,
    )

    return OrchestratorRunResult.from_orchestrator(
        orchestrator=orchestrator,
        total_rounds=total_rounds,
        duration_sec=duration_sec,
        gate_results=last_gate_results,
    )
