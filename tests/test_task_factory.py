"""M3 Plan + Task Factory — Plan.get_tasks_by_stage / parallelism_groups + task_factory 测试.

设计参考: v5.6-Design-Loop.md §B1.7 (Plan 方法)
                   + §B2.12b (_topological_layers Kahn 变体)
                   + §B7.2 (apply_outcome_to_state)
                   + §B7.3 (tasks_from_batch_plan)

测试原则 (per pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- Plan.get_tasks_by_stage: 4 用例 (architect / developer / critic / 无匹配)
- Plan.parallelism_groups: 3 用例 (单 task / 多并行 / 链式依赖)
- DAG 环检测: 1 用例 (raises ConflictError)
- tasks_from_batch_plan: 3 用例 (空 batch / 单 batch / 多 batch + critic 追加)
- apply_outcome_to_state: 3 role × 2 边界 (完整字段 / 部分字段)
"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.loop.plan import (
    ConflictError,
    Plan,
    Task,
)
from auto_engineering.loop.round import TaskOutcome
from auto_engineering.loop.task_factory import (
    apply_outcome_to_state,
    tasks_from_batch_plan,
)

# ============================================================
# Plan.get_tasks_by_stage — 4 用例
# ============================================================


def test_get_tasks_by_stage_architect_returns_only_architect_tasks() -> None:
    """get_tasks_by_stage('architect') 只返回 role='architect' 的 Task."""
    plan = Plan(tasks=[
        Task(id="a1", title="A1", expected_output="arch", role="architect"),
        Task(id="d1", title="D1", expected_output="dev", role="developer"),
        Task(id="c1", title="C1", expected_output="critic", role="critic"),
    ])
    result = plan.get_tasks_by_stage("architect")
    assert len(result) == 1
    assert result[0].id == "a1"
    assert result[0].role == "architect"


def test_get_tasks_by_stage_developer_returns_only_developer_tasks() -> None:
    """get_tasks_by_stage('developer') 过滤多个 developer task."""
    plan = Plan(tasks=[
        Task(id="a1", title="A1", expected_output="arch", role="architect"),
        Task(id="d1", title="D1", expected_output="dev", role="developer"),
        Task(id="d2", title="D2", expected_output="dev", role="developer"),
        Task(id="c1", title="C1", expected_output="critic", role="critic"),
    ])
    result = plan.get_tasks_by_stage("developer")
    ids = {t.id for t in result}
    assert ids == {"d1", "d2"}
    for t in result:
        assert t.role == "developer"


def test_get_tasks_by_stage_critic_returns_only_critic_tasks() -> None:
    """get_tasks_by_stage('critic') 只返回 critic task."""
    plan = Plan(tasks=[
        Task(id="a1", title="A1", expected_output="arch", role="architect"),
        Task(id="c1", title="C1", expected_output="critic", role="critic"),
        Task(id="c2", title="C2", expected_output="critic", role="critic"),
    ])
    result = plan.get_tasks_by_stage("critic")
    assert len(result) == 2
    for t in result:
        assert t.role == "critic"


def test_get_tasks_by_stage_no_match_returns_empty_list() -> None:
    """无匹配 stage 返回 [] (不抛异常)."""
    plan = Plan(tasks=[
        Task(id="a1", title="A1", expected_output="arch", role="architect"),
        Task(id="d1", title="D1", expected_output="dev", role="developer"),
    ])
    assert plan.get_tasks_by_stage("nonexistent") == []
    # 正常存在的 stage 但 plan 为空 → 也返回 []
    empty_plan = Plan(tasks=[])
    assert empty_plan.get_tasks_by_stage("architect") == []


# ============================================================
# Plan.parallelism_groups — 3 用例
# ============================================================


def test_parallelism_groups_single_task_returns_one_group() -> None:
    """单 task → [[task_id]] (一层一组)."""
    plan = Plan(tasks=[
        Task(id="solo", title="S", expected_output="x", role="developer"),
    ])
    groups = plan.parallelism_groups()
    assert groups == [["solo"]]


def test_parallelism_groups_multiple_parallel_returns_one_group() -> None:
    """多无依赖 task → 一个并行组,所有 task id 在同层."""
    plan = Plan(tasks=[
        Task(id="a", title="A", expected_output="x", role="architect"),
        Task(id="b", title="B", expected_output="y", role="architect"),
        Task(id="c", title="C", expected_output="z", role="architect"),
    ])
    groups = plan.parallelism_groups()
    assert len(groups) == 1
    # 单层包含所有 task,顺序不固定
    assert set(groups[0]) == {"a", "b", "c"}


def test_parallelism_groups_chain_dependency_returns_layered_groups() -> None:
    """链式依赖 (a→b→c) → 三层,每层一个 task."""
    plan = Plan(tasks=[
        Task(id="a", title="A", expected_output="x", role="developer"),
        Task(id="b", title="B", expected_output="y", role="developer", depends_on=["a"]),
        Task(id="c", title="C", expected_output="z", role="developer", depends_on=["b"]),
    ])
    groups = plan.parallelism_groups()
    assert len(groups) == 3
    assert groups[0] == ["a"]
    assert groups[1] == ["b"]
    assert groups[2] == ["c"]


# ============================================================
# DAG 环检测 — 1 用例
# ============================================================


def test_parallelism_groups_dag_cycle_raises_conflict_error() -> None:
    """Plan.parallelism_groups 检测到环 → 抛 ConflictError."""
    plan = Plan(tasks=[
        Task(id="x", title="X", expected_output="a", role="developer", depends_on=["y"]),
        Task(id="y", title="Y", expected_output="b", role="developer", depends_on=["x"]),
    ])
    with pytest.raises(ConflictError):
        plan.parallelism_groups()


# ============================================================
# tasks_from_batch_plan — 3 用例
# ============================================================


def test_tasks_from_batch_plan_empty_batch_returns_critic_only() -> None:
    """空 batch_plan → 只有 critic-review task."""
    plan = tasks_from_batch_plan([], requirement="req-1")
    assert len(plan.tasks) == 1
    assert plan.tasks[0].id == "critic-review"
    assert plan.tasks[0].role == "critic"
    assert plan.requirement == "req-1"


def test_tasks_from_batch_plan_missing_task_id_raises_aeerror() -> None:
    """畸形 batch_plan (task 缺必填 id) → 抛 AEError(INVALID_AGENT_OUTPUT), 非 raw KeyError."""
    batch_plan = [{
        "batch_id": "batch-X",
        "design_section": "B2",
        "component": "Foo",
        "tasks": [
            {"description": "缺 id 的畸形 task",
             "file_targets": ["auto_engineering/foo.py"]},
        ],
    }]
    with pytest.raises(AEError) as exc_info:
        tasks_from_batch_plan(batch_plan, requirement="r")
    assert exc_info.value.code is ErrorCode.INVALID_AGENT_OUTPUT


def test_tasks_from_batch_plan_empty_task_id_raises_aeerror() -> None:
    """task id 为空串 → 同样视作契约违规 (空 id 破坏 depends_on/critic 引用)."""
    batch_plan = [{
        "batch_id": "batch-Y",
        "tasks": [{"id": "", "description": "空 id", "file_targets": ["x.py"]}],
    }]
    with pytest.raises(AEError) as exc_info:
        tasks_from_batch_plan(batch_plan, requirement="r")
    assert exc_info.value.code is ErrorCode.INVALID_AGENT_OUTPUT


def test_tasks_from_nested_batch_plan_single_batch_multiple_tasks() -> None:
    """v5.6 嵌套: 单 batch 含 2 task → 2 个 developer Task (id 匹配 nested) + critic."""
    batch_plan = [{
        "batch_id": "batch-SR-1",
        "design_section": "B2",
        "component": "StageRouter",
        "depends_on": [],
        "tasks": [
            {"id": "T1", "description": "StageDecision dataclass + next() 骨架",
             "module_ref": "§B2",
             "file_targets": ["auto_engineering/loop/stage_router.py",
                              "tests/test_stage_router.py"]},
            {"id": "T2", "description": "T1-T22 转换表填充",
             "module_ref": "§B2",
             "file_targets": ["auto_engineering/loop/stage_router.py"]},
        ],
    }]
    plan = tasks_from_batch_plan(batch_plan, requirement="实现 StageRouter")
    # 2 developer + 1 critic
    assert len(plan.tasks) == 3
    devs = plan.get_tasks_by_stage("developer")
    assert [t.id for t in devs] == ["T1", "T2"]
    for t in devs:
        assert t.role == "developer"
    # BatchState.current_batch_tasks 靠 task id 匹配 — id 必须来自 nested task
    t1 = plan.get_task("T1")
    assert t1 is not None
    assert t1.description == "StageDecision dataclass + next() 骨架"


def test_tasks_from_nested_batch_plan_file_targets_per_task() -> None:
    """每个 developer Task 携带自己 task 的 file_targets (非 batch 级 files)."""
    batch_plan = [{
        "batch_id": "batch-SR-1", "design_section": "B2", "component": "StageRouter",
        "tasks": [
            {"id": "T1", "description": "d1", "module_ref": "§B2",
             "file_targets": ["a.py", "test_a.py"]},
            {"id": "T2", "description": "d2", "module_ref": "§B2",
             "file_targets": ["b.py"]},
        ],
    }]
    plan = tasks_from_batch_plan(batch_plan, requirement="r")
    t1 = plan.get_task("T1")
    t2 = plan.get_task("T2")
    assert t1.target_files == frozenset({"a.py", "test_a.py"})
    assert t2.target_files == frozenset({"b.py"})


def test_tasks_from_nested_batch_plan_expected_output_derived() -> None:
    """expected_output 由 description 派生 (module_ref 丢弃, 不进 developer action)."""
    batch_plan = [{
        "batch_id": "b1", "design_section": "B2", "component": "C",
        "tasks": [{"id": "T1", "description": "实现登录校验", "module_ref": "§B2",
                   "file_targets": ["login.py"]}],
    }]
    plan = tasks_from_batch_plan(batch_plan, requirement="r")
    t1 = plan.get_task("T1")
    assert "实现登录校验" in t1.expected_output
    assert t1.expected_output.strip() != ""  # 非空 (Plan.validate contract)


def test_tasks_from_nested_batch_plan_task_depends_on_empty() -> None:
    """task 级 depends_on 默认 [] (batch 内顺序即隐式依赖; 跨 batch 由 batch 级表达)."""
    batch_plan = [{
        "batch_id": "b1", "design_section": "B2", "component": "C",
        "depends_on": ["b0"],  # batch 级依赖不下放到 task
        "tasks": [{"id": "T1", "description": "d", "module_ref": "§B2",
                   "file_targets": ["x.py"]}],
    }]
    plan = tasks_from_batch_plan(batch_plan, requirement="r")
    assert plan.get_task("T1").depends_on == []


def test_tasks_from_nested_batch_plan_multiple_batches_critic_all_task_ids() -> None:
    """多 batch → 所有 task 展平为 developer + 1 critic (depends_on = 全部 task id)."""
    batch_plan = [
        {"batch_id": "b1", "design_section": "B2", "component": "C1",
         "tasks": [{"id": "T1", "description": "d1", "module_ref": "§B2",
                    "file_targets": ["a.py"]}]},
        {"batch_id": "b2", "design_section": "B3", "component": "C2", "depends_on": ["b1"],
         "tasks": [
             {"id": "T2", "description": "d2", "module_ref": "§B3", "file_targets": ["b.py"]},
             {"id": "T3", "description": "d3", "module_ref": "§B3", "file_targets": ["c.py"]},
         ]},
    ]
    plan = tasks_from_batch_plan(batch_plan, requirement="multi")
    devs = plan.get_tasks_by_stage("developer")
    assert {t.id for t in devs} == {"T1", "T2", "T3"}
    critic = plan.get_task("critic-review")
    assert critic.role == "critic"
    assert set(critic.depends_on) == {"T1", "T2", "T3"}
    assert plan.requirement == "multi"
# ============================================================


def test_apply_outcome_architect_writes_all_four_fields() -> None:
    """完整 architect 字段 → 全部写入 state."""
    state = EngineState()
    outcome = TaskOutcome(
        task_id="arch-1",
        status="completed",
        task_role="architect",
        output={
            "plan": "## 计划\n实现 foo",
            "file_list": ["src/foo.py", "tests/test_foo.py"],
            "batch_plan": [{"id": "b1"}],
            "contracts": {"b1": "契约 X"},
        },
    )
    apply_outcome_to_state(state, outcome)
    assert state.plan == "## 计划\n实现 foo"
    assert state.file_list == ["src/foo.py", "tests/test_foo.py"]
    assert state.batch_plan == [{"id": "b1"}]
    assert state.contracts == {"b1": "契约 X"}


def test_apply_outcome_architect_partial_fields_leaves_other_unchanged() -> None:
    """部分 architect 字段 → 缺失字段保留 state 原值 (默认值)."""
    state = EngineState()
    outcome = TaskOutcome(
        task_id="arch-2",
        status="completed",
        task_role="architect",
        output={"plan": "仅 plan"},
    )
    apply_outcome_to_state(state, outcome)
    assert state.plan == "仅 plan"
    # 其他字段维持 EngineState 默认
    assert state.file_list == []
    assert state.batch_plan == []
    assert state.contracts == {}


def test_apply_outcome_developer_writes_all_three_fields() -> None:
    """完整 developer 字段 → 全部写入."""
    state = EngineState()
    outcome = TaskOutcome(
        task_id="dev-1",
        status="completed",
        task_role="developer",
        output={
            "files_changed": ["src/foo.py"],
            "commit_hash": "a" * 40,
            "test_results": {"passed": 10, "failed": 0, "errors": 0},
        },
    )
    apply_outcome_to_state(state, outcome)
    assert state.files_changed == ["src/foo.py"]
    assert state.commit_hash == "a" * 40
    assert state.test_results == {"passed": 10, "failed": 0, "errors": 0}


def test_apply_outcome_developer_partial_fields_no_keyerror() -> None:
    """部分 developer 字段 (仅 files_changed) → 不抛 KeyError,缺失字段保持默认."""
    state = EngineState()
    # 先设置默认值以便区分
    state.commit_hash = "previous"
    state.test_results = {"passed": 5}
    outcome = TaskOutcome(
        task_id="dev-2",
        status="completed",
        task_role="developer",
        output={"files_changed": ["src/bar.py"]},
    )
    apply_outcome_to_state(state, outcome)
    # 只覆盖了 files_changed
    assert state.files_changed == ["src/bar.py"]
    # commit_hash 和 test_results 因 outcome 中无对应 key → 不变
    assert state.commit_hash == "previous"
    assert state.test_results == {"passed": 5}


def test_apply_outcome_critic_writes_all_three_fields() -> None:
    """完整 critic 字段 → 全部写入."""
    state = EngineState()
    outcome = TaskOutcome(
        task_id="crit-1",
        status="completed",
        task_role="critic",
        output={
            "verdict": "APPROVE",
            "findings": [{"severity": "minor", "msg": "f1"}],
            "critic_feedback": "ok",
        },
    )
    apply_outcome_to_state(state, outcome)
    assert state.critic_verdict == "APPROVE"
    assert state.findings == [{"severity": "minor", "msg": "f1"}]
    assert state.critic_feedback == "ok"


def test_apply_outcome_critic_partial_fields_leaves_others_unchanged() -> None:
    """部分 critic 字段 (仅 verdict) → 缺失字段保留 state 原值, 不抛 KeyError."""
    state = EngineState()
    state.findings = [{"old": "value"}]
    state.critic_feedback = "old feedback"
    outcome = TaskOutcome(
        task_id="crit-2",
        status="completed",
        task_role="critic",
        output={"verdict": "MAJOR"},
    )
    apply_outcome_to_state(state, outcome)
    assert state.critic_verdict == "MAJOR"
    # 缺失字段不变
    assert state.findings == [{"old": "value"}]
    assert state.critic_feedback == "old feedback"


def test_apply_outcome_critic_with_strengths_and_assessment() -> None:
    """v5.5: critic outcome 含 strengths + assessment → 正确写入 state."""
    state = EngineState()
    outcome = TaskOutcome(
        task_id="crit-3",
        status="completed",
        task_role="critic",
        output={
            "verdict": "APPROVE",
            "findings": [],
            "critic_feedback": "great work",
            "strengths": [
                {"description": "Clean architecture", "location": "src/core.py"},
            ],
            "assessment": "Ready to merge",
        },
    )
    apply_outcome_to_state(state, outcome)
    assert state.critic_verdict == "APPROVE"
    assert state.strengths == [{"description": "Clean architecture", "location": "src/core.py"}]
    assert state.assessment == "Ready to merge"


# ============================================================
# v5.5 Phase 2: severity 映射 (LLM 标签 → P0/P1/P2)
# ============================================================


class TestSeverityMapping:
    """v5.5: apply_outcome_to_state 将 LLM severity 标签映射为 P0/P1/P2."""

    def test_critical_maps_to_p0(self) -> None:
        """severity='Critical' → P0."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "Critical", "file": "x.py", "line": 1,
                     "issue": "null deref"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P0"

    def test_important_maps_to_p1(self) -> None:
        """severity='Important' → P1."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "Important", "file": "y.py", "line": 42,
                     "issue": "missing error handling"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P1"

    def test_minor_maps_to_p2(self) -> None:
        """severity='Minor' → P2."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "Minor", "file": "z.py", "line": 100,
                     "issue": "unused import"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P2"

    def test_p0_preserved(self) -> None:
        """severity='P0' (已映射) → 保持不变."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "P0", "file": "a.py", "line": 1,
                     "issue": "SQL injection"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P0"

    def test_unknown_severity_preserved(self) -> None:
        """未知 severity 标签 → 保持原值 (不覆盖)."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "UnknownTag", "file": "b.py", "line": 5,
                     "issue": "some issue"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "UnknownTag"

    def test_multiple_findings_mixed_severity(self) -> None:
        """多个 findings 不同 severity 全部正确映射."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="crit-1", status="completed", task_role="critic",
            output={
                "verdict": "MAJOR",
                "findings": [
                    {"severity": "Critical", "file": "x.py", "line": 1,
                     "issue": "crash"},
                    {"severity": "Important", "file": "y.py", "line": 42,
                     "issue": "leak"},
                    {"severity": "Minor", "file": "z.py", "line": 100,
                     "issue": "style"},
                ],
            },
        )
        apply_outcome_to_state(state, outcome)
        assert state.findings[0]["severity"] == "P0"
        assert state.findings[1]["severity"] == "P1"
        assert state.findings[2]["severity"] == "P2"

    def test_non_critic_role_skips_severity_mapping(self) -> None:
        """非 critic role 不触发 severity 映射."""
        state = EngineState()
        outcome = TaskOutcome(
            task_id="dev-1", status="completed", task_role="developer",
            output={"files_changed": ["a.py"], "commit_hash": "abc123",
                    "test_results": {"passed": 1}},
        )
        apply_outcome_to_state(state, outcome)
        assert state.files_changed == ["a.py"]
