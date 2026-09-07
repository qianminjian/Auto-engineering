"""T362 空项目 project_setup Action/Result 协议。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _orchestrator(project_root: Path) -> TickOrchestrator:
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        project_root=project_root,
        gate_runner=lambda gate_names, project_root: {
            name: MagicMock(passed=True, message="ok") for name in gate_names
        },
        guardrail=guardrail,
        checkpoint_store=None,
    )


def test_project_setup_policy_has_one_dedicated_service(tmp_path: Path) -> None:
    """Setup policy must not remain embedded in the Tick state machine."""
    from auto_engineering.loop.project_setup_service import ProjectSetupService

    orchestrator = _orchestrator(tmp_path)

    assert isinstance(orchestrator._project_setup_service, ProjectSetupService)
    assert orchestrator._project_setup_service.owner is orchestrator


def test_empty_project_emits_structured_setup_action(tmp_path: Path) -> None:
    action = _orchestrator(tmp_path).init("实现一个页面")

    assert action["action"] == "project_setup_required"
    assert action["stage"] == "project_setup"
    assert action["reason_code"] == "insufficient_project_evidence"
    assert action["missing_capabilities"] == [
        "primary_language",
        "source_roots",
        "test_command",
    ]
    assert action["constraints"]["must_not_assume_framework"] is True
    assert action["message_type"] == "action"


def test_setup_instruction_only_mentions_requested_capabilities(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    action = orchestrator.init("实现 Python slugify")

    assert "eslint_flat_config" not in action["instruction"]
    assert "jsdom_dependency" not in action["instruction"]
    assert "primary_language" in action["instruction"]
    assert "source_roots" in action["instruction"]
    assert "test_command" in action["instruction"]


def test_setup_instruction_gives_minimal_effective_eslint_config(
    tmp_path: Path,
) -> None:
    """有效配置缺口必须给出宿主可直接执行的最小修复形状。"""

    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"lint": "eslint .", "test": "vitest run"},
        "devDependencies": {"eslint": "latest", "vitest": "latest"},
    }))
    (tmp_path / "eslint.config.js").write_text("export default [{}];\n")

    action = _orchestrator(tmp_path).init("实现一个页面")

    assert "eslint_effective_config" in action["missing_capabilities"]
    assert "至少一条实际启用的规则" in action["instruction"]
    assert "rules: {\"no-warning-comments\": \"warn\" }" in action["instruction"]


def test_setup_instruction_does_not_take_over_business_implementation(
    tmp_path: Path,
) -> None:
    action = _orchestrator(tmp_path).init("实现 Python slugify")

    assert "不得实现用户业务功能" in action["instruction"]
    assert "不得创建业务测试" in action["instruction"]
    assert "业务实现只能从 Architect/Developer Action 开始" in action["instruction"]
    assert "smoke 不得导入、创建或引用设计中的业务模块、类、函数或行为" in (
        action["instruction"]
    )
    assert "Python smoke 固定放在声明测试根的 `test_smoke.py`" in (
        action["instruction"]
    )
    assert "不得为了让 smoke 通过而创建业务模块桩代码" in action["instruction"]
    assert "测试门禁必须是一次性非交互命令" in action["instruction"]
    assert "Vitest 使用 `vitest run`" in action["instruction"]
    assert "tests/toolchain.smoke.test.ts" in action["instruction"]
    assert "不得创建 `src/smoke*`" in action["instruction"]
    assert "不得使用 `--passWithNoTests`" in action["instruction"]
    assert action["constraints"]["setup_scope"] == {
        "mode": "capability_only",
        "business_stage": "architect",
        "allowed": [
            "project_metadata",
            "toolchain",
            "source_test_roots",
            "minimal_non_business_smoke",
        ],
        "forbidden": [
            "business_implementation",
            "business_tests",
            "user_docs",
        ],
    }
    assert action["setup_attempt_policy"] == {
        "max_retries_in_action": 1,
        "failure_result_type": "project_setup_failed",
        "max_failure_streak": 3,
    }


def test_setup_gate_action_contains_executable_project_environment_steps(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现 Python slugify")
    orchestrator._state.current_stage = "project_setup"
    orchestrator._state.missing_project_capabilities = [
        "setup_gate:build",
        "setup_gate:test",
    ]

    action = orchestrator.build_action()

    assert "uv venv .venv" in action["instruction"]
    assert "uv sync --dev --project ." in action["instruction"]
    assert ".ae-state/.ae-runtime" in action["instruction"]
    assert "pytest/ruff/mypy" in action["instruction"]
    assert "PEP 735" in action["instruction"]
    assert "[project.optional-dependencies]" in action["instruction"]
    assert "不得执行 `rm -rf .venv`" in action["instruction"]
    assert "resource_wait" in action["instruction"]
    assert "绝对路径 symlink" in action["instruction"]
    assert "同一 Action 内无限重复失败命令" in action["instruction"]
    assert "project_setup_failed" in action["instruction"]
    assert "failure_code" in action["instruction"]
    assert "attempts_in_action" in action["instruction"]
    assert "立即停止所有 Setup 工具调用" in action["instruction"]
    assert action["result_contract"]["properties"]["failure_code"]["enum"] == [
        "PROJECT_SETUP_BUILD_FAILED",
        "PROJECT_SETUP_COMMAND_FAILED",
        "PROJECT_SETUP_GATE_FAILED",
        "PROJECT_SETUP_SCOPE_VIOLATION",
        "PROJECT_SETUP_TOOLCHAIN_FAILED",
        "PROJECT_SETUP_UNKNOWN_FAILURE",
    ]


def test_unverified_setup_result_keeps_setup_stage(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    initial = orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json"],
    })

    assert action["action"] == "project_setup_required"
    assert action["stage"] == "project_setup"
    assert action["feedback"].startswith("PROJECT_SETUP_UNVERIFIED")
    assert action["message_id"] != initial["message_id"]
    assert action["tick"] > initial["tick"]
    assert action["extensions"]["ae"]["execution_control"]["disposition"] == (
        "CONTINUE"
    )
    assert orchestrator._state.current_stage == "project_setup"


def test_repeated_setup_failure_enters_recoverable_resource_wait(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    result = {
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": [],
    }

    first_retry = orchestrator.tick_dict(result)
    second_retry = orchestrator.tick_dict(result)
    exhausted = orchestrator.tick_dict(result)

    assert first_retry["action"] == "project_setup_required"
    assert second_retry["action"] == "project_setup_required"
    assert exhausted["action"] == "resource_wait"
    assert exhausted["reason_code"] == "PROJECT_SETUP_RETRY_EXHAUSTED"
    assert exhausted["retry_stage"] == "project_setup"
    assert exhausted["active_action_message_id"]
    assert orchestrator._state.project_setup_failure_streak == 3


def test_setup_result_after_resource_wait_is_read_only_even_if_failure_is_malformed(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    for _ in range(3):
        orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": [],
        })

    waiting = orchestrator._active_action
    assert waiting is not None
    assert waiting["action"] == "resource_wait"
    failure = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_failed",
        "artifacts": [],
        "failure_code": "model-guessed-code",
        "failure_summary": "宿主在等待边界重复提交了失败摘要",
        "attempts_in_action": 99,
    })

    assert failure["action"] == "resource_wait"
    assert failure["reason_code"] == "PROJECT_SETUP_RETRY_EXHAUSTED"
    assert failure["message_id"] == waiting["message_id"]
    assert orchestrator._state.project_setup_failure_streak == 3


def test_invalid_setup_completion_after_resource_wait_returns_repair_action(
    tmp_path: Path,
) -> None:
    """资源恢复后的无效完成声明必须暴露可执行修复，而不能回显旧等待。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    for _ in range(3):
        orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": [],
        })

    waiting = orchestrator._active_action
    assert waiting is not None
    assert waiting["action"] == "resource_wait"

    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {
            "build": "node -e \"console.log('build passed')\"",
            "lint": "node -e \"console.log('lint passed')\"",
            "test": "node -e \"console.log('test passed')\"",
            "typecheck": "node -e \"console.log('typecheck passed')\"",
        },
        "devDependencies": {"typescript": "^5.0.0"},
    }), encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"noEmit": True}}),
        encoding="utf-8",
    )
    (tmp_path / "src/index.ts").write_text("export {};\n", encoding="utf-8")

    repaired = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "tsconfig.json", "src/index.ts"],
    })

    assert repaired["action"] == "project_setup_required"
    assert repaired["stage"] == "project_setup"
    assert repaired["message_id"] != waiting["message_id"]
    assert repaired["feedback"].startswith("PROJECT_SETUP_SCOPE_VIOLATION")
    assert orchestrator._state.project_setup_failure_streak == 3


def test_reported_setup_failure_is_observable_and_issues_next_action(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    initial = orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_failed",
        "artifacts": [],
        "failure_code": "PROJECT_SETUP_BUILD_FAILED",
        "failure_summary": "构建产物包含绝对路径 symlink",
        "attempts_in_action": 2,
    })

    assert action["action"] == "project_setup_required"
    assert action["feedback"].startswith("PROJECT_SETUP_REPORTED_FAILURE")
    assert action["setup_failure_streak"] == 1
    assert action["message_id"] != initial["message_id"]
    assert orchestrator._state.project_setup_failure_streak == 1


def test_reported_setup_failure_rejects_unbounded_in_action_attempts(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_failed",
        "artifacts": [],
        "failure_code": "PROJECT_SETUP_BUILD_FAILED",
        "failure_summary": "仍然失败",
        "attempts_in_action": 3,
    })

    assert action["action"] == "error"
    assert action["error_code"] == "RESULT_VALIDATION_ERROR"
    assert orchestrator._state.project_setup_failure_streak == 0


def test_reported_setup_failure_requires_stable_code_and_bounded_summary(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_failed",
        "artifacts": [],
        "failure_code": "arbitrary-error",
        "failure_summary": "x" * 513,
        "attempts_in_action": 2,
    })

    assert action["action"] == "error"
    assert action["error_code"] == "RESULT_VALIDATION_ERROR"


def test_verified_setup_result_reprobes_and_continues(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src"],
    })

    assert action["action"] == "architect"
    assert action["stage"] == "architect"
    assert orchestrator._state.project_profile_id.startswith("sha256:")
    assert orchestrator._state.missing_project_capabilities == []


def test_verified_setup_commits_stage_transition_with_event_store(
    tmp_path: Path,
) -> None:
    """真跑路径必须以 StageAdvanced 拥有 setup→architect 投影变化。"""
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {
                name: MagicMock(passed=True, message="ok")
                for name in gate_names
            },
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")
        (tmp_path / "src").mkdir()
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "vitest run"}}),
            encoding="utf-8",
        )

        action = orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src"],
        })

        assert action["action"] == "architect"
        stream = events.load_stream(initial["thread_id"])
        expected_types = (
            LoopEventType.RESULT_ACCEPTED,
            LoopEventType.PROJECT_SETUP_COMPLETED,
            LoopEventType.STAGE_ADVANCED,
            LoopEventType.ACTION_ISSUED,
        )
        assert [
            event.event_type
            for event in stream
            if event.event_type in expected_types
        ][-4:] == list(expected_types)
        assert events.load_projection(initial["thread_id"]).current_stage == (
            "architect"
        )


def test_restored_setup_result_does_not_drift_profile_projection(
    tmp_path: Path,
) -> None:
    """跨进程恢复重探测 Profile 不得把未提交内存状态混入 Tick。"""
    with SQLiteEventStore(tmp_path / "events.db") as events:
        def gate_runner(gate_names, project_root):
            return {
                name: MagicMock(passed=True, message="ok")
                for name in gate_names
            }
        first = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=gate_runner,
            checkpoint_store=None,
            event_store=events,
        )
        initial = first.init("实现一个页面")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "business.py").write_text(
            "def business_feature(): pass\n", encoding="utf-8"
        )
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
        (tmp_path / "package.json").write_text(
            '{"scripts":{"test":"vitest run"}}',
            encoding="utf-8",
        )

        restored = TickOrchestrator.restore_from_event_store(
            tmp_path,
            checkpoint_store=None,
            event_store=events,
            thread_id=initial["thread_id"],
            gate_runner=gate_runner,
        )

        action = restored.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["package.json", "src"],
        })

        assert action["action"] == "project_setup_required"
        assert action["feedback"].startswith("PROJECT_SETUP_SCOPE_VIOLATION")
        projected = events.load_projection(initial["thread_id"])
        assert projected is not None
        assert projected.project_profile == restored._state.project_profile
        assert projected.project_profile_id == restored._state.project_profile_id


def test_failed_setup_commits_only_new_setup_action_without_stage_advance(
    tmp_path: Path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {
                name: MagicMock(
                    passed=True,
                    message="ok",
                    not_applicable=False,
                    advisory=False,
                )
                for name in gate_names
            },
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")

        action = orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["package.json"],
        })

        assert action["action"] == "project_setup_required"
        stream = events.load_stream(initial["thread_id"])
        assert sum(
            event.event_type is LoopEventType.ACTION_ISSUED for event in stream
        ) == 2
        assert not any(
            event.event_type in {
                LoopEventType.PROJECT_SETUP_COMPLETED,
                LoopEventType.STAGE_ADVANCED,
            }
            for event in stream
        )
        assert events.load_projection(initial["thread_id"]).current_stage == (
            "project_setup"
        )
        assert events.load_projection(initial["thread_id"]).project_setup_failure_streak == 1


def test_reported_setup_failure_is_persisted_as_a_domain_fact(
    tmp_path: Path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {},
            guardrail=MagicMock(check=MagicMock(return_value=MagicMock(action="pass"))),
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")
        orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_failed",
            "artifacts": [],
            "failure_code": "PROJECT_SETUP_BUILD_FAILED",
            "failure_summary": "构建产物包含绝对路径 symlink",
            "attempts_in_action": 2,
        })

        failures = [
            event for event in events.load_stream(initial["thread_id"])
            if event.event_type is LoopEventType.PROJECT_SETUP_FAILED
        ]
        assert len(failures) == 1
        assert failures[0].payload["failure_code"] == "PROJECT_SETUP_BUILD_FAILED"
        assert failures[0].payload["attempts_in_action"] == 2


def test_setup_rejects_new_business_files_before_profile_completion(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "business.py").write_text("def run(): pass\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_business.py").write_text(
        "def test_business(): assert True\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["pyproject.toml", "src", "tests"],
    })

    assert action["action"] == "project_setup_required"
    assert action["feedback"].startswith("PROJECT_SETUP_SCOPE_VIOLATION")
    assert action["missing_capabilities"] == [
        "primary_language",
        "source_roots",
        "test_command",
    ]
    assert "business_implementation" not in action["missing_capabilities"]
    assert "business_tests" not in action["missing_capabilities"]


def test_setup_scope_violation_is_persisted_as_core_fact(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {},
            guardrail=MagicMock(
                check=MagicMock(return_value=MagicMock(action="pass"))
            ),
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "business.py").write_text(
            "def feature():\n    return 1\n", encoding="utf-8"
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_business.py").write_text(
            "def test_feature():\n    assert True\n", encoding="utf-8"
        )
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'scope-canary'\nversion = '0.1.0'\n"
            "requires-python = '>=3.11'\n"
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            encoding="utf-8",
        )

        action = orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["pyproject.toml", "src", "tests"],
        })

        assert action["action"] == "project_setup_required"
        failures = [
            event for event in events.load_stream(initial["thread_id"])
            if event.event_type is LoopEventType.PROJECT_SETUP_FAILED
        ]
        assert len(failures) == 1
        assert failures[0].payload["failure_code"] == (
            "PROJECT_SETUP_SCOPE_VIOLATION"
        )
        assert failures[0].payload["source"] == "core_validation"
        assert "src/business.py" in failures[0].payload["violations"][
            "business_implementation"
        ]
        assert action["missing_capabilities"] == [
            "primary_language",
            "source_roots",
            "test_command",
        ]


def test_setup_scope_violation_is_not_exposed_as_impossible_capability(
    tmp_path: Path,
) -> None:
    """越界事实不能被投影成 Setup 必须完成的业务能力。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "feature.py").write_text(
        "def feature():\n    return 'business'\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_feature.py").write_text(
        "def test_feature():\n    assert True\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='scope-contract'\nversion='0.1.0'\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["pyproject.toml", "src", "tests"],
    })

    assert action["feedback"].startswith("PROJECT_SETUP_SCOPE_VIOLATION")
    assert "setup_scope:business_implementation" not in (
        action["missing_capabilities"]
    )
    assert "setup_scope:business_tests" not in action["missing_capabilities"]
    assert "不得通过实现业务代码来满足" in action["feedback"]


def test_setup_test_root_wins_when_it_overlaps_source_root(tmp_path: Path) -> None:
    """前端测试根常与 src 重叠，smoke test 不得被报成业务源码。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src" / "smoke").mkdir(parents=True)
    (tmp_path / "src" / "smoke" / "toolchain.test.ts").write_text(
        "import { describe, it, expect } from 'vitest'\n"
        "describe('smoke', () => it('works', () => expect(true).toBe(true)))\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=("src",))
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_recognizes_nested_conventional_test_root(tmp_path: Path) -> None:
    """src/__tests__ 是常见布局，即使 Profile 尚未显式声明也应识别。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    test_file = tmp_path / "src" / "__tests__" / "smoke.test.ts"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "import { describe, it, expect } from 'vitest'\n"
        "describe('smoke', () => it('works', () => expect(true).toBe(true)))\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=())
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_recognizes_test_files_inside_source_root_without_declared_test_root(
    tmp_path: Path,
) -> None:
    """Vite/Vitest 常见的 src/*.test.ts 与 setupTests.ts 不得被误报为业务源码。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    src = tmp_path / "src"
    src.mkdir()
    (src / "setupTests.ts").write_text(
        "import '@testing-library/jest-dom/vitest'\n", encoding="utf-8"
    )
    (src / "smoke.test.ts").write_text(
        "import { describe, it, expect } from 'vitest'\n"
        "describe('toolchain smoke', () => it('works', () => expect(true).toBe(true)))\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=())
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_allows_smoke_test_importing_setup_safe_entry(tmp_path: Path) -> None:
    """Smoke 可验证 setup-safe 入口，但不能因此放行业务模块。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text(
        "// SETUP SMOKE: placeholder entry\nexport function hello() { return 'setup' }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "smoke.test.ts").write_text(
        "import { describe, expect, it } from 'vitest'\n"
        "import { hello } from '../src/index'\n"
        "describe('toolchain smoke', () => it('works', () => expect(hello()).toBe('setup')))\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=("tests",))
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_rejects_source_root_test_that_imports_business_module(
    tmp_path: Path,
) -> None:
    """仅凭 .test.ts 后缀不能放行导入业务模块的业务测试。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    src = tmp_path / "src"
    src.mkdir()
    (src / "smoke.test.ts").write_text(
        "import { cloneVoice } from './voice-clone'\n"
        "test('business', () => cloneVoice())\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=())
    assert orchestrator._project_setup_scope_violations(profile) == {
        "business_tests": ["src/smoke.test.ts"],
    }


def test_setup_allows_project_metadata_and_minimal_smoke_files(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke.py").write_text(
        "def test_smoke(): assert True\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["pyproject.toml", "src", "tests"],
    })

    assert action["action"] == "architect"


def test_setup_allows_node_test_smoke_without_business_imports(tmp_path: Path) -> None:
    """Node 项目的纯工具链 smoke 也不应被误判为业务测试。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke.js").write_text(
        "test('toolchain smoke', () => expect(true).toBe(true));\n",
        encoding="utf-8",
    )

    profile = SimpleNamespace(source_roots=("src",), test_roots=("tests",))
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_ignores_gitkeep_used_to_materialize_empty_source_root(
    tmp_path: Path,
) -> None:
    """空源码根的目录占位文件不能被误报为业务实现。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    src = tmp_path / "src"
    src.mkdir()
    (src / ".gitkeep").write_text("", encoding="utf-8")

    profile = SimpleNamespace(source_roots=("src",), test_roots=())
    assert orchestrator._project_setup_scope_violations(profile) == {}


def test_setup_allows_toolchain_smoke_using_safe_stdlib_modules(
    tmp_path: Path,
) -> None:
    """工具链 smoke 可调用受限标准库，但仍不能导入业务模块。"""
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke.py").write_text(
        "import subprocess\n"
        "import sys\n\n"
        "def test_smoke():\n"
        "    assert subprocess.run([sys.executable, '-c', 'import pytest'], check=True).returncode == 0\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["pyproject.toml", "src", "tests"],
    })

    assert action["action"] == "architect"


def test_setup_allows_marked_node_minimal_smoke_entry(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.tsx").write_text(
        "// Minimal smoke entry — replaced after architect stage\n"
        "export {};\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "smoke.test.ts").write_text(
        "describe('smoke', () => {});\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({
            "scripts": {"test": "vitest run"},
            "devDependencies": {"typescript": "^5.0.0", "vitest": "^3.0.0"},
        }),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src/main.tsx", "tests/smoke.test.ts"],
    })

    assert action["action"] == "architect"


def test_setup_allows_bounded_vite_bootstrap_placeholders(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.tsx").write_text(
        "import React from 'react'\n"
        "import ReactDOM from 'react-dom/client'\n"
        "import { App } from '../container/App'\n\n"
        "ReactDOM.createRoot(document.getElementById('root')!).render(\n"
        "  <React.StrictMode><App /></React.StrictMode>,\n"
        ")\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "container").mkdir()
    (tmp_path / "src" / "container" / "App.tsx").write_text(
        "/** [SETUP SMOKE] static bootstrap placeholder */\n"
        "export function App() { return <div id=\"app-root\" data-testid=\"setup-root\">toolchain smoke</div> }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "test").mkdir()
    (tmp_path / "src" / "test" / "setup.ts").write_text(
        "import '@testing-library/jest-dom'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "vite-env.d.ts").write_text(
        "/// <reference types=\"vite/client\" />\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "smoke.test.ts").write_text(
        "describe('smoke', () => {});\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src", "tests"],
    })

    assert action["action"] == "architect"


def test_setup_rejects_unmarked_node_entry_as_business_source(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.tsx").write_text(
        "export function VoiceClone() { return null; }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "smoke.test.ts").write_text(
        "describe('smoke', () => {});\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src/main.tsx", "tests/smoke.test.ts"],
    })

    assert action["action"] == "project_setup_required"
    assert action["feedback"].startswith("PROJECT_SETUP_SCOPE_VIOLATION")
    assert "setup_scope:business_implementation" not in action["missing_capabilities"]
    assert "不得通过实现业务代码来满足" in action["feedback"]


def test_setup_ignores_generated_python_package_metadata(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src" / "canary_math.egg-info").mkdir(parents=True)
    (tmp_path / "src" / "canary_math.egg-info" / "PKG-INFO").write_text(
        "Metadata-Version: 2.4\nName: canary-math\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "canary_math").mkdir()
    (tmp_path / "src" / "canary_math" / "__init__.py").write_text(
        "",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_smoke.py").write_text(
        "def test_smoke(): assert True\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["pyproject.toml", "src", "tests"],
    })

    assert action["action"] == "architect"


def test_setup_result_requires_expected_result_type(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "claimed_complete",
        "artifacts": [],
    })

    assert action["action"] == "error"
    assert action["error_code"] == "RESULT_VALIDATION_ERROR"


def test_setup_does_not_complete_when_declared_quality_gate_fails(
    tmp_path: Path,
) -> None:
    def gate_runner(gate_names, project_root):
        return {
            name: MagicMock(
                passed=name != "lint",
                message="lint config ineffective" if name == "lint" else "ok",
                not_applicable=False,
                advisory=False,
            )
            for name in gate_names
        }

    orchestrator = TickOrchestrator(
        project_root=tmp_path,
        gate_runner=gate_runner,
        guardrail=MagicMock(check=MagicMock(return_value=MagicMock(action="pass"))),
        checkpoint_store=None,
    )
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/setup_smoke.test.ts").write_text("export {};\n")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {
            "lint": "eslint .",
            "typecheck": "tsc --noEmit",
            "test": "vitest run",
            "build": "vite build",
        },
        "devDependencies": {"eslint": "^8.0.0", "typescript": "^5.0.0"},
    }))

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src", "tests"],
    })

    assert action["action"] == "project_setup_required"
    assert action["feedback"].startswith("PROJECT_SETUP_GATE_FAILED")
    assert orchestrator._state.current_stage == "project_setup"
    assert orchestrator._state.missing_project_capabilities == ["setup_gate:lint"]
    assert orchestrator._state.gate_results["lint"]["passed"] is False
