"""Claude 原生 stream-json usage 事实回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.host.usage_attestation import (
    HostUsageAttestationError,
    read_claude_stream_usage,
)


def test_reads_last_complete_claude_result_usage(tmp_path: Path) -> None:
    stream = tmp_path / "claude.stream.jsonl"
    stream.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "usage": {"input_tokens": 1}}),
                json.dumps({
                    "type": "result",
                    "total_cost_usd": 0.25,
                    "usage": {
                        "input_tokens": 12,
                        "cache_read_input_tokens": 30,
                        "cache_creation_input_tokens": 4,
                        "output_tokens": 5,
                    },
                }),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    usage = read_claude_stream_usage(stream)

    assert usage.cost_usd == 0.25
    assert usage.input_tokens == 12
    assert usage.cache_read_tokens == 30
    assert usage.cache_write_tokens == 4
    assert usage.output_tokens == 5


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "result", "total_cost_usd": 0.25},
        {
            "type": "result",
            "total_cost_usd": 0.25,
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    ],
)
def test_rejects_missing_or_incomplete_cost_usage(
    tmp_path: Path, payload: dict,
) -> None:
    stream = tmp_path / "claude.stream.jsonl"
    stream.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(HostUsageAttestationError, match="CLAUDE_COST_EVIDENCE_MISSING"):
        read_claude_stream_usage(stream)


def test_skips_malformed_intermediate_lines_but_requires_final_fact(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "claude.stream.jsonl"
    stream.write_text(
        "not-json\n" + json.dumps({"type": "assistant"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(HostUsageAttestationError, match="CLAUDE_COST_EVIDENCE_MISSING"):
        read_claude_stream_usage(stream)
