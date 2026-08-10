"""按任务类型解释 Core Gate 证据，拒绝 Agent 自报替代验证。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class TaskEvidencePolicy:
    """把 Gate 事实归类为可信通过、环境故障或验证失败。"""

    _SMOKE_KINDS = frozenset({"project_setup", "configuration", "documentation"})
    _ENVIRONMENT_MARKERS = (
        "命令未找到",
        "command not found",
        "no importer manifest",
        "manifest not found",
        "未找到 package.json",
        "toolchain",
    )

    def evaluate(
        self,
        *,
        tasks: Sequence[Mapping[str, Any]],
        gate_results: Mapping[str, Any],
        test_results_claim: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """只使用 Core Gate；`test_results_claim` 仅保留接口兼容，不参与通过判定。"""
        del test_results_claim
        environment_gate = self._environment_failure(gate_results)
        if environment_gate is not None:
            return {
                "status": "environment_failure",
                "passed": False,
                "reason_code": "missing_toolchain_or_manifest",
                "gate": environment_gate,
            }

        kinds = {str(task.get("kind") or task.get("type") or "implementation") for task in tasks}
        test_gate = gate_results.get("test")
        if self._authoritative_pass(test_gate):
            return {
                "status": "pass",
                "passed": True,
                "reason_code": "core_test_passed",
                "evidence_kind": "core_test",
            }

        if kinds and kinds <= self._SMOKE_KINDS:
            passed_gates = [
                str(name)
                for name, result in gate_results.items()
                if self._authoritative_pass(result)
            ]
            if passed_gates:
                return {
                    "status": "pass",
                    "passed": True,
                    "reason_code": "core_smoke_passed",
                    "evidence_kind": "core_smoke",
                    "gates": passed_gates,
                }

        return {
            "status": "fail",
            "passed": False,
            "reason_code": "authoritative_test_required",
            "evidence_kind": "none",
        }

    @staticmethod
    def _authoritative_pass(raw: Any) -> bool:
        if not isinstance(raw, Mapping) or raw.get("passed") is not True:
            return False
        status = raw.get("status", "pass")
        if status == "":
            # 兼容旧注入 GateRunner：空 status 但 passed=true 是 Core 返回事实。
            return True
        return (
            status == "pass"
            and raw.get("skipped") is not True
            and raw.get("not_applicable") is not True
        )

    def _environment_failure(self, gate_results: Mapping[str, Any]) -> str | None:
        for name, raw in gate_results.items():
            if not isinstance(raw, Mapping) or raw.get("passed") is not False:
                continue
            message = str(raw.get("message", "")).lower()
            if any(marker in message for marker in self._ENVIRONMENT_MARKERS):
                return str(name)
        return None


__all__ = ["TaskEvidencePolicy"]
