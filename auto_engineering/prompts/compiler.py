"""将 Prompt Contract 与动态上下文编译为宿主可执行提示词。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from auto_engineering.prompts.contracts import (
    ExecutionMode,
    StagePromptContract,
)


class PromptContextError(ValueError):
    """关键任务上下文缺失，不能安全生成提示词。"""


class PromptLayoutError(ValueError):
    """多 Agent 模板布局与契约不一致。"""


@dataclass(frozen=True, slots=True)
class CompiledWorkerPrompt:
    """一个实际 Worker 的完整提示词。"""

    index: int
    role: str
    prompt: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class CompiledPromptBundle:
    """一次 stage 的提示词编译结果。"""

    stage: str
    coordinator_prompt: str
    worker_prompts: tuple[CompiledWorkerPrompt, ...]
    expected_format: dict[str, Any]


def _stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)


_FORBIDDEN_HISTORY_FIELDS = frozenset({
    "messages",
    "transcript",
    "conversation_history",
    "action_history",
})


def select_stage_context(
    contract: StagePromptContract,
    context: dict[str, Any],
) -> dict[str, Any]:
    """只选择契约声明字段，并对历史与字节预算 fail-closed。"""
    forbidden = _FORBIDDEN_HISTORY_FIELDS.intersection(context)
    if forbidden:
        raise PromptContextError(
            "PROMPT_HISTORY_FORBIDDEN stage="
            f"{contract.stage}: {', '.join(sorted(forbidden))}"
        )
    allowed = (*contract.required_context, *contract.optional_context)
    selected = {key: context[key] for key in allowed if key in context}
    size = len(_stable_json(selected).encode("utf-8"))
    if size > contract.max_context_bytes:
        raise PromptContextError(
            f"PROMPT_CONTEXT_TOO_LARGE stage={contract.stage}: "
            f"{size}>{contract.max_context_bytes}"
        )
    return selected


def _render_prompt(
    *,
    role_prompt: str,
    role: str,
    context: dict[str, Any],
    expected_format: dict[str, Any],
) -> str:
    return "\n\n".join((
        f"## 执行角色\n\n{role}",
        role_prompt.strip(),
        "## 本次任务上下文（编排器注入，禁止自行虚构）\n\n"
        f"```json\n{_stable_json(context)}\n```",
        "## 输出契约\n\n只输出可由 Team Lead 映射到以下结构的结果：\n\n"
        f"```json\n{_stable_json(expected_format)}\n```",
    ))


def compile_prompt_bundle(
    *,
    contract: StagePromptContract,
    role_prompt: str,
    context: dict[str, Any],
    expected_format: dict[str, Any],
) -> CompiledPromptBundle:
    """编译单阶段提示词；关键上下文缺失时 fail closed。"""

    missing = [
        key for key in contract.required_context
        if key not in context
    ]
    if missing:
        raise PromptContextError(
            f"PROMPT_CONTEXT_MISSING stage={contract.stage}: "
            + ", ".join(missing)
        )

    selected_context = select_stage_context(contract, context)

    if contract.execution_mode is ExecutionMode.INLINE:
        return CompiledPromptBundle(
            stage=contract.stage,
            coordinator_prompt=_render_prompt(
                role_prompt=role_prompt,
                role=contract.stage,
                context=selected_context,
                expected_format=expected_format,
            ),
            worker_prompts=(),
            expected_format=dict(expected_format),
        )

    role_sections = [role_prompt]
    coordinator_prompt = ""
    if contract.execution_mode is ExecutionMode.MULTI_WORKER:
        role_sections = role_prompt.split("\n***\n")
        expected_sections = len(contract.worker_roles) + 1
        if len(role_sections) != expected_sections:
            raise PromptLayoutError(
                f"PROMPT_LAYOUT_INVALID stage={contract.stage}: "
                f"sections={len(role_sections)}, expected={expected_sections}"
            )
        coordinator_prompt = _render_prompt(
            role_prompt=role_sections[0],
            role=f"{contract.stage}_coordinator",
            context=selected_context,
            expected_format=expected_format,
        )

    workers: list[CompiledWorkerPrompt] = []
    for index, role in enumerate(contract.worker_roles):
        worker_role_prompt = (
            role_sections[index + 1]
            if contract.execution_mode is ExecutionMode.MULTI_WORKER
            else role_sections[0]
        )
        prompt = _render_prompt(
            role_prompt=worker_role_prompt,
            role=role,
            context=selected_context,
            expected_format=expected_format,
        )
        workers.append(CompiledWorkerPrompt(
            index=index,
            role=role,
            prompt=prompt,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        ))

    return CompiledPromptBundle(
        stage=contract.stage,
        coordinator_prompt=coordinator_prompt,
        worker_prompts=tuple(workers),
        expected_format=dict(expected_format),
    )


__all__ = [
    "CompiledPromptBundle",
    "CompiledWorkerPrompt",
    "PromptContextError",
    "PromptLayoutError",
    "compile_prompt_bundle",
    "select_stage_context",
]
