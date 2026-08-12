"""将 Prompt Contract 与动态上下文编译为宿主可执行提示词。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from auto_engineering.host.runtime_identity import ExecutionIdentity
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
    execution_identity: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompiledPromptBundle:
    """一次 stage 的提示词编译结果。"""

    stage: str
    coordinator_prompt: str
    worker_prompts: tuple[CompiledWorkerPrompt, ...]
    expected_format: dict[str, Any]
    context_manifest: dict[str, Any]


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


def build_context_manifest(
    stage: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """生成块级清单并拒绝同一非空值跨字段重复内联。"""
    blocks: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    total = 0
    for key, value in context.items():
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        if value not in (None, "", [], {}):
            digest = hashlib.sha256(encoded).hexdigest()
            if digest in seen:
                raise PromptContextError(
                    f"PROMPT_CONTEXT_DUPLICATE stage={stage}: "
                    f"{seen[digest]},{key} hash={digest}"
                )
            seen[digest] = key
        else:
            digest = hashlib.sha256(encoded).hexdigest()
        total += len(encoded)
        blocks.append({
            "id": key,
            "sha256": digest,
            "bytes": len(encoded),
            "mode": "inline",
            "authority": "stage_contract",
        })
    return {
        "schema_version": "1.0",
        "stage": stage,
        "blocks": blocks,
        "total_inline_bytes": total,
        "duplicate_block_bytes": 0,
    }


def _render_prompt(
    *,
    role_prompt: str,
    role: str,
    context: dict[str, Any],
    expected_format: dict[str, Any],
    identity: ExecutionIdentity,
) -> str:
    identity_rule = (
        "你是隔离 Worker，只执行本角色任务。不得调用 Auto-Engineering Loop、"
        "不得推进 Tick、不得创建其他 Worker，也不得检查协调器专属能力。"
        if identity.role.value == "worker"
        else "你是 Coordinator，负责按当前 Action 驱动宿主执行。"
    )
    return "\n\n".join((
        f"## 执行角色\n\n{role}",
        "## 运行身份（机器契约）\n\n"
        f"```json\n{_stable_json(identity.to_dict())}\n```\n\n{identity_rule}",
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
    context_manifest = build_context_manifest(contract.stage, selected_context)

    if contract.execution_mode is ExecutionMode.INLINE:
        return CompiledPromptBundle(
            stage=contract.stage,
            coordinator_prompt=_render_prompt(
                role_prompt=role_prompt,
                role=contract.stage,
                context=selected_context,
                expected_format=expected_format,
                identity=ExecutionIdentity.coordinator(stage=contract.stage),
            ),
            worker_prompts=(),
            expected_format=dict(expected_format),
            context_manifest=context_manifest,
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
            identity=ExecutionIdentity.coordinator(stage=contract.stage),
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
            identity=ExecutionIdentity.worker(stage=contract.stage),
        )
        worker_identity = ExecutionIdentity.worker(stage=contract.stage)
        workers.append(CompiledWorkerPrompt(
            index=index,
            role=role,
            prompt=prompt,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            execution_identity=worker_identity.to_dict(),
        ))

    return CompiledPromptBundle(
        stage=contract.stage,
        coordinator_prompt=coordinator_prompt,
        worker_prompts=tuple(workers),
        expected_format=dict(expected_format),
        context_manifest=context_manifest,
    )


__all__ = [
    "CompiledPromptBundle",
    "CompiledWorkerPrompt",
    "PromptContextError",
    "PromptLayoutError",
    "build_context_manifest",
    "compile_prompt_bundle",
    "select_stage_context",
]
