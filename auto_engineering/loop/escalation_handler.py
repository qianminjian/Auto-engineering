"""EscalationHandler — Agent escalation gate 构建与解析 (P1-9).

Extracted from TickOrchestrator (P0-1 God Class 拆分).
Builds Agent-requested escalation gates and resolves user decisions into stage
transitions. Project setup is handled by the deterministic ProjectProfile
protocol, not by an escalation that writes toolchain files.

Design ref: v5.6-Design-Loop.md T94/T95.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.loop.actions import build_terminal_acceptance_summary
from auto_engineering.loop.events import LoopEventType

if TYPE_CHECKING:
    from auto_engineering.engine.batch_state import BatchState
    from auto_engineering.engine.state import EngineState

_logger = logging.getLogger("ae.loop.escalation")

_LANGUAGE_INDICATORS: list[tuple[str, str]] = [
    ("python", "pyproject.toml"),
    ("python", "setup.py"),
    ("python", "setup.cfg"),
    ("typescript", "package.json"),
    ("go", "go.mod"),
    ("rust", "Cargo.toml"),
]


def detect_project_language(project_root: Path) -> str | None:
    """从常见配置文件探测项目语言。返回 language code 或 None。

    探测优先级按 _LANGUAGE_INDICATORS 顺序。package.json 需要二次确认——
    检查 tsconfig.json 或 devDependencies/dependencies 中是否有 typescript。
    """
    for lang, indicator in _LANGUAGE_INDICATORS:
        indicator_path = project_root / indicator
        if not indicator_path.exists():
            continue
        if lang == "typescript":
            if (project_root / "tsconfig.json").exists():
                return "typescript"
            try:
                pkg = json.loads(indicator_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return "typescript"
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "typescript" in deps:
                return "typescript"
            return "typescript"
        return lang
    return None


@dataclass
class EscalationContext:
    """EscalationHandler 所需的 TickOrchestrator 状态引用 (P1-9)."""

    state: EngineState
    batch_state: BatchState | None
    build_action: Callable[..., dict]
    save_checkpoint: Callable[[], str | None]
    queue_domain_event: Callable[[LoopEventType, dict[str, Any]], None]


class EscalationHandler:
    """Agent escalation gate 的构建与解析。

    Agent 请求人工决策时拦截。
    所有状态修改通过 EscalationContext 注入，不依赖 TickOrchestrator。
    """

    def __init__(self, ctx: EscalationContext) -> None:
        self._ctx = ctx

    # ── Agent escalation ──

    @staticmethod
    def build_agent_escalation_gate(agent_context: dict | None) -> dict:
        """构建 Agent 发起的 escalation gate."""
        if agent_context and agent_context.get("question"):
            question = agent_context["question"]
            options = agent_context.get("options") or [
                "批准继续", "回退重设计", "终止 loop"]
            default = agent_context.get("default") or options[0]
        else:
            question = "Agent 请求人工决策。请描述需要决策的事项，或选择操作："
            options = ["继续（批准当前方向）", "回退到上一阶段", "终止 loop"]
            default = options[0]

        return {
            "id": "agent_escalation",
            "type": "agent_escalation",
            "trigger": "agent_requested",
            "question": question,
            "options": options,
            "default": default,
            "timeout_ms": 0,
        }

    def resolve_agent_escalation(self, gate_resolution: dict) -> dict:
        """处理 Agent escalation 的 resolution."""
        resolution = gate_resolution.get("resolution", "")
        detail = gate_resolution.get("resolution_detail", {})
        state = self._ctx.state

        if resolution == "终止 loop":
            return {
                "action": "done",
                "verdict": "TERMINATED",
                "message": "用户通过 agent_escalation 终止 loop",
                "stage": state.current_stage,
                "tick": state.tick + 1,
                "thread_id": state.thread_id,
                "acceptance_summary": build_terminal_acceptance_summary(
                    state, verdict="TERMINATED",
                ),
            }

        if "回退" in resolution:
            previous_stage = state.current_stage
            state.current_stage = "architect"
            state.expected_stage = "architect"
            if previous_stage != state.current_stage:
                self._ctx.queue_domain_event(
                    LoopEventType.STAGE_ADVANCED,
                    {"from": previous_stage, "to": state.current_stage},
                )
            state.round += 1
            self._ctx.save_checkpoint()
            note = detail.get("note", "")
            return self._ctx.build_action(
                feedback=f"Agent escalation: 用户选择回退重设计。{note}".rstrip())

        if "跳过" in resolution:
            if self._ctx.batch_state is not None:
                self._ctx.batch_state.advance_batch()
            self._ctx.save_checkpoint()
            return self._ctx.build_action()

        # 默认: "批准继续" / "继续（批准当前方向）"
        if state.project_profile is None and state.missing_project_capabilities:
            previous_stage = state.current_stage
            state.current_stage = "project_setup"
            state.expected_stage = "project_setup"
            if previous_stage != state.current_stage:
                self._ctx.queue_domain_event(
                    LoopEventType.STAGE_ADVANCED,
                    {"from": previous_stage, "to": state.current_stage},
                )
        self._ctx.save_checkpoint()
        return self._ctx.build_action()
