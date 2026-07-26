"""EscalationHandler — System/Agent escalation gate 构建与解析 (P1-9).

Extracted from TickOrchestrator (P0-1 God Class 拆分).
Manages init-manifest missing escalation (system-initiated) and Agent-requested
escalation gates.  Builds gate JSON dicts and resolves user decisions into
stage transitions.

Design ref: v5.6-Design-Loop.md T94/T95.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.gates._tools import LANGUAGE_TOOLS

if TYPE_CHECKING:
    from auto_engineering.engine.batch_state import BatchState
    from auto_engineering.engine.state import EngineState

_logger = logging.getLogger("ae.loop.escalation")

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

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

    project_root: Path
    state: EngineState
    batch_state: BatchState | None
    design_doc: Any | None  # DesignDoc | None — avoid circular import
    init_manifest: dict | None
    tick_gate_runner: Any  # TickGateRunner — avoid circular import
    build_action: Callable[..., dict]
    save_checkpoint: Callable[[], str | None]


class EscalationHandler:
    """系统/Agent escalation gate 的构建与解析。

    Init-manifest 缺失时自动创建，Agent 请求人工决策时拦截。
    所有状态修改通过 EscalationContext 注入，不依赖 TickOrchestrator。
    """

    def __init__(self, ctx: EscalationContext) -> None:
        self._ctx = ctx

    # ── init-manifest 缺失 escalation ──

    @staticmethod
    def build_init_manifest_gate(detected_language: str | None) -> dict:
        """构建 'init-manifest 缺失' 的 system escalation gate."""
        if detected_language:
            default_tools = LANGUAGE_TOOLS.get(
                detected_language, LANGUAGE_TOOLS["python"])
            default_label = (
                f"{detected_language}: {default_tools[0]}/{default_tools[1]}/{default_tools[2]}")
            options = [
                default_label,
                "python: ruff/mypy/pytest",
                "自定义（在 resolution_detail 中指定）",
            ]
            question = (
                f"未找到 .ae-state/init-manifest.json。"
                f"检测到项目可能为 {detected_language} 项目。"
                f"请选择 Gate 工具链配置："
            )
        else:
            options = []
            for lang in ["python", "typescript", "go", "rust", "bash"]:
                tools = LANGUAGE_TOOLS[lang]
                options.append(f"{lang}: {tools[0]}/{tools[1]}/{tools[2]}")
            options.append("自定义（在 resolution_detail 中指定）")
            question = (
                "未找到 .ae-state/init-manifest.json, 且无法自动探测项目语言。"
                "请选择 Gate 工具链配置："
            )
            default_label = options[0]

        return {
            "id": "init_manifest_missing",
            "type": "system_escalation",
            "trigger": "missing_init_manifest",
            "question": question,
            "options": options,
            "default": default_label,
            "detected_language": detected_language,
            "timeout_ms": 0,
        }

    def resolve_init_manifest(self, gate_resolution: dict) -> dict:
        """处理 init_manifest_missing 的 gate resolution — 创建 manifest 并继续."""
        resolution = gate_resolution.get("resolution", "")
        detail = gate_resolution.get("resolution_detail", {})

        lang: str | None = None
        tools: tuple[str, str, str] | None = None

        if "自定义" in resolution:
            lang = detail.get("language", "python")
            tools = (
                detail.get("linter", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[0]),
                detail.get("type_checker", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[1]),
                detail.get("test_runner", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[2]),
            )
        else:
            for candidate in LANGUAGE_TOOLS:
                if resolution.startswith(candidate):
                    lang = candidate
                    tools = LANGUAGE_TOOLS[candidate]
                    break
            if lang is None:
                lang = "python"
                tools = LANGUAGE_TOOLS["python"]

        # 所有分支均赋值 tools，assert 消除 None 类型（逻辑保证，非运行时检查）
        assert tools is not None, "tools must be set by one of the resolution branches"
        ae_state_dir = self._ctx.project_root / ".ae-state"
        ae_state_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": lang,
            "structure": {"source_root": "src/", "test_root": "tests/"},
            "conventions": {
                "linter": tools[0],
                "type_checker": tools[1],
                "test_runner": tools[2],
            },
            "created_at": datetime.now(UTC).strftime(_ISO_FMT),
        }
        manifest_path = ae_state_dir / "init-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

        _logger.info(
            "Escalation resolved: created init-manifest (language=%s, "
            "linter=%s, type_checker=%s, test_runner=%s)",
            lang, tools[0], tools[1], tools[2],
        )

        self._ctx.init_manifest = manifest
        self._ctx.tick_gate_runner.reload(manifest)

        state = self._ctx.state
        if self._ctx.design_doc:
            state.current_stage = "gap_scan"
            state.expected_stage = "gap_scan"
        else:
            state.current_stage = "architect"
            state.expected_stage = "architect"
        state.tick = 0
        self._ctx.save_checkpoint()
        return self._ctx.build_action()

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
            }

        if "回退" in resolution:
            state.current_stage = "architect"
            state.expected_stage = "architect"
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
        self._ctx.save_checkpoint()
        return self._ctx.build_action()
