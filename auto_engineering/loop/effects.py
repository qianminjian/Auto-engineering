"""Action 编译后的显式文件副作用。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EffectExecutionError(ValueError):
    """EffectIntent 无效或执行结果不可信。"""


@dataclass(frozen=True, slots=True)
class WriteContentAddressedArtifact:
    kind: str
    content: str
    sha256: str


@dataclass(frozen=True, slots=True)
class WriteJsonArtifact:
    """在 `.ae-state/` 下写入一个名称稳定的规范 JSON Artifact。"""

    relative_path: str
    payload: Mapping[str, Any]


type EffectIntent = WriteContentAddressedArtifact | WriteJsonArtifact


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    kind: str
    relative_path: str
    sha256: str
    bytes: int


class EffectExecutor:
    """在项目专用根下执行内容寻址写入并返回可校验 receipt。"""

    _KIND = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def execute(self, intent: EffectIntent) -> EffectReceipt:
        if isinstance(intent, WriteJsonArtifact):
            return self._write_json(intent)
        if not self._KIND.fullmatch(intent.kind):
            raise EffectExecutionError("effect kind 无效")
        encoded = intent.content.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if digest != intent.sha256:
            raise EffectExecutionError("effect content hash 不匹配")
        relative = Path(".ae-state") / "effects" / intent.kind / f"{digest}.txt"
        path = (self.project_root / relative).resolve()
        effect_root = (self.project_root / ".ae-state" / "effects").resolve()
        if effect_root not in path.parents:
            raise EffectExecutionError("effect path 逃逸")
        if path.exists():
            if path.read_bytes() != encoded:
                raise EffectExecutionError("内容寻址 Artifact 冲突")
        else:
            self._atomic_write(path, encoded)
        return EffectReceipt(
            kind=intent.kind,
            relative_path=str(relative),
            sha256=digest,
            bytes=len(encoded),
        )

    def _write_json(self, intent: WriteJsonArtifact) -> EffectReceipt:
        relative_input = Path(intent.relative_path)
        if (
            relative_input.is_absolute()
            or ".." in relative_input.parts
            or relative_input.suffix != ".json"
        ):
            raise EffectExecutionError("effect path 无效")
        relative = Path(".ae-state") / relative_input
        path = (self.project_root / relative).resolve()
        state_root = (self.project_root / ".ae-state").resolve()
        if state_root not in path.parents:
            raise EffectExecutionError("effect path 逃逸")
        encoded = json.dumps(
            dict(intent.payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self._atomic_write(path, encoded)
        return EffectReceipt(
            kind="json",
            relative_path=str(relative),
            sha256=hashlib.sha256(encoded).hexdigest(),
            bytes=len(encoded),
        )

    def discard(self, receipts: Iterable[EffectReceipt]) -> None:
        """撤销尚未提交到 EventStore 的可变 JSON 产物。

        内容寻址 prompt 是跨 Action 可复用的不可变事实，不能因一次事务失败
        删除；命名 JSON（spawn proof 等）只在对应 Action 提交后才有意义，且
        仅在内容摘要仍匹配时删除，避免误伤后续已覆盖的文件。
        """

        root = self.project_root / ".ae-state"
        for receipt in receipts:
            if receipt.kind != "json":
                continue
            relative = Path(receipt.relative_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] != ".ae-state"
            ):
                continue
            path = (self.project_root / relative).resolve()
            if root.resolve() not in path.parents:
                continue
            try:
                if (
                    path.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest()
                    == receipt.sha256
                ):
                    path.unlink()
            except OSError:
                # 清理是 best effort；事务失败本身不能被二次清理异常覆盖。
                continue

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise


__all__ = [
    "EffectExecutionError",
    "EffectExecutor",
    "EffectIntent",
    "EffectReceipt",
    "WriteContentAddressedArtifact",
    "WriteJsonArtifact",
]
