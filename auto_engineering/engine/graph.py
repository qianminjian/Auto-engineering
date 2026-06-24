"""StageGraph — 借鉴 LangGraph StateGraph(简化: 无 channel 类型/reducer/managed value).

核心类:
    Stage        — 单个执行节点(类比 LangGraph PregelNode)
    ConditionSpec — 条件边规约
    StageGraph   — builder + next_stage 调度

v3.0 §3.1 bug 修复: render_description 遇空字符串值时整行删除,
    避免 developer 模板 "上一轮审查反馈: {critic_feedback}" 首轮渲染产生空行.
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from auto_engineering.errors import AEError, ErrorCode
from auto_engineering.engine.state import LoopState


@dataclass
class Stage:
    """单个 Stage 节点. 类比 CrewAI Task 富模型 + LangGraph PregelNode.

    关键字段:
        description_template — 使用 {var} Python 风格占位符,非 Jinja2(避免 LLM 输出 {} 误解析)
        expected_output     — CrewAI 风格: Agent 知道"产出应该长什么样"
        output_schema       — JSON Schema 约束 LLM 输出结构(Phase 2+ 使用)
        input_channels      — 从 state 读哪些 channel
        output_channels     — 写哪些 channel 到 state(按顺序与 Agent 输出对齐)
        retry_policy        — per-Stage 重试策略(Phase 4+ 使用,Phase 1 留 None)
    """

    name: str
    agent_type: str
    description_template: str
    expected_output: str
    output_schema: dict | None = None
    tools: list[str] = field(default_factory=list)
    input_channels: list[str] = field(default_factory=list)
    output_channels: list[str] = field(default_factory=list)
    retry_policy: Any = None  # RetryPolicy dataclass (Phase 4+ 引入)

    def render_description(self, state: LoopState) -> str:
        """用 state 的 channel 值渲染描述模板.

        策略:
            1. 遍历 input_channels
            2. 对每个 channel,值非空 → str.replace 替换占位符
            3. v3.0 §3.1 修复: 值是空字符串/None/空容器 → 整行删除(避免空行干扰 LLM)

        Why 整行删除而非保留字面量:
            保留 "{critic_feedback}" 在 LLM 输入里会让模型困惑(看起来像未填充的占位符).
            删除整行后,首轮无反馈时模板自然收尾,二轮有反馈时正常展开.
        """
        result = self.description_template
        channels = state.get_channels(self.input_channels)
        for key, value in channels.items():
            placeholder = "{" + key + "}"
            if value is None or value == "" or value == [] or value == {}:
                # 空值:删除包含此 placeholder 的整行
                result = "\n".join(
                    line for line in result.split("\n")
                    if placeholder not in line
                )
            else:
                result = result.replace(placeholder, str(value))
        return result


@dataclass
class ConditionSpec:
    """条件边规约. 类比 LangGraph BranchSpec(简化: 单一 condition 函数)."""

    condition: Callable[[LoopState], str]  # 返回 path_map 的 key
    path_map: dict[str, str]                # key → Stage name 或 END


class StageGraph:
    """builder 链式 API + next_stage 调度.

    LangGraph 风格 START sentinel — 用 set_start() 替代 START → first_node 边.
    """

    START = "__start__"
    END = "__end__"

    def __init__(self):
        self.stages: dict[str, Stage] = {}
        self.edges: dict[str, str] = {}                        # 固定边
        self.conditional_edges: dict[str, ConditionSpec] = {}  # 条件边
        self._start_stage: str | None = None

    def set_start(self, stage_name: str) -> "StageGraph":
        """设置入口 Stage. 替代 LangGraph 的 START → first_node 边."""
        if stage_name not in self.stages:
            raise ValueError(f"Start stage '{stage_name}' not registered")
        self._start_stage = stage_name
        return self

    def add_stage(self, stage: Stage) -> "StageGraph":
        self.stages[stage.name] = stage
        return self

    def add_edge(self, from_stage: str, to_stage: str) -> "StageGraph":
        """固定边: from → to. to 可为 END."""
        self.edges[from_stage] = to_stage
        return self

    def add_conditional_edge(
        self,
        from_stage: str,
        condition: Callable[[LoopState], str],
        path_map: dict,
    ) -> "StageGraph":
        """条件边: condition(state) 返回 key,path_map[key] 是目标 Stage 或 END."""
        self.conditional_edges[from_stage] = ConditionSpec(condition, path_map)
        return self

    def next_stage(self, state: LoopState) -> Stage | None:
        """决定下一步执行哪个 Stage. 返回 None 表示终止.

        顺序:
            1. 首次调用(current_stage=""): 返回 set_start() 指定的入口
            2. 否则先查条件边(优先级最高)
            3. 再查固定边
            4. 都没有 → 返回 None(done)
        """
        current = state.current_stage

        # 首 Stage
        if not current:
            if self._start_stage:
                return self.stages[self._start_stage]
            raise AEError(
                ErrorCode.GRAPH_RECURSION_LIMIT,
                "No start stage set. Call graph.set_start('stage_name').",
            )

        # 条件边
        if cond := self.conditional_edges.get(current):
            decision = cond.condition(state)
            next_name = cond.path_map.get(decision)
            if next_name is None or next_name == self.END:
                return None
            if next_name not in self.stages:
                raise ValueError(f"条件边指向未知 Stage: {next_name}")
            return self.stages[next_name]

        # 固定边
        if next_name := self.edges.get(current):
            if next_name == self.END:
                return None
            return self.stages[next_name]

        return None


def _critic_decision(state: LoopState) -> str:
    """Critic 条件边判定: 返回 verdict 字符串作为 path_map 的 key."""
    return state.verdict


def build_dev_loop_graph() -> StageGraph:
    """开发循环图: architect → developer → critic → (APPROVE→END | MAJOR→developer).

    三个 Stage 的 input/output channels 与 v3.0 §2.2 LoopState 字段对齐.

    v3.1 D1 修复(f4f9b9c): 显式注册 add_edge('developer', 'critic').
    原 v3.0 设计漏此边,导致 next_stage() 在 developer 后查不到固定边 → 返回 None
    → 循环在 developer 后立即 done,critic 永远不被调度.
    """
    g = StageGraph()

    g.add_stage(Stage(
        name="architect",
        agent_type="architect",
        description_template="分析需求: {requirement}",
        expected_output="实现计划 (plan.md),含文件清单、分批策略、契约定义",
        output_schema={
            "type": "object",
            "properties": {
                "plan": {"type": "string"},
                "file_list": {"type": "array", "items": {"type": "string"}},
                "batch_plan": {"type": "array"},
                "contracts": {"type": "object"},
            },
            "required": ["plan", "file_list"],
        },
        tools=["read_file", "search_code", "list_dir"],
        input_channels=["requirement"],
        output_channels=["plan", "file_list", "batch_plan", "contracts"],
    ))

    g.add_stage(Stage(
        name="developer",
        agent_type="developer",
        description_template=(
            "按计划实现: {plan}\n"
            "上一轮审查反馈: {critic_feedback}"
        ),
        expected_output="代码变更 + 测试通过 + git commit",
        output_schema={
            "type": "object",
            "properties": {
                "files_changed": {"type": "array", "items": {"type": "string"}},
                "commit_hash": {"type": "string"},
                "test_results": {"type": "object"},
            },
            "required": ["files_changed", "commit_hash"],
        },
        tools=["read_file", "write_file", "edit_file", "run_bash", "git_commit"],
        input_channels=["plan", "batch_plan", "critic_feedback"],
        output_channels=["files_changed", "commit_hash", "test_results"],
    ))

    g.add_stage(Stage(
        name="critic",
        agent_type="critic",
        description_template=(
            "审查 commit {commit_hash} 的变更。"
            "对照验收标准: {contracts}"
        ),
        expected_output="审查结论 APPROVE 或 MAJOR(含具体问题清单和修复建议)",
        output_schema={
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["APPROVE", "MAJOR"]},
                "findings": {"type": "array"},
                "critic_feedback": {"type": "string"},
            },
            "required": ["verdict", "findings"],
        },
        tools=["read_file", "git_diff", "run_tests"],
        input_channels=["files_changed", "commit_hash", "plan", "contracts"],
        output_channels=["verdict", "findings", "critic_feedback"],
    ))

    g.add_edge("architect", "developer")
    g.add_edge("developer", "critic")
    g.add_conditional_edge("critic", _critic_decision, {
        "APPROVE": g.END,
        "MAJOR": "developer",
    })
    g.set_start("architect")

    return g
