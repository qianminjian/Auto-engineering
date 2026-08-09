"""领域转换事实到进程内生命周期对象的显式 Effect 边界。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.stages.base import LifecycleEffects


class TransitionEffectExecutor:
    """按固定生命周期阶段执行非 Projection 领域事实。"""

    def __init__(
        self,
        batch_state: BatchState | None,
        activate_architecture: Callable[[], None],
        record_critic_progress: Callable[[str], None],
        progress_tree: ProgressTree | None = None,
        collect_token_usage: Callable[[], None] | None = None,
        record_completed_batch: Callable[[str], None] | None = None,
        snapshot_developer_output: Callable[[], None] | None = None,
        save_checkpoint: Callable[[], None] | None = None,
        offload_stage: Callable[[str], None] | None = None,
    ) -> None:
        self._batch_state = batch_state
        self._activate_architecture = activate_architecture
        self._record_critic_progress = record_critic_progress
        self._progress_tree = progress_tree
        self._collect_token_usage = collect_token_usage
        self._record_completed_batch = record_completed_batch
        self._snapshot_developer_output = snapshot_developer_output
        self._save_checkpoint = save_checkpoint
        self._offload_stage = offload_stage

    def apply_before_transition(self, effects: LifecycleEffects) -> None:
        if effects.collect_token_usage and self._collect_token_usage is not None:
            self._collect_token_usage()

    def apply_after_progress(self, effects: LifecycleEffects) -> None:
        if (
            effects.completed_batch_id is not None
            and self._record_completed_batch is not None
        ):
            self._record_completed_batch(effects.completed_batch_id)
        if (
            effects.snapshot_developer_output
            and self._snapshot_developer_output is not None
        ):
            self._snapshot_developer_output()
        if effects.save_checkpoint and self._save_checkpoint is not None:
            self._save_checkpoint()
        if effects.offload_stage is not None and self._offload_stage is not None:
            self._offload_stage(effects.offload_stage)

    def apply_pre_progress(self, events: Sequence[LoopEvent]) -> None:
        for event in events:
            if event.event_type is LoopEventType.ARCHITECTURE_PLAN_ACTIVATED:
                self._activate_architecture()
            elif event.event_type is LoopEventType.CRITIC_PROGRESS_RECORDED:
                verdict = event.to_dict()["payload"].get("verdict")
                if isinstance(verdict, str):
                    self._record_critic_progress(verdict)

    def apply_post_progress(self, events: Sequence[LoopEvent]) -> None:
        if self._batch_state is None:
            return
        for event in events:
            if event.event_type is LoopEventType.BATCH_COMPLETED:
                self._batch_state.advance_batch()
            elif event.event_type is LoopEventType.WORK_REOPENED:
                self._batch_state.reopen_previous_batch()
            elif event.event_type is LoopEventType.COMPONENT_COMPLETED:
                self._batch_state.advance_component()
            elif event.event_type is LoopEventType.PLATE_COMPLETED:
                self._batch_state.advance_plate()

    def apply_verification_progress(self, update: object) -> None:
        if self._progress_tree is None or self._batch_state is None:
            return
        if not isinstance(update, dict):
            return
        kind = update.get("kind")
        if kind == "component_verifier":
            component = self._batch_state.current_component()
            node = self._progress_tree.find_by_design_section(
                component.design_section
            )
            if node is not None:
                missing = int(update.get("missing", 0))
                diverged = int(update.get("diverged", 0))
                node.verifier_status = "failed" if missing or diverged else "pass"
                node.verifier_missing = missing
                node.verifier_diverged = diverged
                self._progress_tree.recalculate_parents(node.id)
        elif kind == "plate_deep_audit":
            p0, p1, p2 = update.get("counts", (0, 0, 0))
            threshold = int(update.get("threshold", 10))
            plate = self._batch_state.current_plate()
            for component in plate.components:
                node = self._progress_tree.find_by_design_section(
                    component.design_section
                )
                if node is not None:
                    node.deep_audit_status = (
                        "failed" if p0 or p1 > threshold else "pass"
                    )
                    node.deep_audit_p0 = p0
                    node.deep_audit_p1 = p1
                    node.deep_audit_p2 = p2
            self._progress_tree.recalculate_parents(
                f"sys/{self._batch_state.current_plate_idx}"
            )

    def apply_developer_progress(self, update: object) -> None:
        if self._progress_tree is None or not isinstance(update, dict):
            return
        section = update.get("design_section")
        if not isinstance(section, str):
            return
        node = self._progress_tree.find_by_design_section(section)
        if node is None:
            return
        node.done_tasks += int(update.get("completed_task_count", 0))
        next_task = update.get("next_task")
        node.current_task = next_task if isinstance(next_task, str) else None
        self._progress_tree.recalculate_parents(node.id)


__all__ = ["TransitionEffectExecutor"]
