"""v5.8 T315：ArtifactRef 与有界 Worker Receipt。"""

from __future__ import annotations

import json

import pytest

from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    compact_worker_receipt,
    validate_worker_receipt,
)


def test_artifact_store_is_content_addressed_and_verifiable(tmp_path) -> None:
    store = ArtifactStore(tmp_path / ".ae-state" / "artifacts")
    payload = {"findings": [{"severity": "P1", "issue": "状态竞态"}]}

    first = store.put(kind="audit_report", payload=payload)
    replay = store.put(kind="audit_report", payload=payload)

    assert replay == first
    assert first.sha256 == first.artifact_id
    assert store.read(first) == payload
    assert store.verify(first)


def test_artifact_store_detects_tampering(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put(kind="worker_report", payload={"result": "ok"})
    path = store.root / f"{ref.artifact_id}.json"
    path.write_text('{"result":"tampered"}', encoding="utf-8")

    with pytest.raises(ArtifactError, match="hash"):
        store.read(ref)


def test_large_worker_result_becomes_ref_and_bounded_summary(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    receipt = compact_worker_receipt(
        store=store,
        stage="system_deep_audit",
        worker="architecture",
        payload={"findings": ["x" * 1000 for _ in range(20)]},
        summary="发现 20 个问题，完整内容见 ArtifactRef。",
        inline_limit=512,
        summary_limit=128,
    )

    encoded = json.dumps(receipt, ensure_ascii=False).encode()
    assert len(encoded) < 512
    assert "payload" not in receipt
    assert receipt["artifact_ref"]["kind"] == "worker_report"
    assert store.verify_dict(receipt["artifact_ref"])


def test_small_worker_result_stays_inline(tmp_path) -> None:
    receipt = compact_worker_receipt(
        store=ArtifactStore(tmp_path / "artifacts"),
        stage="critic",
        worker="critic",
        payload={"verdict": "APPROVE"},
        summary="通过",
        inline_limit=512,
    )

    assert receipt["payload"] == {"verdict": "APPROVE"}
    assert "artifact_ref" not in receipt


def test_summary_over_limit_fails_instead_of_silent_truncation(tmp_path) -> None:
    with pytest.raises(ArtifactError, match="summary"):
        compact_worker_receipt(
            store=ArtifactStore(tmp_path / "artifacts"),
            stage="audit",
            worker="worker",
            payload={"large": "x" * 1000},
            summary="y" * 129,
            inline_limit=10,
            summary_limit=128,
        )


def test_receipt_validator_rejects_large_inline_payload(tmp_path) -> None:
    with pytest.raises(ArtifactError, match="inline"):
        validate_worker_receipt(
            {
                "status": "completed",
                "stage": "audit",
                "payload": {"report": "x" * 5000},
            },
            expected_stage="audit",
            store=ArtifactStore(tmp_path / "artifacts"),
            receipt_limit=4096,
        )


def test_receipt_validator_accepts_verified_artifact_ref(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    receipt = compact_worker_receipt(
        store=store,
        stage="audit",
        worker="worker",
        payload={"report": "x" * 5000},
        summary="完整报告见引用",
        inline_limit=128,
    )

    assert validate_worker_receipt(
        receipt,
        expected_stage="audit",
        store=store,
    )
