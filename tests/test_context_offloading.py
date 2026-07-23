"""Tests for auto_engineering.context.offloading — StageContextOffload + ContextOffloader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from auto_engineering.context.offloading import ContextOffloader, StageContextOffload


class TestStageContextOffload:
    """StageContextOffload dataclass tests."""

    def test_default_construction_with_required_fields(self) -> None:
        """Minimal construction with only required fields."""
        offload = StageContextOffload(
            stage="architect",
            round_number=1,
            timestamp="2026-07-19T10:00:00",
            summary="Designed payment module architecture.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
            raw_context_path="/tmp/offload/architect-r1.json",
        )
        assert offload.stage == "architect"
        assert offload.round_number == 1
        assert offload.summary == "Designed payment module architecture."

    def test_full_construction_with_all_fields(self) -> None:
        """Full construction exercise all dataclass fields."""
        offload = StageContextOffload(
            stage="developer",
            round_number=2,
            timestamp="2026-07-19T10:05:00",
            summary="Implemented payment module with TDD.",
            key_decisions=["Used Decimal for amounts", "Added retry on gateway timeout"],
            files_changed=["src/payment.py", "tests/test_payment.py"],
            gate_results={"safety": "pass", "test": "pass"},
            raw_context_path="/tmp/offload/developer-r2.json",
        )
        assert len(offload.key_decisions) == 2
        assert len(offload.files_changed) == 2
        assert offload.gate_results["safety"] == "pass"

    def test_serialization_roundtrip(self) -> None:
        """StageContextOffload can be serialized to dict and reconstructed."""
        offload = StageContextOffload(
            stage="critic",
            round_number=3,
            timestamp="2026-07-19T10:10:00",
            summary="Code review passed.",
            key_decisions=[],
            files_changed=[],
            gate_results={"audit": "pass"},
            raw_context_path="/tmp/offload/critic-r3.json",
        )
        d = {
            "stage": offload.stage,
            "round_number": offload.round_number,
            "timestamp": offload.timestamp,
            "summary": offload.summary,
            "key_decisions": offload.key_decisions,
            "files_changed": offload.files_changed,
            "gate_results": offload.gate_results,
            "raw_context_path": offload.raw_context_path,
        }
        reconstructed = StageContextOffload(**d)
        assert reconstructed.stage == offload.stage
        assert reconstructed.round_number == offload.round_number
        assert reconstructed.summary == offload.summary


class TestContextOffloader:
    """ContextOffloader storage/retrieval tests."""

    @pytest.fixture
    def offload_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as td:
            yield Path(td)

    @pytest.fixture
    def offloader(self, offload_dir: Path) -> ContextOffloader:
        return ContextOffloader(offload_dir)

    def test_offload_writes_file(self, offloader: ContextOffloader, offload_dir: Path) -> None:
        """offload() writes the offload file to disk."""
        messages = [{"role": "user", "content": "Design a payment module."}]
        offload = offloader.offload(
            stage="architect",
            messages=messages,
            summary="Architecture designed.",
            key_decisions=["Use clean architecture"],
            files_changed=[],
            gate_results={},
        )
        assert offload.stage == "architect"
        assert offload.round_number == 1
        assert Path(offload.raw_context_path).exists()

    def test_offload_writes_valid_json(self, offloader: ContextOffloader, offload_dir: Path) -> None:
        """The written offload file contains valid JSON with messages and metadata."""
        messages = [
            {"role": "user", "content": "Implement login."},
            {"role": "assistant", "content": "OK, I'll implement login."},
        ]
        offload = offloader.offload(
            stage="developer",
            messages=messages,
            summary="Login implemented.",
            key_decisions=[],
            files_changed=["src/login.py"],
            gate_results={"test": "pass"},
        )
        with open(offload.raw_context_path) as f:
            data = json.load(f)
        assert data["stage"] == "developer"
        assert data["summary"] == "Login implemented."
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"

    def test_load_summary_returns_offload_without_full_messages(
        self, offloader: ContextOffloader
    ) -> None:
        """load_summary() returns metadata but no full messages in memory."""
        messages = [{"role": "user", "content": "Design something."}]
        offloader.offload(
            stage="architect",
            messages=messages,
            summary="Design done.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        loaded = offloader.load_summary("architect")
        assert loaded is not None
        assert loaded.stage == "architect"
        assert loaded.summary == "Design done."

    def test_load_summary_returns_none_when_no_offload(
        self, offloader: ContextOffloader
    ) -> None:
        """load_summary() returns None for stages that were never offloaded."""
        assert offloader.load_summary("developer") is None

    def test_multiple_stages_offloaded_independently(
        self, offloader: ContextOffloader, offload_dir: Path
    ) -> None:
        """Each stage gets its own offload file that can be loaded independently."""
        offloader.offload(
            stage="architect",
            messages=[{"role": "user", "content": "Design."}],
            summary="Architecture ready.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        offloader.offload(
            stage="developer",
            messages=[{"role": "user", "content": "Implement."}],
            summary="Implementation done.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        arch = offloader.load_summary("architect")
        dev = offloader.load_summary("developer")
        assert arch is not None
        assert dev is not None
        assert arch.stage == "architect"
        assert dev.stage == "developer"

    def test_round_number_increments_per_offload(
        self, offloader: ContextOffloader
    ) -> None:
        """Each offload call increments the round counter."""
        o1 = offloader.offload(
            stage="architect",
            messages=[],
            summary="Round 1.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        o2 = offloader.offload(
            stage="developer",
            messages=[],
            summary="Round 2.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        assert o1.round_number == 1
        assert o2.round_number == 2

    def test_offload_directory_does_not_exist_creates_it(self) -> None:
        """ContextOffloader creates the offload directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            offload_path = Path(td) / "nonexistent" / "offload"
            offloader = ContextOffloader(offload_path)
            offloader.offload(
                stage="architect",
                messages=[],
                summary="Test.",
                key_decisions=[],
                files_changed=[],
                gate_results={},
            )
            assert offload_path.exists()

    def test_messages_with_complex_content_blocks_preserved(
        self, offloader: ContextOffloader
    ) -> None:
        """Messages with list-based content blocks are round-tripped correctly."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Review this code."},
                    {"type": "text", "text": "Also check the tests."},
                ],
            },
        ]
        offload = offloader.offload(
            stage="critic",
            messages=messages,
            summary="Review done.",
            key_decisions=[],
            files_changed=[],
            gate_results={},
        )
        # Verify via raw file path (load_full_context has been removed)
        with open(offload.raw_context_path) as f:
            data = json.load(f)
        loaded_messages = data.get("messages", [])
        assert len(loaded_messages) == 1
        assert isinstance(loaded_messages[0]["content"], list)
        assert loaded_messages[0]["content"][0]["type"] == "text"
