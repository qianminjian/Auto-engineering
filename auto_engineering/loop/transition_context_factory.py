"""StageHandler 的只读 TransitionContext 扩展工厂。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.verification_layers import VerificationLayers


class TransitionContextFactory:
    def build(
        self,
        stage: str,
        *,
        batch_state: BatchState | None,
        verification_layers: VerificationLayers | None,
        max_repair_cycles: int,
        p1_threshold: int,
        gate_results: object,
    ) -> dict[str, object]:
        extensions: dict[str, object] = {
            "verification_layers": (
                verification_layers.value
                if verification_layers is not None
                else VerificationLayers.LEAF.value
            )
        }
        if batch_state is not None and stage == "component_verifier":
            extensions["has_more_components"] = (
                batch_state.current_component_idx + 1
                < len(batch_state.current_plate().components)
            )
        if batch_state is not None and stage == "plate_deep_audit":
            extensions["has_more_plates"] = (
                batch_state.current_plate_idx + 1 < len(batch_state.plates)
            )
        if stage in {"plate_deep_audit", "system_deep_audit"}:
            extensions["p1_threshold"] = p1_threshold
        if stage == "critic":
            extensions["max_repair_cycles"] = max_repair_cycles
            extensions["max_stagnation_cycles"] = 3
            if batch_state is not None:
                component = batch_state.current_component()
                batches = batch_state.batches_for(component)
                index = batch_state.current_batch_idx
                extensions["allowed_file_targets"] = self._allowed_files(
                    batches,
                    index,
                )
                extensions["has_more_batches"] = (
                    batch_state.has_more_batches_for(component)
                )
        if stage == "developer" and batch_state is not None:
            extensions["blocking_gate_results"] = self.blocking_gate_results(
                gate_results
            )
            component = batch_state.current_component()
            batches = batch_state.batches_for(component)
            index = batch_state.current_batch_idx
            completed = batches[index]
            next_index = index + 1
            has_more = next_index < len(batches)
            extensions.update({
                "has_more_batches_after_advance": has_more,
                "completed_batch_id": completed.get("batch_id"),
                "completed_task_count": len(completed.get("tasks", [])),
                "design_section": component.design_section,
                "next_task": (
                    batches[next_index]["tasks"][0]["description"]
                    if has_more and batches[next_index].get("tasks")
                    else None
                ),
                "next_pre_gate": (
                    batches[next_index].get("gate") if has_more else None
                ),
            })
        return extensions

    @staticmethod
    def _allowed_files(batches: list[dict], index: int) -> list[str]:
        allowed: list[str] = []
        if index >= len(batches):
            return allowed
        for task in batches[index].get("tasks", []):
            if not isinstance(task, dict):
                continue
            for path in task.get("file_targets", []):
                if isinstance(path, str) and path not in allowed:
                    allowed.append(path)
        return allowed

    @staticmethod
    def blocking_gate_results(gate_results: object) -> list[dict[str, object]]:
        if not isinstance(gate_results, dict):
            return []
        blocking: list[dict[str, object]] = []
        for gate_name, raw in gate_results.items():
            if not isinstance(raw, dict):
                continue
            status = str(raw.get("status", "")).lower()
            not_applicable = bool(raw.get("not_applicable")) or status in {
                "not_applicable",
                "n/a",
                "skip",
                "skipped",
            }
            if not not_applicable and (
                status == "hard_fail" or raw.get("passed") is False
            ):
                blocking.append({"gate_name": str(gate_name), **raw})
        return blocking


__all__ = ["TransitionContextFactory"]
