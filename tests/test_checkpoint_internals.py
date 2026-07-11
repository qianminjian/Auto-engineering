"""Unit tests for checkpoint internals (serialization + store edge paths).

Covers:
- _serialization.py: Pydantic v1 path (line 51), fallback (line 55),
  JSON decode error (lines 70-71), non-dict deserialize (line 74)
- store.py: non-dict/non-object history item (lines 173-176)
"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.loop.checkpoint._serialization import (
    deserialize_state,
    normalize_value,
    serialize_state,
)

# ============================================================
# serialize_state
# ============================================================


def testserialize_state_pydantic_v1_path() -> None:
    """serialize_state with Pydantic v1-style object (has dict() method)."""

    class PydanticV1Style:
        def dict(self):
            return {"key": "value"}

    result = serialize_state(PydanticV1Style())
    data = json.loads(result)
    assert data == {"key": "value"}


def testserialize_state_fallback_path() -> None:
    """serialize_state with non-Pydantic, non-dict object (fallback to default=str)."""

    class PlainObject:
        def __repr__(self):
            return "PlainObject()"

    result = serialize_state(PlainObject())
    # Falls through to json.dumps(obj, default=str) — produces a JSON string
    assert isinstance(result, str)


def testserialize_state_with_basic_dict() -> None:
    """serialize_state with a plain dict."""
    result = serialize_state({"a": 1, "b": 2})
    data = json.loads(result)
    assert data == {"a": 1, "b": 2}


# ============================================================
# deserialize_state
# ============================================================


def testdeserialize_state_invalid_json() -> None:
    """deserialize_state with invalid JSON → returns raw string."""
    result = deserialize_state("not valid json {{{")
    # Falls into except (json.JSONDecodeError, TypeError) → returns state_json
    assert result == "not valid json {{{"


def testdeserialize_state_non_dict_json() -> None:
    """deserialize_state with valid JSON that is not a dict → returns non-dict value."""
    result = deserialize_state("[1, 2, 3]")
    # data is a list, not a dict → returns data directly
    assert result == [1, 2, 3]


def testdeserialize_state_json_typeerror() -> None:
    """deserialize_state with non-string input → TypeError → returns raw input."""
    result = deserialize_state(12345)  # type: ignore
    # json.loads fails on int → returns raw input
    assert result == 12345  # type: ignore


# ============================================================
# normalize_value
# ============================================================


def testnormalize_value_with_list() -> None:
    """normalize_value recursively normalizes list items."""
    from dataclasses import dataclass

    @dataclass
    class Inner:
        x: int = 1

    result = normalize_value([Inner(x=42), {"key": "val"}])
    assert result == [{"x": 42}, {"key": "val"}]


def testnormalize_value_with_tuple() -> None:
    """normalize_value handles tuples like lists."""
    result = normalize_value((1, 2))
    assert result == [1, 2]


def testnormalize_value_primitive() -> None:
    """normalize_value passes through primitives."""
    assert normalize_value(42) == 42
    assert normalize_value("hello") == "hello"
    assert normalize_value(None) is None
    assert normalize_value(True) is True


# ============================================================
# store.py: history items that are neither dict nor have __dict__
# ============================================================


def test_store_save_history_non_dict_non_object(tmp_path: Path) -> None:
    """store.save() with history item that is neither dict nor has __dict__.

    This exercises the else branch (lines 173-176 in store.py) where
    the item is stored as {"value": str(h)}.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    db_path = tmp_path / "test.db"
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(db_path))
    env = CheckpointEnvelope(round=1, step=1, status="running")

    # History item that is a plain string (neither dict nor has __dict__)
    cp_id = store.save(env, round=1, history=["plain_string_item"])
    assert cp_id is not None

    ckpt = store.load_latest()
    assert ckpt is not None
    # The item should be stored as {"value": "plain_string_item"}
    assert len(ckpt.history) == 1
    assert isinstance(ckpt.history[0], dict)
    assert ckpt.history[0].get("value") == "plain_string_item"
