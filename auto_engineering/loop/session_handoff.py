"""v5.8 会话 rollover/claim 的确定性幂等聚合。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from auto_engineering.loop.resume_capsule import ResumeCapsule

_ROLLOVER_REASONS = frozenset({
    "context_soft_limit",
    "context_hard_limit",
    "tick_limit",
    "time_limit",
    "manual",
})


class SessionHandoffError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class Claim:
    session_id: str
    host: str


class SessionHandoff:
    """管理一个 thread 的单个 pending handoff。

    聚合只保存结构化 Capsule 和 claim 状态，不接触宿主 transcript。
    持久化层可通过 ``to_dict``/``from_dict`` 在同一 Tick 事务中保存。
    """

    def __init__(
        self,
        *,
        token_factory: Callable[[], str] | None = None,
        artifact_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._token_factory = token_factory or (lambda: str(uuid4()))
        self._artifact_id_factory = artifact_id_factory or (lambda: str(uuid4()))
        self._rollover_action: dict[str, Any] | None = None
        self._capsule: ResumeCapsule | None = None
        self._claim: Claim | None = None

    @property
    def active_session_id(self) -> str | None:
        return self._claim.session_id if self._claim is not None else None

    def request_rollover(
        self,
        *,
        current_session_id: str,
        reason: str,
        capsule: ResumeCapsule,
    ) -> dict[str, Any]:
        if reason not in _ROLLOVER_REASONS:
            raise SessionHandoffError("SESSION_ROLLOVER_INVALID", "rollover reason 无效")
        if capsule.source_session_id != current_session_id:
            raise SessionHandoffError(
                "SESSION_ROLLOVER_INVALID", "Capsule source session 不匹配"
            )
        if self._rollover_action is not None:
            if (
                self._rollover_action["current_session_id"] != current_session_id
                or self._rollover_action["reason"] != reason
                or self._capsule != capsule
            ):
                raise SessionHandoffError(
                    "SESSION_HANDOFF_PENDING", "已有不同的 session handoff"
                )
            return dict(self._rollover_action)

        self._capsule = capsule
        self._rollover_action = {
            "action": "session_rollover",
            "reason": reason,
            "current_session_id": current_session_id,
            "capsule": {
                "artifact_id": self._artifact_id_factory(),
                "sha256": capsule.payload_sha256,
                "schema_version": capsule.schema_version,
            },
            "claim_token": self._token_factory(),
            "expires_at": None,
        }
        return dict(self._rollover_action)

    def claim(self, result: Mapping[str, Any]) -> dict[str, Any]:
        if self._rollover_action is None or self._capsule is None:
            raise SessionHandoffError("SESSION_CLAIM_INVALID", "没有待接管的 session")
        if result.get("stage") != "session_claimed":
            raise SessionHandoffError("SESSION_CLAIM_INVALID", "Result stage 必须为 session_claimed")
        if result.get("claim_token") != self._rollover_action["claim_token"]:
            raise SessionHandoffError("SESSION_CLAIM_INVALID", "claim token 无效")
        session_id = result.get("session_id")
        host = result.get("host")
        if not isinstance(session_id, str) or not session_id:
            raise SessionHandoffError("SESSION_CLAIM_INVALID", "session_id 必须为非空字符串")
        if not isinstance(host, str) or not host:
            raise SessionHandoffError("SESSION_CLAIM_INVALID", "host 必须为非空字符串")
        claim = Claim(session_id=session_id, host=host)
        if self._claim is not None and self._claim != claim:
            raise SessionHandoffError(
                "SESSION_CLAIM_CONFLICT", "claim token 已由其他 session 使用"
            )
        self._claim = claim
        return dict(self._capsule.active_action)

    def assert_session_may_submit(self, session_id: str) -> None:
        if self._rollover_action is None:
            return
        if self._claim is None or self._claim.session_id != session_id:
            raise SessionHandoffError(
                "SESSION_NOT_ACTIVE", "旧 session 或未接管 session 不得提交业务 Result"
            )


__all__ = ["Claim", "SessionHandoff", "SessionHandoffError"]
