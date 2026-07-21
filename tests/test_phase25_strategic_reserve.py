"""Phase 25 Integration tests — Strategic reserve activation (T91-T97).

T91: PII Guardrail G10 — post-agent file PII scan
T92: Large file offloading — intermediate artifact offloading
T93: LangSmith exporter — OTLP bridge
T94: Pre-planned Gate — DecisionGate form 1
T95: Escalation Gate — DecisionGate form 2
T96: Task DAG dependencies — topological batch scheduling
T97: Message type semantics — action/result schema extension

RED phase: Tests FAIL because strategic reserve items are not yet implemented.

Design ref: BEACON decisions #67/68.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.loop.guardrail import Guardrail, GuardrailChain, GuardrailResult
from auto_engineering.metrics.collector import MetricsCollector


# =============================================================================
# T91 — PII Guardrail G10
# =============================================================================


class TestPIIGuardrailG10:
    """T91: PIIGuardrail scans developer files for PII patterns."""

    def test_pii_guardrail_module_exists(self) -> None:
        """PII guardrail module MUST exist."""
        try:
            import auto_engineering.pii.guardrail  # noqa: F401
        except ImportError:
            pytest.fail(
                "T91 NOT FIXED: auto_engineering/pii/guardrail.py does not exist. "
                "G10 PII Guardrail is the second defense line after prompt redaction."
            )

    def test_pii_guardrail_is_guardrail_subclass(self) -> None:
        """PIIGuardrail MUST be a Guardrail subclass."""
        from auto_engineering.pii.guardrail import PIIGuardrail

        assert issubclass(PIIGuardrail, Guardrail), (
            "T91 NOT FIXED: PIIGuardrail is not a Guardrail subclass."
        )

    def test_pii_guardrail_scans_files(self, tmp_path: Path) -> None:
        """PIIGuardrail MUST detect PII in changed files."""
        from auto_engineering.pii.guardrail import PIIGuardrail

        # Create a file with PII
        test_file = tmp_path / "test_file.py"
        test_file.write_text("phone = '13812345678'  # should be detected")

        guardrail = PIIGuardrail(project_root=tmp_path)
        result = guardrail.check(files_changed=[str(test_file)])

        assert not result.passed, (
            "T91 NOT FIXED: PIIGuardrail did not detect PII in changed files."
        )

    def test_pii_guardrail_passes_clean_files(self, tmp_path: Path) -> None:
        """PIIGuardrail MUST pass when files contain no PII."""
        from auto_engineering.pii.guardrail import PIIGuardrail

        test_file = tmp_path / "clean.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        guardrail = PIIGuardrail(project_root=tmp_path)
        result = guardrail.check(files_changed=[str(test_file)])

        assert result.passed, (
            "T91 NOT FIXED: PIIGuardrail blocked clean files (false positive)."
        )

    def test_pii_guardrail_block_mode(self, tmp_path: Path) -> None:
        """PIIGuardrail in block_mode MUST trigger block verdict."""
        from auto_engineering.pii.guardrail import PIIGuardrail

        test_file = tmp_path / "secret.py"
        test_file.write_text("api_key = 'sk-1234567890abcdef'")

        guardrail = PIIGuardrail(project_root=tmp_path, block_mode=True)
        result = guardrail.check(files_changed=[str(test_file)])

        assert not result.passed
        assert result.action == "block", (
            "T91 NOT FIXED: block_mode not producing block action."
        )

    def test_pii_guardrail_in_chain_default(self) -> None:
        """GuardrailChain.default() SHOULD include PIIGuardrail in developer stage."""
        chain = GuardrailChain.default()
        # Check that there is a PII-related guardrail in the chain
        names = [g.name for g in chain.guardrails]
        has_pii = any("pii" in name.lower() for name in names)
        assert has_pii, (
            "T91 NOT FIXED: PIIGuardrail not in GuardrailChain.default()."
        )


# =============================================================================
# T92 — Large file offloading
# =============================================================================


class TestT92LargeFileOffloading:
    """T92: Intermediate artifact offloading for large files."""

    def test_offloader_has_offload_file_method(self) -> None:
        """ContextOffloader MUST have an offload_file method."""
        from auto_engineering.context.offloading import ContextOffloader

        assert hasattr(ContextOffloader, "offload_file"), (
            "T92 NOT FIXED: ContextOffloader has no offload_file() method."
        )

    def test_offload_file_writes_to_disk(self, tmp_path: Path) -> None:
        """offload_file MUST write content to offload directory."""
        from auto_engineering.context.offloading import ContextOffloader

        offloader = ContextOffloader(storage_dir=tmp_path / ".ae-offload")
        path = offloader.offload_file(
            "design_doc",
            "# Big Design Document\n" * 100,
        )
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "Big Design Document" in content

    def test_offload_file_returns_summary(self, tmp_path: Path) -> None:
        """offload_file MUST return path + summary, not full content."""
        from auto_engineering.context.offloading import ContextOffloader

        offloader = ContextOffloader(storage_dir=tmp_path / ".ae-offload")
        path = offloader.offload_file(
            "large_code",
            "def x():\n    pass\n" * 100,
            max_inline_lines=5,
        )
        assert path is not None
        # Summary should be shorter than full content
        summary = offloader.get_summary("large_code")
        assert summary is not None
        assert len(summary) < 1000  # Summary much shorter than 200-line file


# =============================================================================
# T93 — LangSmith exporter
# =============================================================================


class TestT93LangSmithExporter:
    """T93: Optional LangSmith OTLP bridge (removed — dead code, 2026-07-21 audit)."""

    def test_langsmith_exporter_removed_dead_code(self) -> None:
        """LangSmith exporter module was 100% dead code — removed per audit."""
        import importlib
        spec = importlib.util.find_spec("auto_engineering.observability.langsmith_exporter")
        assert spec is None, "langsmith_exporter removed as dead code (0 imports)"

    def test_langsmith_exporter_is_optional(self) -> None:
        """LangSmith exporter was 0-import dead module — removed."""
        import importlib
        spec = importlib.util.find_spec("auto_engineering.observability.langsmith_exporter")
        assert spec is None, "langsmith_exporter removed as dead code"


# =============================================================================
# T94 — Pre-planned Gate (DecisionGate form 1)
# =============================================================================


class TestT94PreplannedGate:
    """T94: batch_plan schema extended with gate declarations."""

    def test_batch_state_has_get_pending_gate(self) -> None:
        """BatchState MUST have _get_pending_gate() method."""
        from auto_engineering.engine.batch_state import BatchState

        assert hasattr(BatchState, "_get_pending_gate"), (
            "T94 NOT FIXED: BatchState has no _get_pending_gate() method."
        )


# =============================================================================
# T95 — Escalation Gate (DecisionGate form 2)
# =============================================================================


class TestT95EscalationGate:
    """T95: ae dev-loop --escalate CLI entry."""

    def test_escalate_cli_option_exists(self) -> None:
        """ae dev-loop MUST accept --escalate option."""
        source_path = Path(__file__).parent.parent / "auto_engineering" / "cli" / "__init__.py"
        source = source_path.read_text()
        assert "--escalate" in source, (
            "T95 NOT FIXED: ae dev-loop --escalate CLI option does not exist."
        )


# =============================================================================
# T96 — Task DAG dependencies
# =============================================================================


class TestT96BatchDAG:
    """T96: Batch DAG with depends_on for topological scheduling."""

    def test_batch_state_supports_depends_on(self) -> None:
        """BatchState MUST support depends_on field in batch_plan."""
        from auto_engineering.engine.batch_state import BatchState

        plan_json = {
            "batches": [
                {"id": "b1", "tasks": [], "depends_on": []},
                {"id": "b2", "tasks": [], "depends_on": ["b1"]},
            ],
        }
        bs = BatchState.from_plan(plan_json)
        assert bs is not None

    def test_batch_state_ready_queue(self) -> None:
        """BatchState MUST provide ready batches in topological order."""
        from auto_engineering.engine.batch_state import BatchState

        plan_json = {
            "batches": [
                {"id": "b1", "tasks": [], "depends_on": []},
                {"id": "b2", "tasks": [], "depends_on": ["b1"]},
                {"id": "b3", "tasks": [], "depends_on": []},
            ],
        }
        bs = BatchState.from_plan(plan_json)
        ready = bs.ready_batches()
        # b1 and b3 should be ready (no deps); b2 blocked by b1
        ready_ids = {b["id"] if isinstance(b, dict) else b.id for b in ready}
        assert "b1" in ready_ids
        assert "b3" in ready_ids
        assert "b2" not in ready_ids


# =============================================================================
# T97 — Message type semantics
# =============================================================================


class TestT97MessageType:
    """T97: action/result schema with message_type field."""

    def test_action_schema_has_message_type(self) -> None:
        """action JSON schema MUST include message_type field."""
        schema_path = (
            Path(__file__).parent.parent
            / "auto_engineering" / "loop" / "action.schema.json"
        )
        if schema_path.exists():
            schema = json.loads(schema_path.read_text())
            props = schema.get("properties", {})
            assert "message_type" in props, (
                "T97 NOT FIXED: action.schema.json missing message_type field."
            )
