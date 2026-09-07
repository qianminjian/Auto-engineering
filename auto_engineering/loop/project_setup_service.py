"""Project Setup Action 的确定性事务服务。

Project Setup 是宿主可执行的 capability-only 边界，但不是另一套 Loop。此
服务只编排现有 TickOrchestrator 的状态、事件和 Action 委托；文件分类与
范围判断位于 ``project_setup_scope``，从而保持主状态机只保留一次推进语义。
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING

from auto_engineering.config.constants import (
    PROJECT_SETUP_FAILURE_SUMMARY_MAX_LENGTH,
    PROJECT_SETUP_MAX_FAILURE_STREAK,
)
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.project_setup_scope import (
    project_setup_scope_violations,
    project_setup_snapshot_files,
)
from auto_engineering.project_profile.resolver import ResolutionStatus

if TYPE_CHECKING:
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator


class ProjectSetupService:
    """拥有 Project Setup 策略、但不拥有第二张 Loop 状态机。"""

    def __init__(self, owner: TickOrchestrator) -> None:
        self.owner = owner

    def complete(self) -> dict:
        """重新探测并执行工程门禁；未满足能力时保持原 active Action。"""
        owner = self.owner
        state = owner._state
        if state is None:
            raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
        resolution = owner._project_profile_resolver.resolve(
            owner.project_root,
            design_doc_path=state.design_doc_path,
            require_test_command=False,
        )
        owner._project_profile_resolution = resolution
        if resolution.status is not ResolutionStatus.RESOLVED:
            return self.retry(
                "PROJECT_SETUP_UNVERIFIED: 项目搭建结果未通过本地证据验证",
                list(resolution.missing_capabilities),
                allow_recovery=True,
            )
        scope_violations = project_setup_scope_violations(owner, resolution.profile)
        if scope_violations:
            return self.reject_scope(scope_violations)
        owner._apply_project_profile_resolution(resolution)
        profile = resolution.profile
        if profile is None:
            raise RuntimeError("RESOLVED ProjectProfile 缺少 profile")
        snapshot_files = project_setup_snapshot_files(owner, profile)
        try:
            gate_results, duration_ms = owner._tick_gate_runner.run(
                snapshot_files,
                stage="project_setup",
                tick=state.tick,
            )
            owner._t_gate_ms += duration_ms
        except ValueError as exc:
            return self.retry(
                f"PROJECT_SETUP_GATE_FAILED: 项目搭建工程门禁无法执行: {exc}",
                ["setup_gate:snapshot"],
                allow_recovery=True,
            )
        state.gate_results = gate_results
        failed_gates = sorted(
            name for name, result in gate_results.items()
            if not result.get("not_applicable") and result.get("passed") is not True
        )
        if failed_gates:
            return self.retry(
                "PROJECT_SETUP_GATE_FAILED: 项目搭建工程门禁失败: "
                + ", ".join(failed_gates),
                [f"setup_gate:{name}" for name in failed_gates],
                allow_recovery=True,
            )
        if state.project_setup_failure_streak:
            state.project_setup_failure_streak = 0
            owner._queue_domain_event(
                LoopEventType.PROJECT_STATE_UPDATED,
                {"changes": {"project_setup_failure_streak": 0}},
            )
        owner._queue_domain_event(
            LoopEventType.PROJECT_SETUP_COMPLETED,
            {"profile_id": state.project_profile_id},
        )
        previous_stage = state.current_stage
        state.current_stage = "gap_scan" if owner._design_doc else "architect"
        state.expected_stage = state.current_stage
        owner._queue_domain_event(
            LoopEventType.STAGE_ADVANCED,
            {"from": previous_stage, "to": state.current_stage},
        )
        state.tick += 1
        owner._save_checkpoint()
        return owner.build_action()

    def record_failure(self, result: dict) -> dict:
        """接收宿主显式失败，确保失败发生在 Tick 边界而非宿主内循环。"""
        owner = self.owner
        state = owner._state
        if state is None:
            raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
        failure_code = str(result["failure_code"])
        failure_summary = str(result["failure_summary"]).strip()
        owner._queue_domain_event(
            LoopEventType.PROJECT_SETUP_FAILED,
            {
                "failure_code": failure_code,
                "failure_summary": failure_summary,
                "attempts_in_action": result["attempts_in_action"],
            },
        )
        return self.retry(
            "PROJECT_SETUP_REPORTED_FAILURE: "
            f"{failure_code}: {failure_summary}",
            list(state.missing_project_capabilities),
        )

    def retry(
        self,
        feedback: str,
        missing: list[str],
        *,
        allow_recovery: bool = False,
    ) -> dict:
        """把可修复 setup 失败转换为下一 Action，而不是终止 Product Driver。"""
        owner = self.owner
        state = owner._state
        if state is None:
            raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
        if (
            state.project_setup_failure_streak >= PROJECT_SETUP_MAX_FAILURE_STREAK
            and isinstance(owner._active_action, Mapping)
            and owner._active_action.get("action") == "resource_wait"
        ):
            if allow_recovery:
                state.missing_project_capabilities = missing
                owner._queue_domain_event(
                    LoopEventType.PROJECT_STATE_UPDATED,
                    {"changes": {"missing_project_capabilities": missing}},
                )
                state.tick += 1
                owner._save_checkpoint()
                return owner.build_action(
                    feedback=feedback,
                    project_setup_recovery=True,
                )
            return deepcopy(dict(owner._active_action))
        failure_streak = state.project_setup_failure_streak + 1
        state.project_setup_failure_streak = failure_streak
        state.missing_project_capabilities = missing
        owner._queue_domain_event(
            LoopEventType.PROJECT_STATE_UPDATED,
            {"changes": {
                "missing_project_capabilities": missing,
                "project_setup_failure_streak": failure_streak,
            }},
        )
        state.tick += 1
        owner._save_checkpoint()
        return owner.build_action(feedback=feedback)

    def reject_scope(self, violations: dict[str, list[str]]) -> dict:
        """拒绝 setup 阶段越过 capability-only 边界的文件写入。"""
        rendered = "; ".join(
            f"{kind}={', '.join(paths)}"
            for kind, paths in violations.items()
            if paths
        )
        summary = (
            "Setup 阶段只能建立工程能力；检测到新增业务文件: "
            f"{rendered}"
        )[:PROJECT_SETUP_FAILURE_SUMMARY_MAX_LENGTH]
        owner = self.owner
        state = owner._state
        if state is None:
            raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
        owner._queue_domain_event(
            LoopEventType.PROJECT_SETUP_FAILED,
            {
                "failure_code": "PROJECT_SETUP_SCOPE_VIOLATION",
                "failure_summary": summary,
                "source": "core_validation",
                "violations": violations,
            },
        )
        remediation = (
            "；不得通过实现业务代码来满足该列表。只撤销本次 Setup 尝试新增的越界文件，"
            "不得删除基线中的用户文件；完成后重新提交 setup 结果。"
        )
        waiting_for_recovery = (
            isinstance(owner._active_action, Mapping)
            and owner._active_action.get("action") == "resource_wait"
        )
        return self.retry(
            "PROJECT_SETUP_SCOPE_VIOLATION: " + summary + remediation,
            [] if waiting_for_recovery else list(state.missing_project_capabilities),
            allow_recovery=waiting_for_recovery,
        )


__all__ = ["ProjectSetupService"]
