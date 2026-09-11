"""记录宿主候选 Result，且只由 Core 接受结果完成事务。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class OutcomeJournalTransitionError(ValueError):
    """Outcome journal 出现非法状态转换。"""


MAX_ASSEMBLY_REPAIR_ATTEMPTS = 3


def _outcomes_fingerprint(
    action_message_id: str,
    outcomes: Sequence[Mapping[str, Any]],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action_message_id": action_message_id,
                "outcomes": [dict(item) for item in outcomes],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class OutcomeJournal:
    """实现 `prepared → accepted | rejected → prepared` 最小事务。"""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def path_for(self, action_message_id: str) -> Path:
        return (
            self._root
            / ".ae-state/host-runtime/outcomes"
            / f"{action_message_id}.json"
        )

    def record_stale_result(
        self,
        result: Mapping[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        """隔离晚到 Result 的身份元数据，不把业务 payload 写入审计区。

        晚到消息必须保持 Core projection 不变，但仍需留下可追踪证据。
        文件名由消息身份和 payload 摘要决定，因此重复投递是幂等的，
        且日志不会泄露 worker 的结果正文或错误细节。
        """

        canonical = json.dumps(
            dict(result),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        payload_sha256 = hashlib.sha256(canonical).hexdigest()
        identity = ":".join(
            str(result.get(key, ""))
            for key in ("thread_id", "message_id", "causation_id", "tick")
        )
        filename = hashlib.sha256(
            f"{identity}:{payload_sha256}".encode()
        ).hexdigest()[:32]
        record = {
            "schema_version": "1.0",
            "status": "stale",
            "reason": reason,
            "thread_id": result.get("thread_id"),
            "message_id": result.get("message_id"),
            "causation_id": result.get("causation_id"),
            "correlation_id": result.get("correlation_id"),
            "tick": result.get("tick"),
            "stage": result.get("stage"),
            "payload_sha256": payload_sha256,
        }
        path = (
            self._root
            / ".ae-state/host-runtime/stale-results"
            / f"{filename}.json"
        )
        _atomic_write(path, record)
        return record

    def load(self, action_message_id: str) -> dict[str, Any] | None:
        path = self.path_for(action_message_id)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise OutcomeJournalTransitionError("OUTCOME_JOURNAL_INVALID")
        return value

    def prepare(
        self,
        action_message_id: str,
        result: Mapping[str, Any],
        *,
        fingerprint: str,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.load(action_message_id)
        status = existing.get("status") if existing is not None else None
        if status in {"accepted", "committed"}:
            raise OutcomeJournalTransitionError("OUTCOME_ALREADY_ACCEPTED")
        if status in {"rejected", "assembly_rejected"}:
            previous_attempt = existing.get("attempt", 1) if existing else 1
            if (
                existing is not None
                and (
                    existing.get("repairable") is False
                    or (
                        isinstance(previous_attempt, int)
                        and previous_attempt >= MAX_ASSEMBLY_REPAIR_ATTEMPTS
                    )
                )
            ):
                raise OutcomeJournalTransitionError("OUTCOME_REPAIR_EXHAUSTED")
        history: list[object] = []
        attempt = 1
        if existing is not None:
            raw_history = existing.get("rejection_history", [])
            if isinstance(raw_history, list):
                history = list(raw_history)
            if status in {"rejected", "assembly_rejected"}:
                rejection = existing.get("rejection")
                if isinstance(rejection, Mapping):
                    history.append(dict(rejection))
                raw_attempt = existing.get("attempt", 1)
                attempt = raw_attempt + 1 if isinstance(raw_attempt, int) else 2
            elif (
                status == "prepared"
                and existing.get("fingerprint") == fingerprint
                and isinstance(existing.get("result"), Mapping)
            ):
                return existing
        record: dict[str, Any] = {
            "schema_version": "1.1",
            "status": "prepared",
            "action_message_id": action_message_id,
            "fingerprint": fingerprint,
            "attempt": attempt,
            "repairable": True,
            "result": dict(result),
            "rejection_history": history,
        }
        if extra is not None:
            record.update(dict(extra))
        _atomic_write(self.path_for(action_message_id), record)
        return record

    def reject_assembly(
        self,
        action_message_id: str,
        *,
        coordinator_payload: Mapping[str, Any],
        error_code: str,
        violations: Sequence[str] = (),
        outcomes: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """在 canonical Result 尚未生成时记录可修复的语义组装拒绝。"""

        existing = self.load(action_message_id)
        if existing is not None and existing.get("status") in {
            "accepted", "committed"
        }:
            raise OutcomeJournalTransitionError("OUTCOME_ALREADY_ACCEPTED")
        history: list[object] = []
        attempt = 1
        if existing is not None:
            raw_history = existing.get("rejection_history", [])
            if isinstance(raw_history, list):
                history = list(raw_history)
            prior_rejection = existing.get("rejection")
            if isinstance(prior_rejection, Mapping):
                history.append(dict(prior_rejection))
            raw_attempt = existing.get("attempt", 1)
            attempt = raw_attempt + 1 if isinstance(raw_attempt, int) else 2
        rejection = {
            "error_code": error_code,
            "violations": list(violations),
        }
        record: dict[str, Any] = {
            "schema_version": "1.1",
            "status": "assembly_rejected",
            "action_message_id": action_message_id,
            "attempt": attempt,
            "repairable": attempt < MAX_ASSEMBLY_REPAIR_ATTEMPTS,
            "semantic_payload": dict(coordinator_payload),
            "rejection": rejection,
            "rejection_history": history,
        }
        serialized_outcomes: list[dict[str, Any]] | None = None
        outcomes_fingerprint: str | None = None
        if outcomes is not None:
            serialized_outcomes = [dict(item) for item in outcomes]
            outcomes_fingerprint = _outcomes_fingerprint(
                action_message_id,
                serialized_outcomes,
            )
            record["outcomes"] = serialized_outcomes
            record["outcomes_fingerprint"] = outcomes_fingerprint
        if existing is not None:
            existing_outcomes = existing.get("outcomes")
            existing_fingerprint = existing.get("outcomes_fingerprint")
            existing_pair_is_valid = (
                isinstance(existing_outcomes, list)
                and all(isinstance(item, Mapping) for item in existing_outcomes)
                and isinstance(existing_fingerprint, str)
                and existing_fingerprint
                == _outcomes_fingerprint(action_message_id, existing_outcomes)
            )
            if existing_pair_is_valid:
                # Worker facts are immutable once journaled, but the pair must
                # be preserved atomically. Never copy an old fingerprint and
                # outcomes independently: a prior interrupted write must not
                # poison every subsequent finalize attempt.
                record["outcomes"] = existing_outcomes
                record["outcomes_fingerprint"] = existing_fingerprint
            elif serialized_outcomes is None:
                # A corrupt or legacy pair cannot be treated as authoritative.
                # Without current facts, leave the record explicitly fact-less;
                # the next repair must provide a fresh validated outcome.
                record.pop("outcomes", None)
                record.pop("outcomes_fingerprint", None)
            if "completed_at" in existing:
                record["completed_at"] = existing["completed_at"]
        _atomic_write(self.path_for(action_message_id), record)
        return record

    def reject(
        self,
        action_message_id: str,
        *,
        error_code: str,
        violations: Sequence[str] = (),
    ) -> dict[str, Any]:
        record = self.load(action_message_id)
        if record is None or record.get("status") != "prepared":
            raise OutcomeJournalTransitionError("OUTCOME_NOT_PREPARED")
        attempt = record.get("attempt", 1)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            attempt = 1
        record.update({
            "status": "rejected",
            "repairable": attempt < MAX_ASSEMBLY_REPAIR_ATTEMPTS,
            "rejection": {
                "error_code": error_code,
                "violations": list(violations),
            },
        })
        _atomic_write(self.path_for(action_message_id), record)
        return record

    def reopen_assembly_repair(self, action_message_id: str, *, reason: str) -> dict[str, Any]:
        """显式恢复一次被错误结果耗尽的 assembly repair 预算。

        仅供人工确认后的恢复工具使用；保留完整拒绝历史，并把预算回退到
        最后一次可修复尝试。它不改变 Worker outcomes，也不产生 Core 事实。
        """

        record = self.load(action_message_id)
        if record is None or record.get("status") not in {
            "rejected", "assembly_rejected",
        }:
            raise OutcomeJournalTransitionError("OUTCOME_NOT_REPAIR_EXHAUSTED")
        if record.get("repairable") is not False:
            raise OutcomeJournalTransitionError("OUTCOME_REPAIR_NOT_EXHAUSTED")
        rejection = record.get("rejection")
        history = list(record.get("rejection_history", []))
        if isinstance(rejection, Mapping):
            history.append({**dict(rejection), "reopened_reason": reason})
        record.update({
            "status": "assembly_rejected",
            "attempt": MAX_ASSEMBLY_REPAIR_ATTEMPTS - 1,
            "repairable": True,
            "rejection_history": history,
            "reopened_reason": reason,
        })
        _atomic_write(self.path_for(action_message_id), record)
        return record

    def accept(
        self,
        action_message_id: str,
        *,
        accepted_result_message_id: str,
    ) -> dict[str, Any]:
        record = self.load(action_message_id)
        if record is None or record.get("status") != "prepared":
            raise OutcomeJournalTransitionError("OUTCOME_NOT_PREPARED")
        result = record.get("result")
        if (
            not isinstance(result, Mapping)
            or result.get("message_id") != accepted_result_message_id
        ):
            raise OutcomeJournalTransitionError("OUTCOME_RESULT_IDENTITY_MISMATCH")
        record.update({
            "status": "accepted",
            "repairable": False,
            "accepted_result_message_id": accepted_result_message_id,
        })
        _atomic_write(self.path_for(action_message_id), record)
        return record

    def complete_from_core(
        self,
        submitted_result: Mapping[str, Any],
        core_response: Mapping[str, Any],
    ) -> bool:
        """按 Core 对候选 Result 的真实响应完成事务；返回是否需修复。"""

        action_message_id = submitted_result.get("causation_id")
        result_message_id = submitted_result.get("message_id")
        if not isinstance(action_message_id, str) or not action_message_id:
            return False
        record = self.load(action_message_id)
        if record is None or record.get("status") != "prepared":
            return False
        if core_response.get("action") == "error":
            raw_code = core_response.get("error_code")
            raw_violations = core_response.get("violations")
            self.reject(
                action_message_id,
                error_code=(
                    raw_code if isinstance(raw_code, str) else "RESULT_REJECTED"
                ),
                violations=(
                    [str(item) for item in raw_violations]
                    if isinstance(raw_violations, list)
                    else []
                ),
            )
            return True
        if isinstance(result_message_id, str) and result_message_id:
            self.accept(
                action_message_id,
                accepted_result_message_id=result_message_id,
            )
        return False
