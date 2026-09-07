"""宿主会话结束时的有限、可恢复 Stop Report。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

HOST_RUNTIME_PROTOCOL_ERROR = "HOST_RUNTIME_PROTOCOL_ERROR"
_MAX_REASON_LENGTH = 128


@dataclass(frozen=True, slots=True)
class HostStopReport:
    """描述宿主结束时尚未完成的唯一 Action，不携带 transcript 或业务正文。"""

    schema_version: str
    thread_id: str
    action_message_id: str
    platform: str
    host_session_id: str
    build_id: str
    disposition: str
    termination_category: str
    reason_code: str
    last_host_observation: dict[str, str]
    lease_cleared: bool
    next_operation: dict[str, object]

    @classmethod
    def from_lease(
        cls,
        lease: HostRunLease,
        *,
        event_name: str,
        termination_category: str,
        reason: str,
        lease_cleared: bool,
        reason_code: str = HOST_RUNTIME_PROTOCOL_ERROR,
    ) -> HostStopReport:
        return cls(
            schema_version="1.0",
            thread_id=lease.thread_id,
            action_message_id=lease.action_message_id,
            platform=lease.platform,
            host_session_id=lease.host_session_id,
            build_id=lease.build_id,
            disposition=lease.disposition,
            termination_category=termination_category,
            reason_code=reason_code,
            last_host_observation={
                "event": event_name,
                "reason": reason[:_MAX_REASON_LENGTH],
            },
            lease_cleared=lease_cleared,
            next_operation={
                "operation": "resume_active_action",
                "thread_id": lease.thread_id,
                "argv": ["dev-loop", "--resume", lease.thread_id],
            },
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class HostStopReportStore:
    """按 Action/宿主会话身份保存不可变 Stop Report。"""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve() / ".ae-state" / "host-runtime" / "stop-reports"

    @staticmethod
    def _report_name(report: HostStopReport) -> str:
        identity = (
            f"{report.thread_id}:{report.action_message_id}:"
            f"{report.host_session_id}:{report.build_id}"
        )
        return f"{hashlib.sha256(identity.encode('utf-8')).hexdigest()}.json"

    def path_for(self, report: HostStopReport) -> Path:
        return self.root / self._report_name(report)

    def save(self, report: HostStopReport) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(report)
        payload = json.dumps(
            report.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".stop-report-", suffix=".json", dir=self.root, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return path


def _bounded_reason(payload: Mapping[str, object]) -> str:
    value = payload.get("reason")
    if not isinstance(value, str) or not value:
        return "unknown"
    return value[:_MAX_REASON_LENGTH]


def handle_claude_session_end(
    project_root: Path,
    payload: Mapping[str, object],
    *,
    reason_code: str = HOST_RUNTIME_PROTOCOL_ERROR,
) -> dict[str, object]:
    event_name = payload.get("hook_event_name")
    if event_name not in {"SessionEnd", "StopFailure"}:
        return {"systemMessage": "Auto-Engineering Hook 已安全跳过"}
    termination_category = (
        "session_ended_with_continue"
        if event_name == "SessionEnd"
        else "host_action_failed_with_continue"
    )

    session_id = payload.get("session_id")
    normalized_session = session_id if isinstance(session_id, str) else None
    if not normalized_session:
        return {"systemMessage": "Auto-Engineering 宿主会话已结束"}

    lease_store = HostRunLeaseStore(project_root)
    lease = lease_store.load()
    if lease is None or lease.host_session_id != normalized_session:
        return {"systemMessage": "Auto-Engineering 宿主会话已结束"}

    if not (
        lease.disposition == "CONTINUE"
        and lease.continuation_required
        and not lease.yield_allowed
    ):
        lease_store.clear_if_matches(lease)
        return {"systemMessage": "Auto-Engineering 宿主会话已结束"}

    report = HostStopReport.from_lease(
        lease,
        event_name=event_name,
        termination_category=termination_category,
        reason=_bounded_reason(payload),
        lease_cleared=False,
        reason_code=reason_code,
    )
    report_store = HostStopReportStore(project_root)
    report_store.save(report)
    cleared = lease_store.clear_if_matches(lease)
    if cleared:
        report = HostStopReport.from_lease(
            lease,
            event_name=event_name,
            termination_category=termination_category,
            reason=_bounded_reason(payload),
            lease_cleared=True,
            reason_code=reason_code,
        )
        report_store.save(report)
    report_path = report_store.path_for(report)
    return {
        "reason_code": reason_code,
        "lease_cleared": cleared,
        "stop_report_path": str(report_path.relative_to(project_root.resolve())),
        "next_operation": report.next_operation,
        "systemMessage": (
            "Auto-Engineering 宿主已结束，但 Core 仍要求继续；"
            "已记录 Stop Report，请从 active Action 恢复"
        ),
    }


__all__ = [
    "HOST_RUNTIME_PROTOCOL_ERROR",
    "HostStopReport",
    "HostStopReportStore",
    "handle_claude_session_end",
]
