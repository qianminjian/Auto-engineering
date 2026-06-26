"""Mock Agent 实现 — Phase 1/2 测试 + CLI 默认运行时.

为什么在 production code(runtime/mock.py):
    - 早期 dev-loop 默认 runtime(Plan B Phase 02 在 cli.py 用 ScriptedMockRuntime
      替代真实 LLM 调用,见 cli.py:_run_v1_engine)
    - 测试代码也用(测试 fixtures re-export from tests/conftest.py)

设计要点:
    - 实现 Agent Protocol(duck typing),AgentRuntime.register 可接受
    - ScriptedMockRuntime 按 stage.name 返回预设 writes
    - StepLimitedMockRuntime 让 critic 在前 N 次返回 MAJOR,之后 APPROVE
      (用于测试 MAJOR→developer 反馈回路)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from auto_engineering.engine.loop import StageResult


@dataclass
class ScriptedMockRuntime:
    """按 stage.name 查找对应 writes 的 Mock Agent.

    用法:
        runtime = ScriptedMockRuntime({
            'architect': {'plan': 'p', 'file_list': []},
            'critic': {'verdict': 'APPROVE', 'findings': [], 'critic_feedback': ''},
        })

    注意:
        - 实现 Agent Protocol(见 runtime/runtime.py:Agent)
        - cli.py 在 v1.0 默认用本类替代真实 LLM(Plan B Phase 02)
        - 测试代码用 tests/conftest re-export
    """

    scripts: dict[str, dict]
    call_log: list[str] = field(default_factory=list)

    async def execute(
        self,
        stage: Any,
        state: Any = None,
        cancellation: Any = None,
        token_tracker: Any = None,
    ) -> StageResult:
        self.call_log.append(stage.name)
        if stage.name not in self.scripts:
            raise AssertionError(f"MockRuntime: no script for stage '{stage.name}'")
        return StageResult(stage=stage.name, writes=self.scripts[stage.name])


@dataclass
class StepLimitedMockRuntime:
    """强制 Critic 在第 N 次返回 MAJOR,然后再 APPROVE. 用于测试 MAJOR→developer 反馈回路."""

    major_count: int
    critic_calls: int = 0
    call_log: list[str] = field(default_factory=list)

    async def execute(
        self,
        stage: Any,
        state: Any = None,
        cancellation: Any = None,
        token_tracker: Any = None,
    ) -> StageResult:
        self.call_log.append(stage.name)
        if stage.name == "architect":
            return StageResult(
                stage="architect",
                writes={
                    "plan": "p",
                    "file_list": ["x.py"],
                    "batch_plan": [],
                    "contracts": {},
                },
            )
        if stage.name == "developer":
            return StageResult(
                stage="developer",
                writes={
                    "files_changed": ["x.py"],
                    "commit_hash": "abc",
                    "test_results": {},
                },
            )
        if stage.name == "critic":
            self.critic_calls += 1
            if self.critic_calls <= self.major_count:
                return StageResult(
                    stage="critic",
                    writes={
                        "verdict": "MAJOR",
                        "findings": [{"severity": "P1", "issue": "x"}],
                        "critic_feedback": f"fix bug (round {self.critic_calls})",
                    },
                )
            return StageResult(
                stage="critic",
                writes={"verdict": "APPROVE", "findings": [], "critic_feedback": ""},
            )
        raise AssertionError(f"Unknown stage: {stage.name}")
