"""共享 Worker outcomes 文件的唯一当前协议。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class OutcomeFileError(ValueError):
    """共享 outcomes 文件不符合当前 object envelope。"""


def parse_outcomes_document(value: object) -> list[dict[str, Any]]:
    """只解析当前 ``{"outcomes": [...]}`` 共享文件，不接受旧数组旁路。"""

    if not isinstance(value, Mapping):
        raise OutcomeFileError("OUTCOMES_DOCUMENT_OBJECT_REQUIRED")
    if set(value) != {"outcomes"}:
        raise OutcomeFileError("OUTCOMES_DOCUMENT_FIELDS_INVALID")
    raw = value.get("outcomes")
    if not isinstance(raw, list):
        raise OutcomeFileError("OUTCOMES_DOCUMENT_OUTCOMES_REQUIRED")
    if any(not isinstance(item, Mapping) for item in raw):
        raise OutcomeFileError("OUTCOMES_DOCUMENT_ITEM_INVALID")
    return [dict(item) for item in raw]


__all__ = ["OutcomeFileError", "parse_outcomes_document"]
