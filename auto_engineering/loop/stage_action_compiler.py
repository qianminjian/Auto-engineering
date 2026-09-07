"""Stage Action 编译的 canonical boundary。

ActionBuilder 负责调用生命周期；本模块只编译严格 stage Action 结构及其
Worker invocation 合同，所有 effect 仍经 target 提供的显式边界提交。
"""

from __future__ import annotations

import shlex
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

from auto_engineering.config.constants import _SPAWN_CONFIG
from auto_engineering.engine.state import EngineState
from auto_engineering.host.runtime_identity import ExecutionIdentity
from auto_engineering.host.spawn_contract import WorkerInvocationSpec
from auto_engineering.loop.action_prompt_contract import (
    INLINE_INSTRUCTION,
    SPAWN_INSTRUCTION,
    SPAWN_MULTI_INSTRUCTION,
    SPAWN_SINGLE_INSTRUCTION,
)
from auto_engineering.loop.actions import business_result_contract
from auto_engineering.loop.design_authority import DesignAuthorityPolicy
from auto_engineering.loop.worker_paths import worker_outcome_path as _worker_outcome_path
from auto_engineering.prompts.compiler import (
    CORE_OWNED_OUTPUT_FIELDS,
    compile_prompt_bundle,
)
from auto_engineering.prompts.contracts import default_prompt_contracts


class StageActionTarget(Protocol):
    """Stage Action 编译所需的最小 ActionBuilder 视图。"""

    project_root: Path
    @property
    def _state(self) -> EngineState: ...
    _design_authority_projection: dict[str, Any]

    def _stable_token(self, role: str, content_hash: str = "") -> str: ...

    def _write_spawn_proof_file(self, proof_token: str, stage: str) -> None: ...

    def _load_prompt(self, stage: str) -> str: ...

    def _write_coordinator_prompt(self, prompt: str) -> dict[str, object]: ...

    def _write_prompt_artifact(self, prompt: str, prompt_hash: str) -> str: ...


_SPAWN_INSTRUCTION = SPAWN_INSTRUCTION
_SPAWN_MULTI_INSTRUCTION = SPAWN_MULTI_INSTRUCTION
_SPAWN_SINGLE_INSTRUCTION = SPAWN_SINGLE_INSTRUCTION
_INLINE_INSTRUCTION = INLINE_INSTRUCTION
_CORE_OWNED_RESULT_FIELDS = CORE_OWNED_OUTPUT_FIELDS


def build_stage_action(
    target: StageActionTarget, base: dict, action: str,
    context: dict | None = None, expected_format: dict | None = None, **extra,
) -> dict:
    """Construct a stage action dict.

    DS-15: subagent prompt is read from prompts/roles/<stage>.md verbatim.
    No context injection, no expected_format for subagent.  Team Lead
    extracts fields from subagent output and maps to result JSON per
    expected_format.

    Spawn proof: engine pre-writes the proof file, instruction references
    the path.  Token is never embedded in instruction text → PII-safe.
    """
    result: dict = {**base, "action": action}
    authority = DesignAuthorityPolicy.default().to_dict()
    ledger = deepcopy(target._design_authority_projection)
    result["design_authority"] = authority
    result["design_decision_ledger"] = ledger
    result["execution_identity"] = ExecutionIdentity.coordinator(
        stage=action,
    ).to_dict()
    compiled_prompt = False
    contract = default_prompt_contracts().get(action)
    if contract is not None:
        context = dict(context or {})
        if "design_authority" in contract.optional_context:
            context.setdefault("design_authority", authority)
        if "design_decision_ledger" in contract.optional_context:
            context.setdefault("design_decision_ledger", ledger)
    spawn_template = _SPAWN_CONFIG.get(action)
    if spawn_template is not None:
        spawn = deepcopy(spawn_template)
        audit_files = (
            context.get("audit_scope", {}).get("files", [])
            if isinstance(context, dict)
            and isinstance(context.get("audit_scope"), dict)
            else []
        )
        compact_system_audit = (
            action == "system_deep_audit"
            and isinstance(audit_files, list)
            and len(audit_files) <= 20
        )
        if compact_system_audit:
            spawn.update({"count": 1, "parallel": False, "effort": "high"})
            result["audit_execution_profile"] = {
                "profile": "compact",
                "audited_file_count": len(audit_files),
                "dimension_count": 5,
            }
        elif action == "system_deep_audit":
            result["audit_execution_profile"] = {
                "profile": "specialist",
                "audited_file_count": len(audit_files),
                "dimension_count": 5,
            }
        result["spawn"] = spawn
        result["spawn"]["contract_version"] = "1.0"
        # DS-15: spawn proof — 生产路径只规划文件，不在 Action 构建时写入。
        proof_token = target._stable_token("total")
        result["spawn_proof_token"] = proof_token
        target._write_spawn_proof_file(proof_token, action)

        count = spawn["count"]
        is_multi = count > 1
        multi_inst = _SPAWN_MULTI_INSTRUCTION if is_multi else _SPAWN_SINGLE_INSTRUCTION

        result["instruction"] = _SPAWN_INSTRUCTION.format(
            count=count,
            parallel=" (parallel)" if spawn.get("parallel") else "",
            multi_instruction=multi_inst,
            stage=action,
            effort=spawn.get("effort", "high"),
            proof_token=proof_token,
            project_root=shlex.quote(str(target.project_root.resolve())),
        )

        # DS-15: read prompt from file
        full_prompt = target._load_prompt(action)
        worker_expected_format = dict(expected_format or {})
        coordinator_expected_format = dict(worker_expected_format)

        if is_multi:
            contract = default_prompt_contracts()[action]
            bundle = compile_prompt_bundle(
                contract=contract,
                role_prompt=full_prompt,
                context=dict(context or {}),
                expected_format=worker_expected_format,
            )
            result["coordinator_prompt_ref"] = target._write_coordinator_prompt(
                bundle.coordinator_prompt
            )
            result.setdefault("extensions", {})[
                "context_manifest"
            ] = bundle.context_manifest
            invocations: list[dict] = []
            for worker in bundle.worker_prompts:
                receipt_token = target._stable_token(
                    f"worker-{worker.index}", worker.prompt_hash
                )
                target._write_spawn_proof_file(receipt_token, action)
                invocations.append(
                    WorkerInvocationSpec(
                        worker_id=f"{action}-{worker.index}",
                        role=worker.role,
                        prompt_ref=target._write_prompt_artifact(
                            worker.prompt, worker.prompt_hash
                        ),
                        prompt_sha256=worker.prompt_hash,
                        requested_effort=str(spawn.get("effort", "high")),
                        isolation="fresh_context",
                        capabilities={
                            "may_drive_loop": False,
                            "may_spawn_workers": False,
                        },
                        receipt_path=(
                            f".ae-state/spawn-proofs/{receipt_token}.json"
                        ),
                        outcome_path=_worker_outcome_path(
                            f"{target.project_root.resolve()}:{target._state.tick}:{action}:{worker.index}"
                        ),
                    ).to_dict()
                )
            result["spawn"]["invocations"] = invocations
            compiled_prompt = True
        else:
            single_contract = default_prompt_contracts().get(action)
            if compact_system_audit and single_contract is not None:
                from auto_engineering.prompts.contracts import (
                    ExecutionMode,
                    StagePromptContract,
                )

                role_sections = full_prompt.split("\n***\n")
                compact_role_prompt = (
                    "你是小型项目五维系统审计 Worker。必须在同一个隔离上下文中完成："
                    "架构合理性、代码质量、工程化规范、虚化实现、团队与设计覆盖。"
                    "逐维执行下列清单，最后合并去重并直接按输出契约返回；不得遗漏维度。\n\n"
                    + "\n\n".join(role_sections[1:])
                )
                compact_contract = StagePromptContract(
                    stage=single_contract.stage,
                    execution_mode=ExecutionMode.SINGLE_WORKER,
                    required_context=single_contract.required_context,
                    worker_roles=("system_audit_compact",),
                    optional_context=single_contract.optional_context,
                    artifact_kinds=single_contract.artifact_kinds,
                    max_context_bytes=single_contract.max_context_bytes,
                )
                bundle = compile_prompt_bundle(
                    contract=compact_contract,
                    role_prompt=compact_role_prompt,
                    context=dict(context or {}),
                    expected_format=worker_expected_format,
                )
                result["worker_execution_identity"] = (
                    bundle.worker_prompts[0].execution_identity
                )
                worker = bundle.worker_prompts[0]
                receipt_token = target._stable_token("worker-0", worker.prompt_hash)
                target._write_spawn_proof_file(receipt_token, action)
                prompt_ref = target._write_prompt_artifact(
                    worker.prompt, worker.prompt_hash,
                )
                result["spawn"]["invocations"] = [
                    WorkerInvocationSpec(
                        worker_id=f"{action}-0",
                        role=worker.role,
                        prompt_ref=prompt_ref,
                        prompt_sha256=worker.prompt_hash,
                        requested_effort=str(spawn.get("effort", "high")),
                        isolation="fresh_context",
                        capabilities={
                            "may_drive_loop": False,
                            "may_spawn_workers": False,
                        },
                        receipt_path=(
                            f".ae-state/spawn-proofs/{receipt_token}.json"
                        ),
                        outcome_path=_worker_outcome_path(
                            f"{target.project_root.resolve()}:{target._state.tick}:{action}:0"
                        ),
                    ).to_dict()
                ]
                result.setdefault("extensions", {})[
                    "context_manifest"
                ] = bundle.context_manifest
                compiled_prompt = True
            elif single_contract is not None and action in {
                "architect", "developer", "critic", "component_verifier",
                "system_verifier",
            }:
                prompt_context = dict(context or {})
                prompt_context.setdefault("requirement", base.get("requirement"))
                prompt_context.setdefault("feedback", base.get("feedback"))
                bundle = compile_prompt_bundle(
                    contract=single_contract,
                    role_prompt=full_prompt,
                    context=prompt_context,
                    expected_format=worker_expected_format,
                )
                result["worker_execution_identity"] = (
                    bundle.worker_prompts[0].execution_identity
                )
                worker = bundle.worker_prompts[0]
                receipt_token = target._stable_token("worker-0", worker.prompt_hash)
                target._write_spawn_proof_file(receipt_token, action)
                prompt_ref = target._write_prompt_artifact(
                    worker.prompt, worker.prompt_hash,
                )
                result["spawn"]["invocations"] = [
                    WorkerInvocationSpec(
                        worker_id=f"{action}-0",
                        role=worker.role,
                        prompt_ref=prompt_ref,
                        prompt_sha256=worker.prompt_hash,
                        requested_effort=str(spawn.get("effort", "high")),
                        isolation="fresh_context",
                        capabilities={
                            "may_drive_loop": False,
                            "may_spawn_workers": False,
                        },
                        receipt_path=(
                            f".ae-state/spawn-proofs/{receipt_token}.json"
                        ),
                        outcome_path=_worker_outcome_path(
                            f"{target.project_root.resolve()}:{target._state.tick}:{action}:0"
                        ),
                    ).to_dict()
                ]
                result.setdefault("extensions", {})[
                    "context_manifest"
                ] = bundle.context_manifest
                compiled_prompt = True
            else:
                prompt_hash = __import__("hashlib").sha256(
                    full_prompt.encode("utf-8")
                ).hexdigest()
                receipt_token = target._stable_token("worker-0", prompt_hash)
                target._write_spawn_proof_file(receipt_token, action)
                result["spawn"]["invocations"] = [
                    WorkerInvocationSpec(
                        worker_id=f"{action}-0",
                        role=action,
                        prompt_ref=target._write_prompt_artifact(
                            full_prompt, prompt_hash,
                        ),
                        prompt_sha256=prompt_hash,
                        requested_effort=str(spawn.get("effort", "high")),
                        isolation="fresh_context",
                        capabilities={
                            "may_drive_loop": False,
                            "may_spawn_workers": False,
                        },
                        receipt_path=(
                            f".ae-state/spawn-proofs/{receipt_token}.json"
                        ),
                        outcome_path=_worker_outcome_path(
                            f"{target.project_root.resolve()}:{target._state.tick}:{action}:0"
                        ),
                    ).to_dict()
                ]

        # T141: spawned field in expected_format (for Team Lead, NOT subagent)
        if expected_format is not None:
            expected_format = coordinator_expected_format
    else:
        # Non-spawn stage — inline instruction
        if action not in ("developer",):  # developer has custom instruction
            result["instruction"] = _INLINE_INSTRUCTION.format(stage=action)
    if context and not compiled_prompt:
        result["context"] = context
    if expected_format is not None:
        result["expected_format"] = {
            key: value
            for key, value in expected_format.items()
            if key not in _CORE_OWNED_RESULT_FIELDS
        }
        result_contract = business_result_contract(
            action,
            result["expected_format"],
        )
        if result_contract is not None:
            result["result_contract"] = result_contract
    result.update(extra)
    return result
