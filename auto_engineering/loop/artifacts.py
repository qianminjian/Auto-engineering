"""v5.8 内容寻址 Artifact Store 与精简 Worker Receipt。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ArtifactError(ValueError):
    """Artifact 契约、完整性或尺寸校验失败。"""


def _canonical_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"artifact payload 不可序列化: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    sha256: str
    size_bytes: int
    media_type: str = "application/json"
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, *, kind: str, payload: object) -> ArtifactRef:
        if not kind or not kind.replace("_", "").replace("-", "").isalnum():
            raise ArtifactError("artifact kind 无效")
        encoded = _canonical_bytes(payload)
        digest = hashlib.sha256(encoded).hexdigest()
        ref = ArtifactRef(
            artifact_id=digest,
            kind=kind,
            sha256=digest,
            size_bytes=len(encoded),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{digest}.json"
        if path.exists():
            if path.read_bytes() != encoded:
                raise ArtifactError("artifact content-address 冲突")
        else:
            path.write_bytes(encoded)
        return ref

    def read(self, ref: ArtifactRef) -> Any:
        path = self.root / f"{ref.artifact_id}.json"
        try:
            encoded = path.read_bytes()
        except OSError as exc:
            raise ArtifactError(f"artifact 不可读: {ref.artifact_id}") from exc
        digest = hashlib.sha256(encoded).hexdigest()
        if digest != ref.sha256 or len(encoded) != ref.size_bytes:
            raise ArtifactError("artifact hash 或 size 校验失败")
        return json.loads(encoded)

    def verify(self, ref: ArtifactRef) -> bool:
        self.read(ref)
        return True

    def verify_dict(self, value: dict[str, Any]) -> bool:
        try:
            return self.verify(ArtifactRef(**value))
        except (ArtifactError, TypeError):
            return False


def compact_worker_receipt(
    *,
    store: ArtifactStore,
    stage: str,
    worker: str,
    payload: object,
    summary: str,
    inline_limit: int,
    summary_limit: int = 2048,
) -> dict[str, Any]:
    """小结果 inline；大结果只返回有界摘要与可校验引用。"""
    encoded = _canonical_bytes(payload)
    if len(encoded) <= inline_limit:
        return {
            "status": "completed",
            "stage": stage,
            "worker": worker,
            "payload": payload,
        }
    if len(summary.encode("utf-8")) > summary_limit:
        raise ArtifactError("worker receipt summary 超过字节上限")
    ref = store.put(kind="worker_report", payload=payload)
    return {
        "status": "completed",
        "stage": stage,
        "worker": worker,
        "summary": summary,
        "artifact_ref": ref.to_dict(),
    }


def validate_worker_receipt(
    receipt: dict[str, Any],
    *,
    expected_stage: str,
    store: ArtifactStore,
    receipt_limit: int = 4096,
    summary_limit: int = 2048,
) -> bool:
    if receipt.get("status") != "completed" or receipt.get("stage") != expected_stage:
        raise ArtifactError("worker receipt 状态或 stage 无效")
    encoded = _canonical_bytes(receipt)
    artifact_ref = receipt.get("artifact_ref")
    if artifact_ref is None:
        if len(encoded) > receipt_limit:
            raise ArtifactError("worker receipt inline payload 超过字节上限")
        return True
    if not isinstance(artifact_ref, dict) or not store.verify_dict(artifact_ref):
        raise ArtifactError("worker receipt ArtifactRef 无效")
    summary = receipt.get("summary")
    if not isinstance(summary, str) or len(summary.encode("utf-8")) > summary_limit:
        raise ArtifactError("worker receipt summary 无效或超过字节上限")
    if len(encoded) > receipt_limit:
        raise ArtifactError("worker receipt envelope 超过字节上限")
    return True


__all__ = [
    "ArtifactError",
    "ArtifactRef",
    "ArtifactStore",
    "compact_worker_receipt",
    "validate_worker_receipt",
]
