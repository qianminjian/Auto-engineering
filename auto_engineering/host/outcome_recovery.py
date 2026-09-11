"""Core-owned outcome journal 的恢复与文件物化边界。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host.worker_evidence import (
    HostEvidenceValidationError,
    _atomic_write_json,
    _canonical_bytes,
)

_Finalize = Callable[..., dict[str, Any]]


class OutcomeRecoveryService:
    """只恢复同一 active Action 的 Journal，不重新启动 Worker。"""

    def __init__(
        self,
        project_root: Path,
        *,
        finalize: _Finalize,
        finalize_to_file: _Finalize,
    ) -> None:
        self.project_root = project_root.resolve()
        self._finalize = finalize
        self._finalize_to_file = finalize_to_file

    def restore_committed_result_to_file(
        self,
        *,
        action: Mapping[str, Any],
        result_path: Path,
        outcomes_path: Path | None = None,
    ) -> dict[str, Any] | None:
        """从 Core-owned journal 恢复与 active Action 绑定的 Result。

        无 committed journal 表示应执行正常 Worker 路径；已有 journal 但
        身份不一致则 fail-closed，不得回退为重新 spawn。
        """

        message_id = action.get("message_id")
        thread_id = action.get("thread_id")
        stage = action.get("stage")
        if (
            not isinstance(message_id, str)
            or not message_id
            or not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(stage, str)
            or not stage
        ):
            raise HostEvidenceValidationError(("ACTION_IDENTITY_INVALID",))
        journal_path = (
            self.project_root
            / ".ae-state/host-runtime/outcomes"
            / f"{message_id}.json"
        )
        journal = self.read_json(journal_path)
        if journal is None:
            return None
        if journal.get("status") == "rejected":
            # Core 已拒绝候选 Result，但 Worker 事实仍是同一 Action 的权威事实；
            # 修复上下文只能拿到这份原文，绝不能因 rejected 状态重新 spawn。
            if outcomes_path is None:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_PATH_MISSING",)
                )
            outcomes = self.authoritative_outcomes(
                journal=journal,
                action_message_id=message_id,
                required=True,
            )
            if outcomes is None:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_MISSING",)
                )
            self.write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") == "assembly_rejected":
            # 语义组装拒绝通常保留已完成 Worker；有事实时恢复并复用，
            # 没有事实则允许当前 Action 首次执行 Worker。
            outcomes = self.authoritative_outcomes(
                journal=journal,
                action_message_id=message_id,
                required=False,
            )
            if outcomes is not None and outcomes_path is not None:
                self.write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") == "prepared" and not isinstance(
            journal.get("result"), dict
        ):
            outcomes = journal.get("outcomes")
            if (
                journal.get("schema_version") != "1.0"
                or journal.get("action_message_id") != message_id
                or not isinstance(outcomes, list)
            ):
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_PREPARED_INVALID",)
                )
            if outcomes_path is not None:
                # prepared journal 已在 Worker 完成后原子落盘，是 outcome
                # 的权威恢复点；宿主工作副本只能由它重建，不能反向改写事实。
                self.write_outcomes_file(outcomes_path, outcomes)
            return None
        if journal.get("status") not in {"prepared", "accepted", "committed"}:
            return None
        result = journal.get("result")
        # 早期 T517 build 曾把失败尝试误写为 committed；失败不是成功证据，
        # 恢复时必须允许同一 active Action 重新执行 Worker。
        if isinstance(result, dict) and result.get("spawned") is False:
            return None
        if (
            journal.get("schema_version") not in {"1.0", "1.1"}
            or journal.get("action_message_id") != message_id
            or not isinstance(result, dict)
            or result.get("message_type") != "result"
            or result.get("causation_id") != message_id
            or result.get("thread_id") != thread_id
            or result.get("stage") != stage
            or result.get("tick") != int(action.get("tick", 0))
        ):
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_RESULT_IDENTITY_MISMATCH",)
            )
        target = (
            result_path.resolve()
            if result_path.is_absolute()
            else (self.project_root / result_path).resolve()
        )
        if target != self.project_root and self.project_root not in target.parents:
            raise HostEvidenceValidationError(
                ("RESULT_OUTPUT_PATH_OUTSIDE_PROJECT",)
            )
        _atomic_write_json(target, result)
        if outcomes_path is not None:
            outcomes = journal.get("outcomes", [])
            if not isinstance(outcomes, list):
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_INVALID",)
                )
            outcomes_target = (
                outcomes_path.resolve()
                if outcomes_path.is_absolute()
                else (self.project_root / outcomes_path).resolve()
            )
            if (
                outcomes_target != self.project_root
                and self.project_root not in outcomes_target.parents
            ):
                raise HostEvidenceValidationError(
                    ("OUTCOMES_OUTPUT_PATH_OUTSIDE_PROJECT",)
                )
            _atomic_write_json(outcomes_target, {"outcomes": outcomes})
        return dict(result)

    def write_outcomes_file(
        self,
        outcomes_path: Path,
        outcomes: Sequence[Mapping[str, Any]],
    ) -> None:
        target = (
            outcomes_path.resolve()
            if outcomes_path.is_absolute()
            else (self.project_root / outcomes_path).resolve()
        )
        if target == self.project_root or self.project_root not in target.parents:
            raise HostEvidenceValidationError(
                ("OUTCOMES_OUTPUT_PATH_OUTSIDE_PROJECT",)
            )
        _atomic_write_json(target, {"outcomes": [dict(item) for item in outcomes]})

    @staticmethod
    def authoritative_outcomes(
        *,
        journal: Mapping[str, Any],
        action_message_id: str,
        required: bool,
    ) -> list[dict[str, Any]] | None:
        raw = journal.get("outcomes")
        if journal.get("action_message_id") != action_message_id:
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_ACTION_IDENTITY_MISMATCH",)
            )
        if not isinstance(raw, list):
            if required:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_MISSING",)
                )
            return None
        if any(not isinstance(item, Mapping) for item in raw):
            raise HostEvidenceValidationError(
                ("OUTCOME_JOURNAL_OUTCOMES_INVALID",)
            )
        expected = journal.get("outcomes_fingerprint")
        if isinstance(expected, str):
            actual = hashlib.sha256(
                _canonical_bytes({
                    "action_message_id": action_message_id,
                    "outcomes": raw,
                })
            ).hexdigest()
            if actual != expected:
                raise HostEvidenceValidationError(
                    ("OUTCOME_JOURNAL_OUTCOMES_FINGERPRINT_MISMATCH",)
                )
        return [dict(item) for item in raw]

    @staticmethod
    def read_json(path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise HostEvidenceValidationError(("HOST_EVIDENCE_FILE_CORRUPT",)) from exc
        if not isinstance(raw, dict):
            raise HostEvidenceValidationError(("HOST_EVIDENCE_FILE_INVALID",))
        return raw


__all__ = ["OutcomeRecoveryService"]
