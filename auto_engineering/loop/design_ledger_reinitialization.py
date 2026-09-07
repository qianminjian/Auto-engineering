"""显式 reinitialize 的设计账本来源轮换。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from auto_engineering.loop.design_decision_ledger import (
    DesignDecisionError,
    DesignDecisionLedger,
)


def reinitialize_design_intake(
    project_root: Path,
    design_doc_path: Path,
) -> DesignDecisionLedger:
    """轮换当前设计来源，并把旧账本保留为历史审计文件。"""

    root = project_root.resolve()
    source = design_doc_path.resolve()
    try:
        source_ref = source.relative_to(root).as_posix()
    except ValueError as exc:
        raise DesignDecisionError("DESIGN_LEDGER_SOURCE_OUTSIDE_PROJECT") from exc
    if not source.is_file():
        raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISSING")

    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    path = root / ".ae-state" / "design-decision-ledger.json"
    if path.is_file():
        previous = DesignDecisionLedger.from_project(root)
        if (
            previous.source_sha256 == source_sha256
            and previous.source_ref == source_ref
        ):
            return previous
        archive_dir = root / ".ae-state" / "design-ledger-history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / (
            f"{previous.source_sha256 or 'unknown'}-{source_sha256[:12]}.json"
        )
        if not archive_path.exists():
            archive_path.write_text(
                json.dumps(previous.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    ledger = DesignDecisionLedger((), source_sha256=source_sha256, source_ref=source_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".ledger-reinitialize-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return ledger


__all__ = ["reinitialize_design_intake"]
