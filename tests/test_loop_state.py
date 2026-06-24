"""LoopState 序列化往返 + 未知字段丢弃 + channels 读写."""

import json

import pytest

from auto_engineering.engine.state import LoopState


def test_state_to_dict_包含全部_dataclass_字段():
    state = LoopState(requirement="req", plan="p", file_list=["a.py"])
    d = state.to_dict()

    # 全部字段(包括私有 _pending_sends)都被 asdict 序列化
    assert d["requirement"] == "req"
    assert d["plan"] == "p"
    assert d["file_list"] == ["a.py"]
    assert d["commit_hash"] == ""
    assert d["verdict"] == ""
    assert d["_pending_sends"] == []


def test_state_from_dict_忽略未知字段():
    # 防御性: 旧 checkpoint 包含 schema 演进前的字段时,from_dict 不抛
    state = LoopState.from_dict({"requirement": "x", "unknown_field": "drop_me"})
    assert state.requirement == "x"
    assert not hasattr(state, "unknown_field")


def test_state_json_roundtrip_保留所有_字段():
    original = LoopState(
        requirement="实现用户登录",
        plan="用 JWT",
        file_list=["auth.py", "test_auth.py"],
        commit_hash="abc123",
        verdict="APPROVE",
        findings=[{"severity": "P0", "issue": "test"}],
        critic_feedback="",
    )

    j = json.dumps(original.to_dict(), ensure_ascii=False)
    restored = LoopState.from_dict(json.loads(j))

    assert restored.requirement == original.requirement
    assert restored.plan == original.plan
    assert restored.file_list == original.file_list
    assert restored.commit_hash == original.commit_hash
    assert restored.verdict == original.verdict
    assert restored.findings == original.findings


def test_state_get_channels_缺失字段静默跳过():
    state = LoopState(plan="p")
    ch = state.get_channels(["plan", "nonexistent"])
    assert ch == {"plan": "p"}


def test_state_set_channels_未知字段静默丢弃():
    state = LoopState()
    state.set_channels({"verdict": "APPROVE", "unknown_field": "drop_me"})
    assert state.verdict == "APPROVE"
    assert not hasattr(state, "unknown_field")


def test_state_pending_sends_默认空列表_v1_0_不实现_PUSH():
    state = LoopState()
    assert state._pending_sends == []
    # v1.0 不消费 _pending_sends,确认它是普通字段,不是 None
    state._pending_sends.append({"node": "x", "arg": {}})
    assert state._pending_sends == [{"node": "x", "arg": {}}]
