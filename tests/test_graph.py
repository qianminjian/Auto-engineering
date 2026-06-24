"""StageGraph 调度 + Stage.render_description(v3.0 §3.1 bug 修复)."""

import pytest

from auto_engineering.engine.graph import (
    Stage,
    StageGraph,
    _critic_decision,
    build_dev_loop_graph,
)
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode


# ----- Stage.render_description (v3.0 §3.1 修复验证) -----

def test_render_description_普通替换_无空值():
    stage = Stage(
        name="dev",
        agent_type="dev",
        description_template="Plan: {plan}\nFeedback: {critic_feedback}",
        expected_output="code",
        input_channels=["plan", "critic_feedback"],
    )
    state = LoopState(plan="do X", critic_feedback="fix bug Y")
    result = stage.render_description(state)
    assert "Plan: do X" in result
    assert "Feedback: fix bug Y" in result


def test_render_description_空字符串整行删除_首次_critic_feedback():
    """v3.0 §3.1 bug 修复: 空字符串值时,包含 placeholder 的整行被删除,
    避免 LLM 看到 '上一轮审查反馈: \n' 产生空行干扰."""
    stage = Stage(
        name="dev",
        agent_type="dev",
        description_template=(
            "按计划实现: {plan}\n"
            "上一轮审查反馈: {critic_feedback}"
        ),
        expected_output="code",
        input_channels=["plan", "critic_feedback"],
    )
    state = LoopState(plan="plan content", critic_feedback="")
    result = stage.render_description(state)

    # 保留 plan 行
    assert "按计划实现: plan content" in result
    # 整行删除
    assert "{critic_feedback}" not in result
    assert "上一轮审查反馈:" not in result
    # 不留尾随空行
    assert not result.endswith("\n")


def test_render_description_空_列表和_dict_也触发整行删除():
    stage = Stage(
        name="dev",
        agent_type="dev",
        description_template="Files: {file_list}\nDone",
        expected_output="code",
        input_channels=["file_list"],
    )
    state = LoopState(file_list=[])
    result = stage.render_description(state)
    assert "Files:" not in result
    assert "Done" in result


def test_render_description_缺失_channel_静默跳过():
    stage = Stage(
        name="dev",
        agent_type="dev",
        description_template="Plan: {plan}",
        expected_output="code",
        input_channels=["plan", "nonexistent"],
    )
    state = LoopState(plan="p")
    # 不抛 KeyError
    result = stage.render_description(state)
    assert "Plan: p" in result


# ----- StageGraph.next_stage 路径分支 -----

def test_next_stage_首次返回入口_Stage():
    graph = build_dev_loop_graph()
    state = LoopState()
    next_s = graph.next_stage(state)
    assert next_s.name == "architect"


def test_next_stage_未调用_set_start_抛_GRAPH_RECURSION_LIMIT():
    g = StageGraph()
    g.add_stage(Stage(name="a", agent_type="a", description_template="x", expected_output="y"))
    with pytest.raises(AEError) as exc_info:
        g.next_stage(LoopState())
    assert exc_info.value.code == ErrorCode.GRAPH_RECURSION_LIMIT


def test_next_stage_固定边_architect_to_developer():
    state = LoopState(current_stage="architect")
    next_s = build_dev_loop_graph().next_stage(state)
    assert next_s.name == "developer"


def test_next_stage_固定边_developer_to_critic():
    """v3.0 §三 修复: developer → critic 边存在,critic 才会被调度."""
    state = LoopState(current_stage="developer")
    next_s = build_dev_loop_graph().next_stage(state)
    assert next_s.name == "critic"


def test_next_stage_条件边_APPROVE_返回_NONE_END():
    state = LoopState(current_stage="critic", verdict="APPROVE")
    next_s = build_dev_loop_graph().next_stage(state)
    assert next_s is None  # END


def test_next_stage_条件边_MAJOR_返回_developer():
    state = LoopState(current_stage="critic", verdict="MAJOR")
    next_s = build_dev_loop_graph().next_stage(state)
    assert next_s.name == "developer"


def test_next_stage_未知_verdict_返回_NONE():
    """path_map 查不到 decision 时返回 None(done 而非抛错,防御性)."""
    state = LoopState(current_stage="critic", verdict="UNKNOWN")
    next_s = build_dev_loop_graph().next_stage(state)
    assert next_s is None


def test_critic_decision_helper_返回_verdict():
    state = LoopState(verdict="MAJOR")
    assert _critic_decision(state) == "MAJOR"


# ----- builder 链式 API -----

def test_builder_链式返回_self_支持链式调用():
    g = StageGraph()
    s = Stage(name="a", agent_type="a", description_template="x", expected_output="y")
    result = g.add_stage(s).add_edge("a", "b").set_start("a")
    assert result is g
