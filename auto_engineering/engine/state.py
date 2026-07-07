"""EngineState — Stage 之间通过 channel 共享的状态对象 (P1-B 重命名).

原名 LoopState 改为 EngineState 以避免与 v2.0 loop.state.CheckpointEnvelope 同名冲突.
旧名 LoopState 保留为 type alias, 向后兼容.

参考 LangGraph StateGraph state_schema(简化: 单一 dataclass,无 channel 类型/reducer).
P0 修复: dataclass 默认 factory 不可 JSON 序列化 → to_dict/from_dict 用 asdict.
v5.0 M1: 扩展到 17 字段. v5.1: +suggested_fix 替代 round → 保持 17 字段.
"""

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _new_thread_id() -> str:
    """生成 UUID v4 字符串作为默认 thread_id.

    v5.0 §B1.1 字段 15: thread_id 自动生成, 构造时不显式传则用 UUID v4.
    """
    return str(uuid.uuid4())


@dataclass
class EngineState:
    """开发循环共享状态. Architect/Developer/Critic 各自写入对应 channel,
    下一 Stage 通过 input_channels 读取.

    Channel 分类 (v5.0 §B1.1 字段表):
        输入(用户/前置)     requirement
        控制                current_stage, thread_id, majors_in_a_row, total_majors
        Architect 输出      plan, file_list, batch_plan, contracts
        Developer 输出      files_changed, commit_hash, test_results
        Critic 输出         verdict, findings, critic_feedback
        多 Agent 预留       _pending_sends (v2.0+ PUSH 消费)

    Note (P1-B): 旧名 LoopState 是 EngineState 的 alias, 保持向后兼容.
        新代码推荐 import EngineState.

    Note (v5.5): 18 字段 — round 字段持久化到 EngineState (v5.5 audit P0-4).
    硬上限由 ConvergenceJudge._check_hard_limit 检查.
    """

    requirement: str = ""
    current_stage: str = ""
    round: int = 0  # v5.5 audit P0-4: round 计数器持久化到 EngineState, ae status 消费

    # 控制 (v5.0 §B1.1 字段 15-17: thread_id / majors_in_a_row / total_majors)
    thread_id: str = field(default_factory=_new_thread_id)
    majors_in_a_row: int = 0
    total_majors: int = 0

    # Architect 输出
    plan: str = ""
    file_list: list[str] = field(default_factory=list)
    batch_plan: list[dict[str, Any]] = field(default_factory=list)
    contracts: dict[str, Any] = field(default_factory=dict)

    # Developer 输出
    files_changed: list[str] = field(default_factory=list)
    commit_hash: str = ""
    test_results: dict[str, Any] = field(default_factory=dict)

    # Critic 输出
    verdict: str = ""  # "APPROVE" | "MAJOR"
    findings: list[dict[str, Any]] = field(default_factory=list)
    critic_feedback: str = ""
    # 2026-07-04 (Self-Refine 原则 1 深化): 结构化修复建议
    # critic 直接输出 unified diff patch (具体代码片段而非文字), developer
    # 重做时直接拿到 patch 应用, 不重新解读. Self-Refine 论文表明效果 2-3x.
    suggested_fix: str = ""

    # v5.5 Phase 2: DeepAudit + PLAN-REFINE 字段 (B1.1 字段 18-19)
    audit_findings: list[dict[str, Any]] | None = None
    # 格式: [{severity:P0|P1|P2, dimension, file, line, description,
    #         evidence, suggested_fix, agent_source}]
    # 写入者: Orchestrator._step_2j (DeepAudit 后)
    # 消费: ArchitectAgent PLAN-REFINE MODE (B4.1a)
    # 重置: DeepAudit pass (T4) 时设为 None

    plan_refine_count: int = 0
    # 只计 T9 回路次数, 不与 MAJOR 计数混淆
    # 写入者: Orchestrator._step_2k (T9 触发时 ++)
    # 重置: DeepAudit pass (T4) 时归零

    # v5.5 CriticOutput 扩展字段
    strengths: list[str] | None = None
    assessment: str | None = None

    # 多 Agent 预留(v2.0+ Send 动态路由)
    _pending_sends: list = field(default_factory=list)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """v5.4 审计 P1-13: 提供 Pydantic 兼容的序列化 API.

        serialize_state 优先检查 model_dump → 统一序列化入口。
        内部委托给 asdict (dataclass → dict 递归转换).
        """
        return asdict(self)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict (向后兼容, 委托给 model_dump)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineState":
        """从 dict 重建. 忽略未知字段(防御性,处理 schema 演进)."""
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    def get_channels(self, names: list[str]) -> dict[str, Any]:
        """读取指定 channel 值,传给 Agent 作为上下文.

        缺失的 channel 静默跳过(hasattr 守卫). 不抛 KeyError.
        """
        return {n: getattr(self, n) for n in names if hasattr(self, n)}

    def set_channels(self, writes: dict[str, Any]) -> None:
        """批量写入 channel. 缺失的 channel 静默跳过,防御性."""
        for k, v in writes.items():
            if hasattr(self, k):
                setattr(self, k, v)


# P1-B: 向后兼容 alias. 旧代码 `from auto_engineering.engine.state import LoopState` 仍可用.
LoopState = EngineState
