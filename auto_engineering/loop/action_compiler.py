"""无副作用的 Action Envelope 编译器。"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from auto_engineering.loop.effects import EffectIntent
from auto_engineering.loop.protocol import action_envelope, validate_action_envelope
from auto_engineering.loop.runtime_revision import RuntimeRevision


@dataclass(frozen=True, slots=True)
class ActionIdentity:
    message_id: str
    correlation_id: str
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionDraft:
    payload: Mapping[str, Any]
    effects: tuple[EffectIntent, ...] = ()


class ActionCompiler:
    """只依赖显式输入生成 ActionDraft，不读取 clock/UUID/文件系统。"""

    def compile(
        self,
        *,
        payload: Mapping[str, Any],
        identity: ActionIdentity,
        runtime_revision: RuntimeRevision,
        issued_at: str,
        effects: tuple[EffectIntent, ...] = (),
    ) -> ActionDraft:
        raw = copy.deepcopy(dict(payload))
        thread_id = raw.get("thread_id")
        if identity.correlation_id != thread_id:
            raise ValueError("Action correlation_id 必须等于 thread_id")
        compiled = action_envelope(
            raw,
            message_id=identity.message_id,
            causation_id=identity.causation_id,
        )
        ae = compiled["extensions"].setdefault("ae", {})
        ae["runtime_revision"] = runtime_revision.to_dict()
        ae["issued_at"] = issued_at
        validate_action_envelope(compiled)
        return ActionDraft(payload=compiled, effects=effects)


__all__ = ["ActionCompiler", "ActionDraft", "ActionIdentity"]
