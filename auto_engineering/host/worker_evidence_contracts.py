"""Worker evidence 的公共异常类型。"""

from __future__ import annotations

from collections.abc import Sequence


class HostEvidenceValidationError(ValueError):
    """一次报告全部证据问题，避免宿主逐轮修补 JSON。"""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(dict.fromkeys(violations))
        super().__init__("HOST_EVIDENCE_INVALID: " + ",".join(self.violations))


class WorkerOutcomeCollectionError(ValueError):
    """Worker 私有产出无法汇总为 Action-scoped outcomes。"""

    def __init__(self, code: str, worker_id: str, detail: str = "") -> None:
        self.code = code
        self.worker_id = worker_id
        self.detail = detail
        suffix = f":{detail}" if detail else ""
        super().__init__(f"{code}:{worker_id}{suffix}")


__all__ = ["HostEvidenceValidationError", "WorkerOutcomeCollectionError"]
