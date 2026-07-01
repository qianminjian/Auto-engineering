"""P2-B-1 (deep audit) — engine/state.py 直接测试.

之前 test_type_aliases_p1b.py 只测了重命名 (LoopState → EngineState
alias) 和字段存在性, 78 行 EngineState 的核心方法 to_dict / from_dict
/ get_channels / set_channels 没有直接 round-trip 测试. SQLite checkpoint
migrate 依赖 to_dict 输出, CheckpointEnvelope.from_dict 重建, 都
需要 round-trip 保护.

测试原则 (per pytest-memory-management.md): 单文件 pytest --no-cov --timeout=60.
"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState, LoopState


class TestEngineStateRoundTrip:
    """to_dict → from_dict round-trip."""

    def test_empty_state_round_trip(self) -> None:
        """空 state round-trip."""
        original = EngineState()
        restored = EngineState.from_dict(original.to_dict())
        assert restored == original

    def test_populated_state_round_trip(self) -> None:
        """填满字段的 state round-trip."""
        original = EngineState(
            requirement="build hello world CLI",
            current_stage="developer",
            plan="1. Create main.py\n2. Add tests",
            file_list=["src/main.py", "tests/test_main.py"],
            commit_hash="abc123",
            test_results={"passed": 5, "failed": 0},
            verdict="APPROVE",
            findings=[{"severity": "info", "msg": "ok"}],
            critic_feedback="Looks good.",
        )
        restored = EngineState.from_dict(original.to_dict())
        assert restored == original
        assert restored.requirement == "build hello world CLI"
        assert restored.file_list == ["src/main.py", "tests/test_main.py"]
        assert restored.findings == [{"severity": "info", "msg": "ok"}]

    def test_to_dict_is_json_serializable(self) -> None:
        """to_dict 输出可直接 json.dumps (Checkpoint 持久化路径)."""
        import json
        state = EngineState(requirement="x", plan="p", file_list=["a.py"])
        dumped = json.dumps(state.to_dict())
        loaded = json.loads(dumped)
        assert loaded["requirement"] == "x"
        assert loaded["plan"] == "p"
        assert loaded["file_list"] == ["a.py"]


class TestFromDictDefensive:
    """from_dict 忽略未知字段 (schema 演进兼容)."""

    def test_unknown_fields_silently_dropped(self) -> None:
        """from_dict 收到 schema 中不存在的字段 → 静默忽略, 不抛 KeyError."""
        data = {
            "requirement": "x",
            "unknown_field_added_in_v2_6": "should_be_dropped",
            "another_unknown": 42,
        }
        state = EngineState.from_dict(data)
        assert state.requirement == "x"
        assert not hasattr(state, "unknown_field_added_in_v2_6")

    def test_missing_fields_use_defaults(self) -> None:
        """from_dict 缺字段时使用 dataclass 默认值."""
        state = EngineState.from_dict({"requirement": "only this"})
        assert state.requirement == "only this"
        assert state.plan == ""  # default
        assert state.file_list == []  # default factory


class TestBackwardCompatAlias:
    """P1-B 重命名: LoopState 仍是 EngineState 的 alias."""

    def test_loop_state_is_engine_state(self) -> None:
        assert LoopState is EngineState

    def test_loop_state_works_with_to_dict(self) -> None:
        """LoopState (alias) 也能 to_dict."""
        state = LoopState(requirement="via alias")
        d = state.to_dict()
        assert d["requirement"] == "via alias"


class TestGetSetChannels:
    """get_channels / set_channels 辅助方法."""

    def test_get_channels_existing(self) -> None:
        """get_channels 返回已存在字段的值."""
        state = EngineState(requirement="x", plan="p")
        result = state.get_channels(["requirement", "plan"])
        assert result == {"requirement": "x", "plan": "p"}

    def test_get_channels_missing_silently_skipped(self) -> None:
        """get_channels 对不存在的字段静默跳过 (不抛 KeyError)."""
        state = EngineState()
        result = state.get_channels(["requirement", "nonexistent_field"])
        assert result == {"requirement": ""}

    def test_set_channels_updates_fields(self) -> None:
        """set_channels 把 writes 写入对应字段."""
        state = EngineState()
        state.set_channels({"plan": "new plan", "commit_hash": "xyz"})
        assert state.plan == "new plan"
        assert state.commit_hash == "xyz"


class TestEngineStateFieldDefaults:
    """Phase 10: 17 字段默认值 + 类型契约.

    v5.0 M1: 字段从 13 → 17 (+batch_plan list[dict] / +majors_in_a_row /
    +total_majors / +thread_id). 验证所有字段默认值与类型契约.
    """

    def test_all_17_fields_exist(self) -> None:
        """EngineState 暴露 17 个字段 (v5.0 §B1.1)."""
        from dataclasses import fields

        state = EngineState()
        field_names = {f.name for f in fields(EngineState)}
        # 17 字段 (含 _pending_sends 是 v2.0+ 多 Agent 字段)
        expected = {
            "requirement", "current_stage",
            "thread_id", "majors_in_a_row", "total_majors",
            "plan", "file_list", "batch_plan", "contracts",
            "files_changed", "commit_hash", "test_results",
            "verdict", "findings", "critic_feedback",
            "_pending_sends",
        }
        assert field_names == expected, (
            f"EngineState 字段不匹配 v5.0 §B1.1. "
            f"缺失: {expected - field_names}, 多余: {field_names - expected}"
        )

    def test_default_values_for_all_fields(self) -> None:
        """所有字段默认值符合 v5.0 §B1.1 表."""
        state = EngineState()

        # 输入/控制
        assert state.requirement == ""
        assert state.current_stage == ""

        # 控制 (新增 4 字段, v5.0 M1)
        assert isinstance(state.thread_id, str) and len(state.thread_id) == 36  # UUID v4
        assert state.majors_in_a_row == 0
        assert state.total_majors == 0

        # Architect 输出
        assert state.plan == ""
        assert state.file_list == []
        assert state.batch_plan == []  # M1 修正: v2.5 错为 dict
        assert state.contracts == {}

        # Developer 输出
        assert state.files_changed == []
        assert state.commit_hash == ""
        assert state.test_results == {}

        # Critic 输出
        assert state.verdict == ""
        assert state.findings == []
        assert state.critic_feedback == ""

        # 多 Agent 预留
        assert state._pending_sends == []

    def test_thread_id_is_unique_per_instance(self) -> None:
        """每个新 EngineState 实例的 thread_id 应唯一 (UUID v4)."""
        ids = {EngineState().thread_id for _ in range(100)}
        assert len(ids) == 100, f"100 个实例的 thread_id 全部唯一, 实际 {len(ids)} 个"

    def test_thread_id_format_is_uuid_v4(self) -> None:
        """thread_id 默认值符合 UUID v4 格式 (8-4-4-4-12)."""
        import re
        import uuid

        state = EngineState()
        # 验证可被 uuid.UUID 解析
        parsed = uuid.UUID(state.thread_id)
        assert parsed.version == 4

    def test_thread_id_explicit_override(self) -> None:
        """显式传 thread_id 应被采用, 不再生成 UUID."""
        state = EngineState(thread_id="my-custom-thread-001")
        assert state.thread_id == "my-custom-thread-001"

    def test_majors_counters_default_zero_independent(self) -> None:
        """majors_in_a_row 和 total_majors 默认独立为 0."""
        state = EngineState()
        assert state.majors_in_a_row == 0
        assert state.total_majors == 0
        # 改变一个不影响另一个
        state.majors_in_a_row = 5
        assert state.total_majors == 0

    def test_batch_plan_type_is_list_of_dicts(self) -> None:
        """batch_plan 是 list[dict] (M1 修正, v2.5 错为 dict)."""
        state = EngineState()
        assert isinstance(state.batch_plan, list)

        # 验证可存放 dict 元素
        state.batch_plan = [{"task_id": "t1", "files": ["a.py"]}, {"task_id": "t2"}]
        assert state.batch_plan[0]["task_id"] == "t1"
        assert state.batch_plan[1]["task_id"] == "t2"

        # round-trip 保持 list 类型
        restored = EngineState.from_dict(state.to_dict())
        assert isinstance(restored.batch_plan, list)
        assert restored.batch_plan == state.batch_plan

    def test_list_factory_returns_independent_instances(self) -> None:
        """default_factory=list 确保每个实例的 list 字段是独立对象 (无 mutable default 共享)."""
        state1 = EngineState()
        state2 = EngineState()

        state1.file_list.append("a.py")
        state1.batch_plan.append({"x": 1})
        state1.findings.append({"severity": "info"})

        # state2 不应被影响
        assert state2.file_list == []
        assert state2.batch_plan == []
        assert state2.findings == []

    def test_dict_factory_returns_independent_instances(self) -> None:
        """default_factory=dict 确保每个实例的 dict 字段是独立对象."""
        state1 = EngineState()
        state2 = EngineState()

        state1.contracts["contract1"] = "spec"
        state1.test_results["test1"] = "pass"

        # state2 不应被影响
        assert state2.contracts == {}
        assert state2.test_results == {}


class TestEngineStateBoundary:
    """Phase 10: 字段边界值测试 (负数 / 极大 / 特殊值)."""

    def test_majors_negative_value_allowed_at_field_level(self) -> None:
        """dataclass 层面 majors 字段无验证, 接受任意 int.

        业务约束由 StageRouter 在运行时强制, 不在 dataclass 层.
        """
        state = EngineState()
        state.majors_in_a_row = -1  # 不抛
        state.total_majors = 999  # 不抛

        # to_dict / from_dict 保持
        restored = EngineState.from_dict(state.to_dict())
        assert restored.majors_in_a_row == -1
        assert restored.total_majors == 999

    def test_very_long_requirement_string(self) -> None:
        """requirement 字段支持任意长度字符串."""
        long_req = "x" * 10000
        state = EngineState(requirement=long_req)
        restored = EngineState.from_dict(state.to_dict())
        assert len(restored.requirement) == 10000

    def test_findings_with_nested_dicts(self) -> None:
        """findings 支持嵌套 dict 结构 (Critic 输出常见)."""
        findings = [
            {"severity": "high", "line": 42, "msg": "use of eval()", "file": "main.py"},
            {"severity": "low", "msg": "unused import"},
        ]
        state = EngineState(findings=findings)
        restored = EngineState.from_dict(state.to_dict())
        assert restored.findings == findings
        assert restored.findings[0]["line"] == 42

    def test_set_channels_with_unknown_field_silently_skipped(self) -> None:
        """set_channels 写入未知字段 → 静默跳过, 不抛."""
        state = EngineState()
        state.set_channels({"plan": "ok", "nonexistent": "should_be_dropped"})
        assert state.plan == "ok"
        assert not hasattr(state, "nonexistent")

    def test_to_dict_contains_all_17_fields(self) -> None:
        """to_dict 输出含全部 17 字段 (含 _pending_sends)."""
        state = EngineState()
        d = state.to_dict()
        assert len(d) == 16  # 16 dataclass 字段 (排除私有命名)
        # 实际: requirement, current_stage, thread_id, majors_in_a_row, total_majors,
        #       plan, file_list, batch_plan, contracts,
        #       files_changed, commit_hash, test_results,
        #       verdict, findings, critic_feedback,
        #       _pending_sends
        assert "_pending_sends" in d
        assert d["thread_id"] == state.thread_id

    def test_from_dict_with_empty_dict_uses_all_defaults(self) -> None:
        """from_dict({}) → 使用全部默认值."""
        state = EngineState.from_dict({})
        # thread_id 应被新生成 (factory)
        assert isinstance(state.thread_id, str) and len(state.thread_id) == 36
        # 其他字段默认值
        assert state.requirement == ""
        assert state.current_stage == ""
        assert state.majors_in_a_row == 0
        assert state.file_list == []


class TestEngineStateEquality:
    """Phase 10: EngineState == 比较 + 哈希行为."""

    def test_two_empty_states_not_equal_due_to_thread_id(self) -> None:
        """两个空 EngineState 不相等 (thread_id 唯一).

        业务含义: 每个 EngineState 实例代表一次 thread, 不应被混用.
        """
        s1 = EngineState()
        s2 = EngineState()
        assert s1 != s2, "空状态仍因 thread_id 唯一而不相等"

    def test_copied_state_with_same_thread_id_is_equal(self) -> None:
        """同 thread_id + 同字段 → 相等."""
        from copy import deepcopy

        s1 = EngineState(requirement="x", plan="p", file_list=["a.py"])
        # 强制同 thread_id
        s2 = EngineState(
            thread_id=s1.thread_id, requirement="x", plan="p", file_list=["a.py"]
        )
        assert s1 == s2

    def test_state_is_not_hashable(self) -> None:
        """EngineState 含 list 字段 → 不可 hash (unhashable)."""
        state = EngineState()
        with pytest.raises(TypeError, match="unhashable"):
            hash(state)

