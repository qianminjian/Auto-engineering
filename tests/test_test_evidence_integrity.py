"""T786 测试证据完整性守门回归。"""

from pathlib import Path
from types import SimpleNamespace

from auto_engineering.engine.models import Plan, Task
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuildContext, ActionBuilder
from auto_engineering.loop.guardrails.test_evidence import (
    TestEvidenceIntegrityGuardrail,
    collect_test_assertion_baseline,
    count_test_assertions,
)


def test_count_test_assertions_covers_python_and_typescript() -> None:
    source = """
assert value == 1
expect(value).toBe(1)
expect(value).not.toContain('secret')
"""

    assert count_test_assertions(source) == 3


def test_collect_baseline_is_relative_and_ignores_non_test_files(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "contract.test.ts"
    source_file = tmp_path / "src" / "client.ts"
    test_file.parent.mkdir()
    source_file.parent.mkdir()
    test_file.write_text("expect(value).toBe(true)\n", encoding="utf-8")
    source_file.write_text("expect(value).toBe(true)\n", encoding="utf-8")

    baseline = collect_test_assertion_baseline(
        ["tests/contract.test.ts", "src/client.ts"], tmp_path,
    )

    assert baseline == {"tests/contract.test.ts": {"assertion_count": 1}}


def test_guardrail_retries_when_changed_test_assertions_are_removed(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "contract.test.ts"
    test_file.parent.mkdir()
    test_file.write_text("expect(value).toBe(true)\n", encoding="utf-8")
    state = SimpleNamespace(
        files_changed=["tests/contract.test.ts"],
        _runtime_ctx={
            "active_action": {
                "context": {
                    "test_evidence_baseline": {
                        "tests/contract.test.ts": {"assertion_count": 2},
                    },
                },
            },
        },
    )

    result = TestEvidenceIntegrityGuardrail().check(
        "developer", state, project_root=tmp_path,
    )

    assert result.action == "retry"
    assert "测试断言" in result.message


def test_guardrail_allows_same_or_stronger_test_evidence(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "contract.test.ts"
    test_file.parent.mkdir()
    test_file.write_text(
        "expect(value).toBe(true)\nexpect(value).not.toContain('secret')\n",
        encoding="utf-8",
    )
    state = SimpleNamespace(
        files_changed=["tests/contract.test.ts"],
        _runtime_ctx={
            "active_action": {
                "context": {
                    "test_evidence_baseline": {
                        "tests/contract.test.ts": {"assertion_count": 1},
                    },
                },
            },
        },
    )

    result = TestEvidenceIntegrityGuardrail().check(
        "developer", state, project_root=tmp_path,
    )

    assert result.passed


def test_developer_action_carries_test_evidence_baseline(tmp_path: Path, monkeypatch) -> None:
    test_file = tmp_path / "tests" / "contract.test.ts"
    test_file.parent.mkdir()
    test_file.write_text("expect(value).toBe(true)\n", encoding="utf-8")
    state = EngineState(thread_id="thread", current_stage="developer")
    plan = Plan(tasks=[Task(
        id="T1",
        title="contract",
        expected_output="tested",
        target_files={"tests/contract.test.ts"},
    )])
    builder = ActionBuilder(tmp_path)
    builder._bound_context = ActionBuildContext(state=state, plan=plan)
    monkeypatch.setattr(
        builder,
        "_build_stage_action",
        lambda base, action, **kwargs: {"extensions": {}},
    )

    action = builder._build_action_developer({})

    assert action["extensions"]["test_evidence_baseline"] == {
        "tests/contract.test.ts": {"assertion_count": 1},
    }
