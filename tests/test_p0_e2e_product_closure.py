"""P0-E2E：真实 Gap Scan 宿主边界的第一条纵向回归轨迹。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.host.execution_assembler import (
    HostEvidenceValidationError,
    HostExecutionAssembler,
)
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _core(project_root: Path, event_store: SQLiteEventStore) -> TickOrchestrator:
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        project_root,
        event_store=event_store,
        guardrail=guardrail,
        gate_runner=lambda names, root: {
            name: MagicMock(passed=True, message="ok") for name in names
        },
    )


def _design_doc(project_root: Path) -> Path:
    path = project_root / "design.md"
    path.write_text(
        "## B1 音色克隆\n\n### C1 上传\n明确上传契约。\n",
        encoding="utf-8",
    )
    return path


def test_single_invocation_gap_scan_accepts_semantic_output_without_machine_echo(
    tmp_path: Path,
) -> None:
    """宿主只提交语义结果时，生产链应自动绑定机器事实并继续。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='p0-e2e-fixture'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init(
            "按设计实现音色克隆页面",
            design_doc_path=str(_design_doc(tmp_path)),
        )
        assert action["stage"] == "gap_scan"

        sections = action["context"]["host_design_sections"]
        assert all("section_id" not in section for section in sections)
        semantic_output = {
            "gaps": [],
            "section_findings": [
                {
                    "section_ref": section["section_ref"],
                    "verdict": "clear",
                    "evidence": ["设计章节已给出可核验的上传契约。"],
                }
                for section in sections
            ],
        }

        assembler = HostExecutionAssembler(tmp_path)
        try:
            result = assembler.finalize(
                action=action,
                outcomes=[],
                coordinator_payload=semantic_output,
            )
        except HostEvidenceValidationError as exc:
            pytest.fail(
                "生产宿主仍要求 Agent 复制 Core-owned 字段，"
                f"而不是自动组装 canonical Result: {exc.violations}"
            )

        next_action = core.tick_dict(result)
        OutcomeJournal(tmp_path).complete_from_core(result, next_action)

    assert next_action["stage"] in {"architect", "gap_review"}
    assert next_action["action"] != "error"
    journal = tmp_path / ".ae-state/host-runtime/outcomes" / f"{action['message_id']}.json"
    persisted = json.loads(journal.read_text(encoding="utf-8"))
    assert persisted["status"] == "accepted"
