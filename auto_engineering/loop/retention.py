"""v5.8 永久事实、可重建副本与临时产物的 dry-run 保留策略。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    keep_checkpoint_copies: int
    keep_prompt_logs: int

    def __post_init__(self) -> None:
        if self.keep_checkpoint_copies < 1 or self.keep_prompt_logs < 1:
            raise ValueError("保留数量必须至少为 1")


@dataclass(frozen=True, slots=True)
class RetentionCandidate:
    path: Path
    kind: str
    reason: str
    reconstructible: bool


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    candidates: tuple[RetentionCandidate, ...]
    dry_run: bool = True


class RetentionPlanner:
    """只生成计划，不执行删除；事件事实永远不进入候选集。"""

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root

    @staticmethod
    def _older_files(root: Path, keep: int) -> list[Path]:
        if not root.is_dir():
            return []
        files = sorted(
            (path for path in root.iterdir() if path.is_file()),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        return files[keep:]

    def plan(
        self,
        policy: RetentionPolicy,
        *,
        referenced_artifact_ids: set[str] | None = None,
    ) -> RetentionPlan:
        candidates: list[RetentionCandidate] = []
        for path in self._older_files(
            self.state_root / "checkpoints", policy.keep_checkpoint_copies
        ):
            candidates.append(RetentionCandidate(
                path, "checkpoint_copy", "超过 checkpoint 副本保留数", True
            ))
        for path in self._older_files(
            self.state_root / "prompt-log", policy.keep_prompt_logs
        ):
            candidates.append(RetentionCandidate(
                path, "prompt_log", "超过 Prompt 日志保留数", True
            ))
        referenced = referenced_artifact_ids or set()
        artifact_root = self.state_root / "artifacts"
        if artifact_root.is_dir():
            for path in sorted(artifact_root.glob("*.json")):
                if path.stem not in referenced:
                    candidates.append(RetentionCandidate(
                        path, "unreferenced_artifact", "无事件或 Capsule 引用", False
                    ))
        return RetentionPlan(tuple(candidates))

    def verify_artifact_references(self, artifact_ids: set[str]) -> list[str]:
        root = self.state_root / "artifacts"
        return sorted(
            artifact_id for artifact_id in artifact_ids
            if not (root / f"{artifact_id}.json").is_file()
        )


__all__ = [
    "RetentionCandidate",
    "RetentionPlan",
    "RetentionPlanner",
    "RetentionPolicy",
]
