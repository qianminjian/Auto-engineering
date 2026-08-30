"""Phase 82 T439：Voice Clone 原始设计黄金语义验收。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.host.execution_assembler import HostExecutionAssembler
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.design_decision_ledger import (
    DesignDecisionError,
    DesignDecisionLedger,
)
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from tests.host_runtime.fake_host import FakeHostRuntime
from tests.host_runtime.trajectory_runner import HostTrajectoryRunner

FIXTURE = (
    Path(__file__).parent / "fixtures" / "golden"
    / "voice_clone_design_manifest.json"
)
SCENARIO_ROOT = Path(__file__).parent / "fixtures" / "golden" / "voice_clone"


def _prompt_context(prompt: str) -> dict[str, object]:
    marker = "## 本次任务上下文（编排器注入，禁止自行虚构）"
    section = prompt.split(marker, 1)[1]
    encoded = section.split("```json", 1)[1].split("```", 1)[0]
    value = json.loads(encoded)
    assert isinstance(value, dict)
    return value


def test_voice_clone_manifest_preserves_original_v1_authority() -> None:
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert manifest["binding_decisions"] == {
        "product_architecture": "pure_frontend_react_spa",
        "api_key_storage": "react_memory_only",
        "direct_minimax_api": "v1_current_design",
        "bff": "future_improvement",
        "tdd": "red_green_refactor",
    }
    assert len(manifest["required_layers"]) == 8
    assert manifest["required_components"] == 11
    assert manifest["planned_test_files"] == 17
    assert manifest["planned_test_cases"] == 127
    excerpt = (SCENARIO_ROOT / "design_excerpt.md").read_bytes()
    assert hashlib.sha256(excerpt).hexdigest() == manifest["source_sha256"]
    ledger = DesignDecisionLedger.from_dict(json.loads(
        (SCENARIO_ROOT / "decision_ledger.json").read_text()
    ))
    ledger.validate_source_binding(
        source_sha256=manifest["source_sha256"],
        binding_decision_ids=manifest["binding_decision_ids"],
    )


def test_voice_clone_source_binding_detects_tampered_ledger() -> None:
    value = json.loads((SCENARIO_ROOT / "decision_ledger.json").read_text())
    value["source_sha256"] = "0" * 64
    ledger = DesignDecisionLedger.from_dict(value)
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))

    with pytest.raises(DesignDecisionError, match="DESIGN_LEDGER_SOURCE_MISMATCH"):
        ledger.validate_source_binding(
            source_sha256=manifest["source_sha256"],
            binding_decision_ids=manifest["binding_decision_ids"],
        )


def test_voice_clone_decision_ledger_rejects_bff_promotion() -> None:
    ledger = DesignDecisionLedger.from_dict(json.loads(
        (SCENARIO_ROOT / "decision_ledger.json").read_text()
    ))

    with pytest.raises(DesignDecisionError, match="FUTURE_SCOPE_PROMOTION"):
        ledger.validate_gap({
            "decision_id": "VC-FUTURE-001",
            "scope": "current",
            "blocking": True,
        })


def test_voice_clone_scenario_requires_full_business_lifecycle() -> None:
    scenario = json.loads((SCENARIO_ROOT / "scenario.json").read_text())

    assert scenario["required_stages"] == [
        "architect", "developer", "critic", "component_verifier",
        "plate_deep_audit", "system_verifier", "system_deep_audit", "done",
    ]
    assert scenario["business_gates"] == ["typecheck", "unit_test", "build"]
    assert scenario["required_trajectory_evidence"] == [
        "invocation_count", "manual_protocol_repairs", "unexpected_stops",
        "traceability_complete", "final_disposition",
    ]
    assert "natural_language_plan" in scenario["forbidden_equivalence"]


def test_bff_research_remains_advisory_in_architect_action(tmp_path) -> None:
    state = EngineState(
        thread_id="voice-clone-golden",
        current_stage="architect",
        requirement="按照设计文档完成全部设计任务",
        design_supplements_json=json.dumps({
            "gap-1": {
                "source": "research_agent",
                "content": "建议把 V1 改成同源 BFF",
            }
        }, ensure_ascii=False),
    )

    action = ActionBuilder(tmp_path).build_action(state)

    assert action["design_authority"]["change_policy"] == "user_gate_required"
    research = action["research_and_design_context"][0]
    assert research["authority"] == "advisory"
    assert research["change_policy"] == "user_gate_required"
    assert "未来改进或最佳实践提升为当前范围" in action["subagent_prompt"]


def test_voice_clone_architect_action_runs_in_isolated_fake_host(tmp_path) -> None:
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="voice-clone-worker",
        current_stage="architect",
        requirement="按照设计文档完成全部设计任务",
    ))
    action["message_id"] = "voice-clone-architect-1"
    host = FakeHostRuntime(HostPlatform.CODEX)

    execution = host.execute(action, lambda invocation: {
        "plan": "保留纯前端 V1 设计并按八层架构实施。",
        "batch_plan": [{"batch_id": "B1"}],
    })

    assert execution.receipt["execution_identity"]["role"] == "worker"
    assert execution.result["plan"].startswith("保留纯前端 V1")


def _native_result(action: dict, **payload) -> dict:
    return {
        "schema_version": "1.1", "message_type": "result",
        "message_id": f"result-{action['message_id']}",
        "thread_id": action["thread_id"], "tick": action["tick"],
        "stage": action["stage"], "causation_id": action["message_id"],
        "correlation_id": action["correlation_id"], "extensions": {},
        **payload,
    }


@pytest.mark.parametrize("platform", [HostPlatform.CODEX, HostPlatform.CLAUDE_CODE])
def test_voice_clone_golden_reaches_done_through_real_core(
    tmp_path: Path, platform: HostPlatform,
) -> None:
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    design = design_dir / "voice-clone.md"
    shutil.copy2(SCENARIO_ROOT / "design_excerpt.md", design)
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    shutil.copy2(
        SCENARIO_ROOT / "decision_ledger.json",
        state_dir / "design-decision-ledger.json",
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='voice-clone'\n")
    (tmp_path / "voice_clone").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = TickOrchestrator(
            tmp_path, event_store=events, guardrail=guardrail,
            gate_runner=lambda names, root: {
                name: MagicMock(passed=True, message="ok") for name in names
            },
        )
        action = core.init(
            "严格按 Voice Clone V1 设计实现", design_doc_path="design/voice-clone.md"
        )
        stages: list[str] = []
        batch_index = 0
        result_repairs = 0
        process_recoveries = 0
        critic_rework_injected = False
        for _ in range(30):
            stage = action.get("stage")
            if action.get("action") == "done":
                stages.append("done")
                break
            assert isinstance(stage, str)
            stages.append(stage)
            if stage == "gap_scan":
                design_sections = action["context"]["host_design_sections"]
                gap_result = HostExecutionAssembler(tmp_path).finalize(
                    action=action,
                    outcomes=[],
                    coordinator_payload={
                    "gaps": [],
                    "section_findings": [{
                        "section_ref": item["section_ref"],
                        "verdict": "clear",
                        "evidence": ["黄金设计已明确该章节契约"],
                    } for item in design_sections],
                    },
                )
                corrupted = {
                    **gap_result,
                    "scanned_sections": gap_result["scanned_sections"] + 1,
                }
                rejected = core.tick_dict(corrupted)
                assert rejected["action"] == "error"
                assert OutcomeJournal(tmp_path).complete_from_core(
                    corrupted, rejected
                ) is True
                result_repairs += 1
                # 模拟宿主进程在拒绝后重建；同一 Action 和语义结果必须可恢复。
                gap_result = HostExecutionAssembler(tmp_path).finalize(
                    action=action,
                    outcomes=[],
                    coordinator_payload={
                        "gaps": [],
                        "section_findings": [{
                            "section_ref": item["section_ref"],
                            "verdict": "clear",
                            "evidence": ["黄金设计已明确该章节契约"],
                        } for item in design_sections],
                    },
                )
                process_recoveries += 1
                action = core.tick_dict(gap_result)
                OutcomeJournal(tmp_path).complete_from_core(gap_result, action)
                continue
            if stage == "developer":
                batch_index += 1

            def worker(
                invocation,
                current_stage=stage,
                current_batch=batch_index,
                rework_injected=critic_rework_injected,
            ):
                context = _prompt_context(invocation.prompt)
                if current_stage == "architect":
                    catalog = context.get("design_item_catalog", [])
                    refs_by_component = {}
                    for item in catalog:
                        refs_by_component.setdefault(item.get("component"), []).append(
                            item["design_item"]
                        )
                    return {
                        "plan": (
                            "保留纯前端 SPA、内存 API Key 和 MiniMax 直连设计，"
                            "按两个设计板块实施并完成全部测试、审查及构建验证。"
                        ),
                        "batch_plan": [
                            {"batch_id": "B1", "component": "VoiceClonePage",
                             "design_item_refs": refs_by_component.get("VoiceClonePage", []),
                             "tasks": [{"id": "B1-T1", "description": "页面",
                                        "file_targets": ["voice_clone/page.py"]}]},
                            {"batch_id": "B2", "component": "AudioPipeline",
                             "design_item_refs": refs_by_component.get("AudioPipeline", []),
                             "tasks": [{"id": "B2-T1", "description": "音频",
                                        "file_targets": ["voice_clone/audio.py"]}]},
                        ],
                        "file_list": ["voice_clone/page.py", "voice_clone/audio.py"],
                        "contracts": {},
                        "decision_impacts": [
                            {"decision_id": "VC-ARCH-001", "impact": "preserve"},
                            {"decision_id": "VC-SEC-001", "impact": "preserve"},
                        ],
                    }
                if current_stage == "developer":
                    return {
                        "batch_id": context["batch_id"],
                        "files_changed": [f"voice_clone/part_{current_batch}.py"],
                        "commit_hash": "",
                        "test_results": {"passed": 127, "failed": 0, "total": 127},
                        "red_evidence": ["先失败后通过"],
                    }
                if current_stage == "critic" and not rework_injected:
                    return {
                        "verdict": "MAJOR",
                        "findings": [{
                            "severity": "P1",
                            "file": "voice_clone/page.py",
                            "issue": "缺少边界回归",
                            "suggestion": "补齐回归测试",
                        }],
                        "critic_feedback": "修复后重新审查",
                    }
                if current_stage == "critic":
                    return {"verdict": "APPROVE", "findings": [],
                            "critic_feedback": "设计保持一致"}
                if current_stage == "component_verifier":
                    return {
                        "component": context["component"],
                        "coverage_map": [
                            {"design_item": item["design_item"], "status": "IMPLEMENTED",
                             "file": "voice_clone/page.py", "line": 1, "note": ""}
                            for item in context["allowed_design_items"]
                        ],
                        "missing_count": 0, "diverged_count": 0,
                    }
                if current_stage == "plate_deep_audit":
                    return {"plate": context["plate"], "findings": [],
                            "p0_count": 0, "p1_count": 0, "p2_count": 0,
                            "cross_component_issues": [], "total_audited_files": 2}
                if current_stage == "system_verifier":
                    return {"full_coverage_map": [{"design_section": "golden",
                                                    "status": "IMPLEMENTED"}],
                            "total_design_items": 1, "covered_count": 1,
                            "missing_count": 0, "diverged_count": 0}
                if current_stage == "system_deep_audit":
                    return {"findings": [], "p0_count": 0, "p1_count": 0,
                            "p2_count": 0, "total_audited_files": 2,
                            "design_docs_stale": False, "design_doc_suggestions": "",
                            "missing_count": 0, "diverged_count": 0}
                raise AssertionError(f"unexpected stage: {current_stage}")

            assert "spawn" in action, action
            count = action["spawn"]["count"]
            action = HostTrajectoryRunner(
                tmp_path, platform, core=core, event_store=events
            ).run(action, workers=[worker] * count).next_action
            if stage == "critic" and not critic_rework_injected:
                critic_rework_injected = True

        assert action["action"] == "done"
        assert action["verdict"] == "GOAL_ACHIEVED"
        assert result_repairs == 1
        assert process_recoveries == 1
        assert critic_rework_injected is True
        journals = list((
            tmp_path / ".ae-state/host-runtime/outcomes"
        ).glob("*.json"))
        assert journals
        assert all(json.loads(path.read_text())["status"] == "accepted" for path in journals)
        assert stages == [
            "gap_scan", "architect",
            "developer", "critic", "developer", "critic",
            "component_verifier", "plate_deep_audit",
            "developer", "critic", "component_verifier", "plate_deep_audit",
            "system_verifier", "system_deep_audit", "done",
        ]
        for required in json.loads(
            (SCENARIO_ROOT / "scenario.json").read_text()
        )["required_stages"]:
            assert required in stages
