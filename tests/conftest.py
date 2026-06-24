"""conftest.py — 共享 MockRuntime + 临时 checkpoint 目录 fixture.

Phase 1 不调 LLM,所有 Agent 行为用 MockRuntime 替代.
Phase 2+ 接真实 AgentRuntime 后,本文件可能缩减为仅保留 checkpoint_dir fixture.
"""

import asyncio
from dataclasses import dataclass

import pytest

from auto_engineering.engine.loop import StageResult


@dataclass
class ScriptedMockRuntime:
    """按 stage.name 查找对应 writes 的 Mock Runtime.

    用法:
        runtime = ScriptedMockRuntime({
            'architect': {'plan': 'p', 'file_list': []},
            'critic': {'verdict': 'APPROVE', 'findings': [], 'critic_feedback': ''},
        })
    """

    scripts: dict[str, dict]
    call_log: list[str] = None

    def __post_init__(self):
        if self.call_log is None:
            self.call_log = []

    async def execute(self, stage, state, cancellation=None):
        self.call_log.append(stage.name)
        if stage.name not in self.scripts:
            raise AssertionError(f"MockRuntime: no script for stage '{stage.name}'")
        return StageResult(stage=stage.name, writes=self.scripts[stage.name])


class StepLimitedMockRuntime:
    """强制 Critic 在第 N 次返回 MAJOR,然后再 APPROVE. 用于测试 MAJOR→developer 反馈回路."""

    def __init__(self, major_count: int):
        self.major_count = major_count
        self.critic_calls = 0
        self.call_log: list[str] = []

    async def execute(self, stage, state, cancellation=None):
        self.call_log.append(stage.name)
        if stage.name == "architect":
            return StageResult(
                stage="architect",
                writes={"plan": "p", "file_list": ["x.py"], "batch_plan": [], "contracts": {}},
            )
        if stage.name == "developer":
            return StageResult(
                stage="developer",
                writes={"files_changed": ["x.py"], "commit_hash": "abc", "test_results": {}},
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


@pytest.fixture
def checkpoint_dir(tmp_path):
    """每个测试用独立 tmp 目录存 checkpoint SQLite."""
    return str(tmp_path / ".ae-checkpoints")


def run_async(coro):
    """同步上下文跑 async 协程. Phase 1 不引入 pytest-asyncio 依赖."""
    return asyncio.run(coro)
