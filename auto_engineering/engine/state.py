"""EngineState — Stage 之间通过 channel 共享的状态对象 (P1-B 重命名).

原名 LoopState 改为 EngineState 以避免与 v2.0 loop.state.CheckpointEnvelope 同名冲突.
旧名 LoopState 保留为 type alias, 向后兼容.

参考 LangGraph StateGraph state_schema(简化: 单一 dataclass,无 channel 类型/reducer).
P0 修复: dataclass 默认 factory 不可 JSON 序列化 → to_dict/from_dict 用 asdict.
v5.0 M1: 扩展到 17 字段. v5.1: +suggested_fix 替代 round → 保持 17 字段.

v5.5 P1-5: 写入控制 — 字段级写所有权 + write_field() 验证 + _write_log 审计追踪.
为未来多 Agent 并发写同一 EngineState 打基础 (当前按 role 天然 partition, 无共享写).
"""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, TypedDict


# ============================================================
# v5.5 audit P2-17: TypedDict 替代 dict[str, Any] (类型安全)
# ============================================================


class BatchPlanItem(TypedDict, total=False):
    """Architect 产出的单个 batch plan 条目."""
    task_id: str
    description: str
    expected_output: str
    input_channels: list[str]
    output_channels: list[str]


class CriticFinding(TypedDict, total=False):
    """Critic 产出的单个代码审查发现."""
    severity: str  # P0 | P1 | P2
    file: str
    line: int
    description: str
    suggested_fix: str


class AuditFinding(TypedDict, total=False):
    """DeepAuditGate 产出的单个审计发现."""
    severity: str  # P0 | P1 | P2
    dimension: str
    file: str
    line: int
    description: str
    evidence: str
    suggested_fix: str
    agent_source: str


class TestResults(TypedDict, total=False):
    """TestGate 产出的测试结果摘要."""
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration: float
    exit_code: int


class WriteRecord(TypedDict, total=False):
    """单次字段写入记录 (v5.5 P1-5)."""
    field: str
    writer: str       # agent role or "orchestrator" / "stage_router" / "user"
    timestamp: str    # ISO 8601 UTC


# ============================================================
# 写所有权表 (v5.5 P1-5)
# ============================================================
# 每个字段有唯一写入者, 当前按 agent role 天然 partition:
#
#   user:          requirement
#   auto:          thread_id (UUID on init)
#   architect:     plan, file_list, batch_plan, contracts
#   developer:     files_changed, commit_hash, test_results
#   critic:        verdict, findings, critic_feedback, suggested_fix, strengths, assessment
#   orchestrator:  current_stage, round, audit_findings, plan_refine_count
#   stage_router:  majors_in_a_row, total_majors
#
# 未来多 Agent 并发时, 此表用于:
#   1. 检测跨 role 写入冲突 (同一字段被多个 writer 写入)
#   2. 按 writer 分区加 asyncio.Lock (每 writer 一个锁)
#   3. _write_log 提供审计追踪 (谁在何时写了什么)

# 字段 → 合法 writer(s)
_WRITE_OWNERS: dict[str, frozenset[str]] = {
    "requirement":       frozenset({"user", "orchestrator"}),
    "current_stage":     frozenset({"orchestrator", "stage_router"}),
    "round":             frozenset({"orchestrator"}),
    "thread_id":         frozenset({"auto"}),
    "majors_in_a_row":   frozenset({"stage_router"}),
    "total_majors":      frozenset({"stage_router"}),
    "plan":              frozenset({"architect", "orchestrator"}),
    "file_list":         frozenset({"architect"}),
    "batch_plan":        frozenset({"architect"}),
    "contracts":         frozenset({"architect"}),
    "files_changed":     frozenset({"developer"}),
    "commit_hash":       frozenset({"developer"}),
    "test_results":      frozenset({"developer", "orchestrator"}),
    "verdict":           frozenset({"critic", "orchestrator"}),
    "findings":          frozenset({"critic"}),
    "critic_feedback":   frozenset({"critic", "orchestrator"}),
    "suggested_fix":     frozenset({"critic"}),
    "audit_findings":    frozenset({"orchestrator"}),
    "plan_refine_count": frozenset({"orchestrator"}),
    "strengths":         frozenset({"critic"}),
    "assessment":        frozenset({"critic"}),
}

# 合法 verdict 值
_VALID_VERDICTS = frozenset({"", "APPROVE", "MAJOR"})

# 合法 stage 值
_VALID_STAGES = frozenset({"", "architect", "developer", "critic", "plan_refine"})


def _new_thread_id() -> str:
    """生成 UUID v4 字符串作为默认 thread_id.

    v5.0 §B1.1 字段 15: thread_id 自动生成, 构造时不显式传则用 UUID v4.
    """
    return str(uuid.uuid4())


@dataclass
class EngineState:
    """开发循环共享状态. Architect/Developer/Critic 各自写入对应 channel,
    下一 Stage 通过 input_channels 读取.

    Write ownership (v5.5 P1-5):
        user:          requirement
        auto:          thread_id (UUID on init)
        architect:     plan, file_list, batch_plan, contracts
        developer:     files_changed, commit_hash, test_results
        critic:        verdict, findings, critic_feedback, suggested_fix, strengths, assessment
        orchestrator:  current_stage, round, audit_findings, plan_refine_count
        stage_router:  majors_in_a_row, total_majors

    硬上限由 ConvergenceJudge._check_hard_limit 检查.

    Note (P1-B): 旧名 LoopState 是 EngineState 的 alias, 保持向后兼容.
        新代码推荐 import EngineState.
    """

    requirement: str = ""
    current_stage: str = ""
    round: int = 0

    # 控制 (v5.0 §B1.1 字段 15-17: thread_id / majors_in_a_row / total_majors)
    thread_id: str = field(default_factory=_new_thread_id)
    majors_in_a_row: int = 0
    total_majors: int = 0

    # Architect 输出
    plan: str = ""
    file_list: list[str] = field(default_factory=list)
    batch_plan: list[BatchPlanItem] = field(default_factory=list)
    contracts: dict[str, Any] = field(default_factory=dict)

    # Developer 输出
    files_changed: list[str] = field(default_factory=list)
    commit_hash: str = ""
    test_results: TestResults = field(default_factory=dict)

    # Critic 输出
    verdict: str = ""  # "APPROVE" | "MAJOR"
    findings: list[CriticFinding] = field(default_factory=list)
    critic_feedback: str = ""
    suggested_fix: str = ""

    # v5.5 Phase 2: DeepAudit + PLAN-REFINE 字段
    audit_findings: list[AuditFinding] | None = None
    plan_refine_count: int = 0

    # v5.5 CriticOutput 扩展字段
    strengths: list[str] | None = None
    assessment: str | None = None

    # v5.5 P1-5: 写入审计日志 (repr=False 避免污染输出, 不参与序列化)
    _write_log: list[WriteRecord] = field(default_factory=list, repr=False, init=False)

    # ============================================================
    # v5.5 P1-5: 写入控制 API
    # ============================================================

    def write_field(self, name: str, value: Any, writer: str) -> None:
        """写入单个字段, 带所有权校验 + 审计日志.

        Args:
            name: 字段名 (必须存在于 EngineState).
            value: 新值.
            writer: 写入者标识 (architect/developer/critic/orchestrator/stage_router/user).

        Raises:
            ValueError: 字段不存在, writer 无权写入, 或值不合法.
        """
        if not hasattr(self, name):
            raise ValueError(
                f"EngineState 无字段 '{name}'. 可用: "
                f"{[f.name for f in self.__dataclass_fields__.values()]}"
            )

        # 所有权校验
        allowed = _WRITE_OWNERS.get(name)
        if allowed is not None and writer not in allowed:
            raise ValueError(
                f"'{writer}' 无权写入 '{name}'. "
                f"合法写入者: {sorted(allowed)}"
            )

        # 值校验
        _validate_field_value(name, value)

        # 写入 + 日志
        setattr(self, name, value)
        self._write_log.append(WriteRecord(
            field=name,
            writer=writer,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))

    def get_write_log(self, field_name: str | None = None) -> list[WriteRecord]:
        """读取写入日志, 可按字段名过滤.

        Args:
            field_name: 过滤字段名 (None = 全部).

        Returns:
            list[WriteRecord]: 按时间排序的写入记录.
        """
        if field_name is None:
            return list(self._write_log)
        return [r for r in self._write_log if r.get("field") == field_name]

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """v5.4 审计 P1-13: 提供 Pydantic 兼容的序列化 API.

        serialize_state 优先检查 model_dump → 统一序列化入口。
        内部委托给 asdict (dataclass → dict 递归转换).
        排除 _write_log (内部审计字段, 不参与序列化).
        """
        result = asdict(self)
        result.pop("_write_log", None)
        return result

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict (向后兼容, 委托给 model_dump)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineState":
        """从 dict 重建. 忽略未知字段(防御性,处理 schema 演进)."""
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        # 排除内部字段
        field_names.discard("_write_log")
        return cls(**{k: v for k, v in data.items() if k in field_names})

    def get_channels(self, names: list[str]) -> dict[str, Any]:
        """读取指定 channel 值,传给 Agent 作为上下文.

        缺失的 channel 会记录 WARNING 日志.
        """
        import logging
        _logger = logging.getLogger("ae.engine.state")
        result = {}
        for n in names:
            if hasattr(self, n):
                result[n] = getattr(self, n)
            else:
                _logger.warning("get_channels: unknown channel '%s'", n)
        return result

    def set_channels(self, writes: dict[str, Any], writer: str = "orchestrator") -> None:
        """批量写入 channel, 做审计日志但不强制所有权校验 (向后兼容).

        旧 API, 所有权不严格 — 新代码应使用 write_field().

        Args:
            writes: {field_name: value} 映射.
            writer: 写入者标识 (默认 orchestrator).
        """
        import logging
        _logger = logging.getLogger("ae.engine.state")
        for k, v in writes.items():
            if not hasattr(self, k):
                _logger.warning("set_channels: unknown channel '%s', skipped", k)
                continue
            _validate_field_value(k, v)
            setattr(self, k, v)
            self._write_log.append(WriteRecord(
                field=k,
                writer=writer,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))


def _validate_field_value(name: str, value: Any) -> None:
    """字段值合法性校验 (v5.5 P1-5).

    Raises:
        ValueError: 值不合法.
    """
    if name == "verdict" and value not in _VALID_VERDICTS:
        raise ValueError(
            f"verdict 非法值 '{value}'. 合法值: {sorted(_VALID_VERDICTS)}"
        )
    if name == "current_stage" and value not in _VALID_STAGES:
        raise ValueError(
            f"current_stage 非法值 '{value}'. 合法值: {sorted(_VALID_STAGES)}"
        )
    if name == "round" and not isinstance(value, int):
        raise ValueError(f"round 必须是 int, 收到 {type(value).__name__}")
    if name in ("majors_in_a_row", "total_majors", "plan_refine_count"):
        if not isinstance(value, int):
            raise ValueError(f"{name} 必须是 int, 收到 {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} 不能为负数, 收到 {value}")


# P1-B: 向后兼容 alias. 旧代码 `from auto_engineering.engine.state import LoopState` 仍可用.
LoopState = EngineState
