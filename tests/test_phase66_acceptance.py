"""v5.8 T318：Phase 66 成本与完整性专项验收。"""

from __future__ import annotations

from auto_engineering.prompts.compiler import compile_prompt_bundle
from auto_engineering.prompts.contracts import default_prompt_contracts


def test_prompt_bytes_remain_linear_when_completed_history_grows() -> None:
    contract = default_prompt_contracts()["developer"]
    sizes: list[int] = []

    for tick in range(1, 151):
        bundle = compile_prompt_bundle(
            contract=contract,
            role_prompt="你是 Developer。",
            context={
                "requirement": "实现确定性治理内核",
                "feedback": "只处理当前批次",
                "batch_id": f"B{tick}",
                "component": "Kernel",
                "tasks": [{"id": f"T{tick}", "description": "当前任务"}],
                "project_profile_summary": {
                    "profile_id": "sha256:test",
                    "commands": {"test": ["pytest"]},
                },
                "completed_batches": [
                    {"batch_id": f"B{done}", "status": "done"}
                    for done in range(1, tick)
                ],
            },
            expected_format={"files_changed": "array"},
        )
        assert bundle.coordinator_prompt == ""
        sizes.append(len(bundle.worker_prompts[0].prompt.encode("utf-8")))

    assert max(sizes) < min(sizes) * 1.10
    assert sum(sizes) < sizes[0] * 150 * 1.10
