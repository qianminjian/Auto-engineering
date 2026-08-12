"""Phase 82 T439：Voice Clone 原始设计黄金语义验收。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.loop.action_builder import ActionBuilder
from tests.host_runtime.fake_host import FakeHostRuntime

FIXTURE = (
    Path(__file__).parent / "fixtures" / "golden"
    / "voice_clone_design_manifest.json"
)


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
        "spawned": True,
        "plan": "保留纯前端 V1 设计并按八层架构实施。",
        "batch_plan": [{"batch_id": "B1"}],
    })

    assert execution.receipt["execution_identity"]["role"] == "worker"
    assert execution.result["plan"].startswith("保留纯前端 V1")
