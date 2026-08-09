"""用户本次启动意图；历史状态不得覆盖显式输入。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InvocationIntent:
    mode: str
    design_doc_path: str
    design_doc_digest: str
    scope: str | None = None

    @classmethod
    def from_design_doc(
        cls,
        project_root: Path,
        design_doc_path: str,
        *,
        scope: str | None = None,
    ) -> InvocationIntent:
        relative = Path(design_doc_path)
        if relative.is_absolute():
            path = relative.resolve()
            try:
                normalized = path.relative_to(project_root.resolve()).as_posix()
            except ValueError as exc:
                raise ValueError("设计文档必须位于项目目录内") from exc
        else:
            path = (project_root / relative).resolve()
            normalized = relative.as_posix()
        if not path.is_file():
            raise ValueError(f"设计文档不存在: {design_doc_path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(
            mode="design_doc",
            design_doc_path=normalized,
            design_doc_digest=f"sha256:{digest}",
            scope=scope,
        )


__all__ = ["InvocationIntent"]
