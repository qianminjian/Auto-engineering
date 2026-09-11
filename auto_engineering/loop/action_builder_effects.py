"""ActionBuilder 的 artifact、effect 和 spawn proof 绑定能力。"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from auto_engineering.loop.effects import (
    EffectExecutor,
    EffectIntent,
    EffectReceipt,
    WriteContentAddressedArtifact,
    WriteJsonArtifact,
)

_logger = logging.getLogger("ae.loop.action_builder")


class ActionBuilderEffectsMixin:
    """隔离 Action 构建器的副作用边界，保持主 builder 专注于规划。"""

    project_root: Path
    _effect_intent_sink: Callable[[EffectIntent], None] | None
    _effect_sink: Callable[[EffectReceipt], None] | None

    def _write_prompt_artifact(self, prompt: str, prompt_hash: str) -> str:
        """内容寻址保存 Worker prompt，避免全部正文进入 Coordinator Action。"""
        receipt = self._execute_effect(
            WriteContentAddressedArtifact(
                kind="prompt",
                content=prompt,
                sha256=prompt_hash,
            )
        )
        return receipt.relative_path

    def _write_coordinator_prompt(self, prompt: str) -> dict[str, object]:
        """把多 Worker 合并提示词作为唯一 Coordinator Artifact 引用。"""

        encoded = prompt.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        path = self._write_prompt_artifact(prompt, digest)
        return {
            "path": path,
            "sha256": digest,
            "size_bytes": len(encoded),
            "media_type": "text/plain; charset=utf-8",
        }

    def _execute_effect(self, intent: EffectIntent) -> EffectReceipt:
        if self._effect_intent_sink is None:
            raise RuntimeError("ACTION_PLAN_REQUIRED")
        self._effect_intent_sink(intent)
        receipt = EffectExecutor(self.project_root).preview(intent)
        if self._effect_sink is not None:
            self._effect_sink(receipt)
        return receipt

    def _load_prompt(self, stage: str) -> str:
        """加载唯一的 PromptRegistry 组合结果；注册表失败必须显式终止。"""
        from auto_engineering.loop import action_builder as builder_module

        try:
            combined = builder_module.default_registry().get(stage)
        except (KeyError, OSError, UnicodeDecodeError, ValueError) as exc:
            _logger.error(
                "PromptRegistry 加载失败，拒绝发送未编译提示词: stage=%s", stage
            )
            raise RuntimeError("PROMPT_REGISTRY_UNAVAILABLE") from exc
        if not combined.strip():
            raise RuntimeError("PROMPT_REGISTRY_EMPTY")
        return combined

    def _write_spawn_proof_file(self, proof_token: str, stage: str) -> None:
        """预写 spawn proof，供 Worker 完成后追加事实。"""
        payload = {"token": proof_token, "stage": stage, "status": "pending"}
        self._execute_effect(
            WriteJsonArtifact(
                relative_path=f"spawn-proofs/{proof_token}.json",
                payload=payload,
            )
        )
        self._execute_effect(
            WriteJsonArtifact(
                relative_path=f"spawn-challenges/{proof_token}.json",
                payload=payload,
            )
        )

    def bind_spawn_proofs(self, action: dict) -> None:
        """在 Action 获得协议身份后，把所有 proof 绑定到该 Action。"""
        token_roles = [(action.get("spawn_proof_token"), "total", None)]
        spawn = action.get("spawn")
        if isinstance(spawn, dict):
            invocations = spawn.get("invocations", [])
            if isinstance(invocations, list):
                token_roles.extend(
                    (
                        Path(str(invocation.get("receipt_path", ""))).stem,
                        "worker",
                        invocation.get("requested_effort"),
                    )
                    for invocation in invocations
                    if isinstance(invocation, dict)
                )
        for token, proof_role, requested_effort in token_roles:
            if not isinstance(token, str) or not token:
                continue
            if self._effect_intent_sink is not None:
                payload: dict[str, Any] = {
                    "token": token,
                    "thread_id": action.get("thread_id"),
                    "action_message_id": action.get("message_id"),
                    "stage": action.get("stage"),
                    "proof_role": proof_role,
                    "status": "pending",
                }
                if requested_effort is not None:
                    payload["requested_effort"] = requested_effort
                self._execute_effect(
                    WriteJsonArtifact(
                        relative_path=f"spawn-proofs/{token}.json",
                        payload=payload,
                    )
                )
                self._execute_effect(
                    WriteJsonArtifact(
                        relative_path=f"spawn-challenges/{token}.json",
                        payload=payload,
                    )
                )
                continue
            proof_file = (
                self.project_root / ".ae-state" / "spawn-proofs" / f"{token}.json"
            )
            challenge_file = (
                self.project_root
                / ".ae-state"
                / "spawn-challenges"
                / f"{token}.json"
            )
            try:
                payload = json.loads(proof_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"SPAWN_PROOF_BIND_FAILED: {token}") from exc
            payload.update(
                {
                    "token": token,
                    "thread_id": action["thread_id"],
                    "action_message_id": action["message_id"],
                    "stage": action["stage"],
                    "proof_role": proof_role,
                }
            )
            if requested_effort is not None:
                payload["requested_effort"] = requested_effort
            self._execute_effect(
                WriteJsonArtifact(
                    relative_path=f"spawn-proofs/{token}.json",
                    payload=payload,
                )
            )
            try:
                challenge_payload = json.loads(
                    challenge_file.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"SPAWN_CHALLENGE_BIND_FAILED: {token}") from exc
            challenge_payload.update(
                {
                    "token": token,
                    "thread_id": action["thread_id"],
                    "action_message_id": action["message_id"],
                    "stage": action["stage"],
                    "proof_role": proof_role,
                }
            )
            if requested_effort is not None:
                challenge_payload["requested_effort"] = requested_effort
            self._execute_effect(
                WriteJsonArtifact(
                    relative_path=f"spawn-challenges/{token}.json",
                    payload=challenge_payload,
                )
            )
