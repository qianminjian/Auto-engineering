"""记录宿主候选 Result，且只由 Core 接受结果完成事务。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class OutcomeJournalTransitionError(ValueError):
    """Outcome journal 出现非法状态转换。"""


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
            "repairable": True,
            "semantic_payload": dict(coordinator_payload),
            "rejection": rejection,
            "rejection_history": history,
        }
        if existing is not None:
            for key in ("outcomes_fingerprint", "outcomes", "completed_at"):
                if key in existing:
                    record[key] = existing[key]
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
        record.update({
            "status": "rejected",
            "repairable": True,
            "rejection": {
                "error_code": error_code,
                "violations": list(violations),
            },
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
