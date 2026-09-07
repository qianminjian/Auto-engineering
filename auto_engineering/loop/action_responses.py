"""终态与错误 Action 的响应模型。

这些模型只负责把 Core 的终态或校验失败编码为宿主可消费的 Action；
Stage Result 的 schema 与校验仍归属于 ``actions`` 模块。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass
class ActionDone:
    """循环终止 action (§C.3.1 done)."""

    verdict: str
    reason: str | None = None
    verdict_level: int | None = None
    tick: int | None = None
    thread_id: str | None = None
    rounds: int | None = None
    gate_summary: dict | None = None
    checkpoint_id: str | None = None
    acceptance_summary: dict | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": "done",
            "tick": self.tick,
            "verdict": self.verdict,
            "verdict_level": self.verdict_level,
            "verdict_reason": self.reason,
        }
        if self.acceptance_summary is not None:
            d["acceptance_summary"] = self.acceptance_summary
        else:
            d["acceptance_summary"] = build_terminal_acceptance_summary(
                None, verdict=self.verdict,
            )
        for key in ("thread_id", "rounds", "gate_summary", "checkpoint_id"):
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        if self.tick is None:
            del d["tick"]
        return d


def build_terminal_acceptance_summary(
    state: object | Mapping[str, object] | None,
    *,
    verdict: str,
    design_coverage_ok: bool = False,
    system_deep_audit_ok: bool = False,
) -> dict[str, object]:
    """区分 Core 收敛与真实产品验收，避免 done 被误读为发布完成。"""

    def value(name: str, default: object = None) -> object:
        if isinstance(state, Mapping):
            return state.get(name, default)
        return getattr(state, name, default) if state is not None else default

    verified: list[str] = []
    if design_coverage_ok:
        verified.append("design_coverage")
    if system_deep_audit_ok:
        verified.append("system_deep_audit")
    gate_results = value("gate_results", {})
    if isinstance(gate_results, Mapping) and gate_results and all(
        isinstance(item, Mapping)
        and (item.get("not_applicable") is True or item.get("passed") is True)
        for item in gate_results.values()
    ):
        verified.append("project_gates")
    task_evidence = value("task_verification_evidence", {})
    if isinstance(task_evidence, Mapping) and task_evidence:
        verified.append("task_verification")

    unverified = ["product_business_acceptance"]
    if verdict != "GOAL_ACHIEVED":
        unverified.insert(0, "core_completion")
    total = len(verified) + len(unverified)
    return {
        "scope": "core",
        "status": (
            "core_verified_product_unverified"
            if verdict == "GOAL_ACHIEVED"
            else "core_incomplete"
        ),
        "verified_checks": verified,
        "unverified_items": unverified,
        "coverage": {"verified": len(verified), "total": total},
        "release_eligible": False,
    }


@dataclass
class ActionError:
    """路由/内部错误 action (§C.3.3, 无 current_state)."""

    error_code: str
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": "error",
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


@dataclass
class ErrorResponse:
    """Result 校验失败响应 (§C.3.3, 带 current_state)."""

    error_code: str
    message: str
    current_state: dict | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": "error",
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.current_state is not None:
            d["current_state"] = self.current_state
        if self.suggestion is not None:
            d["suggestion"] = self.suggestion
        return d


__all__ = [
    "ActionDone",
    "ActionError",
    "ErrorResponse",
    "build_terminal_acceptance_summary",
]
