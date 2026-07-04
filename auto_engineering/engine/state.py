"""EngineState — Stage 之间通过 channel 共享的状态对象 (P1-B 重命名).

原名 LoopState 改为 EngineState 以避免与 v2.0 loop.state.CheckpointEnvelope 同名冲突.
旧名 LoopState 保留为 type alias, 向后兼容.

参考 LangGraph StateGraph state_schema(简化: 单一 dataclass,无 channel 类型/reducer).
P0 修复: dataclass 默认 factory 不可 JSON 序列化 → to_dict/from_dict 用 asdict.
v5.0 M1: 扩展到 17 字段(+batch_plan as list[dict] / +majors_in_a_row / +total_majors / +thread_id).
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

    Note (v5.0 M1): 字段总数从 13 → 17. 新增字段含义:
        - batch_plan: list[dict] (architect 产出, v5.0 §B1.1 字段 6)
        - majors_in_a_row: int (连续 MAJOR 计数, §B1.1 字段 16)
        - total_majors: int (累计 MAJOR 计数, §B1.1 字段 17)
        - thread_id: str (UUID v4, §B1.1 字段 15)
    """

    requirement: str = ""
    current_stage: str = ""

    # 控制 (v5.0 §B1.1 字段 15-17: thread_id / majors_in_a_row / total_majors)
    thread_id: str = field(default_factory=_new_thread_id)
    majors_in_a_row: int = 0
    total_majors: int = 0

    # Architect 输出
    plan: str = ""
    file_list: list[str] = field(default_factory=list)
    batch_plan: list[dict] = field(default_factory=list)  # M1 修正: v2.5 是 dict (错), 应为 list[dict]
    contracts: dict = field(default_factory=dict)

    # Developer 输出
    files_changed: list[str] = field(default_factory=list)
    commit_hash: str = ""
    test_results: dict = field(default_factory=dict)

    # Critic 输出
    verdict: str = ""  # "APPROVE" | "MAJOR"
    findings: list[dict] = field(default_factory=list)
    critic_feedback: str = ""
    # 2026-07-04 (Self-Refine 原则 1 深化): 结构化修复建议
    # critic 直接输出 unified diff patch (具体代码片段而非文字), developer
    # 重做时直接拿到 patch 应用, 不重新解读. Self-Refine 论文表明效果 2-3x.
    suggested_fix: str = ""

    # 多 Agent 预留(v2.0+ Send 动态路由)
    _pending_sends: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict. Checkpoint 用此方法写入 SQLite state_json."""
        return asdict(self)

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
