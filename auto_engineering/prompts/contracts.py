"""Prompt Contract 内部模型与注册表。

本模块只描述提示词执行模式、上下文和角色边界，不改变 Action/Result v1.1。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from auto_engineering.config.constants import _SPAWN_CONFIG


class ExecutionMode(StrEnum):
    """提示词由宿主执行的三种模式。"""

    INLINE = "inline"
    SINGLE_WORKER = "single_worker"
    MULTI_WORKER = "multi_worker"


@dataclass(frozen=True, slots=True)
class StagePromptContract:
    """一个 stage 的稳定提示词交付契约。"""

    stage: str
    execution_mode: ExecutionMode
    required_context: tuple[str, ...]
    worker_roles: tuple[str, ...] = ()


_CONTRACTS: Mapping[str, StagePromptContract] = MappingProxyType({
    "gap_scan": StagePromptContract(
        "gap_scan",
        ExecutionMode.INLINE,
        ("design_doc_path", "project_root", "requirement"),
    ),
    "research": StagePromptContract(
        "research",
        ExecutionMode.INLINE,
        ("gap", "knowledge_sources", "requirement"),
    ),
    "architect": StagePromptContract(
        "architect",
        ExecutionMode.SINGLE_WORKER,
        ("requirement", "design_doc_path"),
        ("architect",),
    ),
    "developer": StagePromptContract(
        "developer",
        ExecutionMode.INLINE,
        ("requirement", "feedback", "batch_id", "component", "tasks", "toolchain"),
    ),
    "critic": StagePromptContract(
        "critic",
        ExecutionMode.SINGLE_WORKER,
        ("requirement", "files_changed", "test_results", "design_scope"),
        ("critic",),
    ),
    "component_verifier": StagePromptContract(
        "component_verifier",
        ExecutionMode.SINGLE_WORKER,
        ("component", "design_section", "design_spec", "implementation_files"),
        ("component_verifier",),
    ),
    "plate_deep_audit": StagePromptContract(
        "plate_deep_audit",
        ExecutionMode.MULTI_WORKER,
        ("plate", "components"),
        ("contract_dataflow", "architecture", "code_quality_virtualization"),
    ),
    "system_verifier": StagePromptContract(
        "system_verifier",
        ExecutionMode.SINGLE_WORKER,
        ("design_doc_path", "file_list", "component_coverage"),
        ("system_verifier",),
    ),
    "system_deep_audit": StagePromptContract(
        "system_deep_audit",
        ExecutionMode.MULTI_WORKER,
        ("coverage_map", "audit_scope"),
        (
            "architecture",
            "code_quality",
            "engineering",
            "virtualization",
            "team_design_coverage",
        ),
    ),
})


def default_prompt_contracts() -> Mapping[str, StagePromptContract]:
    """返回进程内只读的默认契约注册表。"""

    return _CONTRACTS


def validate_contract_registry(
    contracts: Mapping[str, StagePromptContract],
) -> list[str]:
    """检查契约、spawn 配置和多 Agent 模板布局是否一致。"""

    errors: list[str] = []
    role_dir = Path(__file__).resolve().parent / "roles"

    for stage, contract in contracts.items():
        spawn = _SPAWN_CONFIG.get(stage)
        expected_count = 0 if spawn is None else int(spawn["count"])

        if expected_count == 0:
            if contract.execution_mode is not ExecutionMode.INLINE:
                errors.append(f"{stage}: 非 spawn stage 必须使用 inline")
            if contract.worker_roles:
                errors.append(f"{stage}: inline stage 不应声明 worker_roles")
            continue

        expected_mode = (
            ExecutionMode.SINGLE_WORKER
            if expected_count == 1
            else ExecutionMode.MULTI_WORKER
        )
        if contract.execution_mode is not expected_mode:
            errors.append(
                f"{stage}: execution_mode={contract.execution_mode.value}, "
                f"期望 {expected_mode.value}"
            )
        if len(contract.worker_roles) != expected_count:
            errors.append(
                f"{stage}: worker_roles={len(contract.worker_roles)}, "
                f"期望 {expected_count}"
            )

        if expected_count > 1:
            prompt_path = role_dir / f"{stage}.md"
            try:
                section_count = len(
                    prompt_path.read_text(encoding="utf-8").split("\n***\n")
                )
            except (OSError, UnicodeDecodeError):
                errors.append(f"{stage}: 无法读取多 Agent 角色模板")
                continue
            if section_count != expected_count + 1:
                errors.append(
                    f"{stage}: 模板分区={section_count}, "
                    f"期望 {expected_count + 1}"
                )

    return errors


__all__ = [
    "ExecutionMode",
    "StagePromptContract",
    "default_prompt_contracts",
    "validate_contract_registry",
]
