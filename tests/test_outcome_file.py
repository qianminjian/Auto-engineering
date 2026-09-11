"""共享 Worker outcomes 文件的单一当前协议回归。"""

import pytest

from auto_engineering.host.outcome_file import (
    OutcomeFileError,
    parse_outcomes_document,
)


def test_outcomes_document_accepts_only_current_object_envelope() -> None:
    assert parse_outcomes_document({"outcomes": [{"worker_id": "w1"}]}) == [
        {"worker_id": "w1"}
    ]


@pytest.mark.parametrize(
    "document, error_code",
    [
        ([{"worker_id": "w1"}], "OUTCOMES_DOCUMENT_OBJECT_REQUIRED"),
        ({"outcomes": []}, None),
        ({"outcomes": "w1"}, "OUTCOMES_DOCUMENT_OUTCOMES_REQUIRED"),
        ({"outcomes": [{}], "source": "legacy"}, "OUTCOMES_DOCUMENT_FIELDS_INVALID"),
        ({"outcomes": ["w1"]}, "OUTCOMES_DOCUMENT_ITEM_INVALID"),
    ],
)
def test_outcomes_document_rejects_noncanonical_shapes(
    document: object,
    error_code: str | None,
) -> None:
    if error_code is None:
        assert parse_outcomes_document(document) == []
        return
    with pytest.raises(OutcomeFileError, match=error_code):
        parse_outcomes_document(document)
