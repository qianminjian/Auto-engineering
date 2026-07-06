"""v2.0 4 级收敛判定.

设计来源: design/v2.0-Analysis-Loop.md §4.7

4 级判定(从硬到软):
1. 硬上限 (level=4): max_iterations 达到 → 立即停止
2. 质量门 (level=3): 6 道 Gate 全 PASS → 停止
3. 停滞检测 (level=2): N 轮产出无实质变化 → 停止
4. 语义收敛 (level=1): LLM 评估"本轮产出满足需求" → 停止
0. 继续 (level=0): 默认, 未触发任何停止条件

API:
    judge = ConvergenceJudge(config)
    verdict = judge.evaluate(history)
    if verdict.should_stop: ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from auto_engineering.gates.base import GateVerdict

# ============================================================
# 常量: 4 级收敛 + 默认继续
# ============================================================

# 默认配置参数
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_STAGNATION_THRESHOLD = 2  # 连续 N 轮无变化
DEFAULT_STAGNATION_DIFF_RATIO = 0.05  # diff 变化率 < 5% 视为无变化

# Verdict level 语义
LEVEL_CONTINUE = 0  # 继续
LEVEL_SEMANTIC = 1  # 语义收敛 (LLM 评估通过)
LEVEL_STAGNANT = 2  # 停滞检测触发
LEVEL_QUALITY = 3  # 质量门全通过
LEVEL_HARD_LIMIT = 4  # 硬上限触发

LEVEL_NAMES = {
    LEVEL_CONTINUE: "CONTINUE",
    LEVEL_SEMANTIC: "GOAL_ACHIEVED",
    LEVEL_STAGNANT: "STAGNANT",
    LEVEL_QUALITY: "QUALITY_PASS",
    LEVEL_HARD_LIMIT: "MAX_ITERATIONS",
}


@dataclass
class ConvergenceConfig:
    """收敛判定配置参数.

    Attributes:
        max_iterations: 单会话最大迭代轮次 (硬上限)
        stagnation_threshold: 连续多少轮无实质变化触发停滞检测
        stagnation_diff_ratio: diff 变化率阈值 (低于此值视为无变化)
        auto_tune: v5.5 — 启用 max_iter 自动学习 (default False)
        max_plan_refines: v5.5 — T9 回路最大次数 (default 3)
        min_samples_for_learning: v5.5 — 冷启动最小样本数 (default 5)
    """

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    stagnation_threshold: int = DEFAULT_STAGNATION_THRESHOLD
    stagnation_diff_ratio: float = DEFAULT_STAGNATION_DIFF_RATIO
    auto_tune: bool = False             # v5.5: 启用 max_iter 自动学习
    max_plan_refines: int = 3           # v5.5: T9 回路最大次数
    min_samples_for_learning: int = 5   # v5.5: 冷启动最小样本数


@dataclass
class RoundHistory:
    """单轮历史记录.

    用于停滞检测算法: 计算与上一轮的 diff 变化率.

    Attributes:
        round_id: 轮次 ID (1-indexed)
        files_changed: 本轮修改的文件数
        lines_added: 本轮新增行数
        lines_removed: 本轮删除行数
        gate_results: v2.3 Phase D (P0.4) — 保留完整 GateVerdict 对象 dict[gate_name, GateVerdict].
                      之前是 dict[str, bool], 丢失 verdict.message 语义.
                      v5.4 P2-4: 从 dict[str, Any] 改为强类型 dict[str, GateVerdict].
        semantic_satisfied: LLM 语义评估是否通过 (v2.0+ LLM 调用, Phase 2 可为 None)
        tasks_run: v2.3 Phase C — 本轮实际跑的 task IDs (供 Orchestrator 增量选择参考)
        task_outcomes: v2.3 Phase C — 本轮每个 task 的最终状态
            {task_id: "completed" | "failed" | "cancelled"}, 供下一轮 _select_round_tasks
            区分"已完成 (跳过)" vs "失败 (重跑)"
    """

    round_id: int
    stage: str = ""
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    gate_results: dict[str, "GateVerdict"] = field(default_factory=dict)
    guardrail_result: str | None = None  # PRE/POST guardrail 判定结果 (pass/block/retry)
    semantic_satisfied: bool | None = None  # None = 未评估
    tasks_run: list[str] = field(default_factory=list)
    task_outcomes: dict[str, str] = field(default_factory=dict)
    channel_versions: dict[str, int] = field(default_factory=dict)


@dataclass
class ConvergenceVerdict:
    """收敛判定结果.

    Attributes:
        should_stop: 是否应该停止循环
        level: 触发的级别 (0=继续, 1=语义, 2=停滞, 3=质量, 4=硬上限)
        reason: 触发原因描述
    """

    should_stop: bool
    level: int
    reason: str

    @property
    def level_name(self) -> str:
        """人类可读的级别名."""
        return LEVEL_NAMES.get(self.level, "UNKNOWN")

    @classmethod
    def continue_(cls) -> ConvergenceVerdict:
        """继续执行的便捷构造."""
        return cls(should_stop=False, level=LEVEL_CONTINUE, reason="继续迭代")

    @classmethod
    def stop(cls, level: int, reason: str) -> ConvergenceVerdict:
        """停止执行的便捷构造 (level 校验)."""
        if level not in LEVEL_NAMES:
            raise ValueError(
                f"Invalid level {level} (from caller: stop({level=}, {reason=})). "
                f"Must be one of {sorted(LEVEL_NAMES.keys())}"
            )
        return cls(should_stop=True, level=level, reason=reason)


# ============================================================
# 核心算法: 停滞检测
# ============================================================


def diff_ratio(current: RoundHistory, previous: RoundHistory) -> float:
    """计算两轮之间的 diff 变化率.

    公式: |current - previous| / max(current, previous)
    返回值 [0.0, 1.0]:
        - 0.0 = 完全无变化
        - 1.0 = 一方为 0, 另一方非 0 (变化率最大)

    Args:
        current: 当前轮历史
        previous: 上一轮历史

    Returns:
        diff ratio, 范围 [0.0, 1.0]

    Edge cases:
        - 两轮都为 0: 视为 0.0 (无变化)
        - 任一轮为 0: 返回 1.0 (相对变化无穷大)
    """
    # 使用 4 个维度的总变化量
    curr_size = (
        current.files_changed + current.lines_added + current.lines_removed
    )
    prev_size = (
        previous.files_changed + previous.lines_added + previous.lines_removed
    )

    if curr_size == 0 and prev_size == 0:
        return 0.0  # 都为空, 无变化

    max_size = max(curr_size, prev_size)
    if max_size == 0:
        return 0.0

    diff_size = abs(curr_size - prev_size)
    return diff_size / max_size


def detect_stagnation(
    history: list[RoundHistory], threshold: int, diff_ratio_threshold: float
) -> bool:
    """检测是否连续 N 轮产出无实质变化.

    两信号联合判定 (借鉴 LangGraph channel_versions):
        1. 数值变化: diff_ratio < diff_ratio_threshold → 数量无变化
        2. 内容变化: _get_new_channel_versions 非空 → channel 内容有变化
    两信号都无变化才计为"一轮无变化". 任一信号有变化 → 重置计数器.

    Args:
        history: 历史轮次列表, 按时间顺序 (index 0 = 最早, -1 = 最新)
        threshold: 连续多少轮无变化触发停滞
        diff_ratio_threshold: diff 变化率阈值 (低于此值视为无变化)

    Returns:
        True = 触发停滞, False = 未停滞
    """
    if len(history) < threshold + 1:
        return False

    consecutive_no_change = 0
    for i in range(len(history) - 1, 0, -1):
        current = history[i]
        previous = history[i - 1]
        ratio = diff_ratio(current, previous)

        # 补充 channel_versions 信号: channel 内容变化则不算停滞
        channels_changed = bool(
            _get_new_channel_versions(
                previous.channel_versions, current.channel_versions
            )
        )

        if ratio < diff_ratio_threshold and not channels_changed:
            consecutive_no_change += 1
            if consecutive_no_change >= threshold:
                return True
        else:
            consecutive_no_change = 0

    return False


# ============================================================
# channel_versions 增量触发算法
# ============================================================


def _get_new_channel_versions(
    prev_versions: dict[str, int], current_versions: dict[str, int]
) -> set[str]:
    """返回本轮 (round/step) 被修改的 channel 名集合.

    从 version_utils.py 迁移 (Phase P1-II): 替代原 get_new_channel_versions.

    Args:
        prev_versions: 上一轮的 channel_versions dict (本轮初基线)
        current_versions: 本轮末的 channel_versions dict (CheckpointEnvelope.channel_versions)

    Returns:
        set[str]: 被修改 (新增 / 删除 / version 累加) 的 channel 名

    算法 (LangGraph pregel/main.py:1736-1740 简化):
        1. 遍历 current_versions → 若 version > prev (或 prev 缺失) → 加入 modified
        2. 遍历 prev_versions → 若 key 不在 current 中 → 视为删除, 加入 modified
    """
    modified: set[str] = set()

    # 1. 当前 versions 中所有 key: 若 version 累加或新增, 视为修改
    for name, ver in current_versions.items():
        prev_ver = prev_versions.get(name, 0)
        if ver > prev_ver:
            modified.add(name)

    # 2. prev 中存在但 current 中不存在的 key → 视为删除/重置
    for name in prev_versions:
        if name not in current_versions:
            modified.add(name)

    return modified


# ============================================================
# ConvergenceJudge 主类
# ============================================================


class ConvergenceJudge:
    """4 级收敛判定引擎.

    判定顺序 (从硬到软):
        1. 硬上限 (level=4): current_round >= max_iterations
        2. 质量门 (level=3): 所有 6 道 Gate 全 PASS
        3. 停滞检测 (level=2): 连续 N 轮无实质变化
        4. 语义收敛 (level=1): LLM 评估通过

    注意: 硬上限 > 质量门 > 停滞 > 语义
    (高优先级先检查, 一旦触发立即停止)

    Usage:
        judge = ConvergenceJudge()
        verdict = judge.evaluate(history)
        if verdict.should_stop:
            _logger.info("收敛停止: %s", verdict.reason)
    """

    def __init__(self, config: ConvergenceConfig | None = None) -> None:
        """初始化.

        Args:
            config: 收敛配置, None = 默认配置
        """
        self.config = config or ConvergenceConfig()

    def auto_tune_max_iter(self, audit_history: Any) -> int | None:
        """冷启动自适应 max_iter.

        冷启动 (样本 < min_samples_for_learning): 返回 None, 调用方使用
        config.max_iterations 作为默认值.
        足够样本后: 委托 ThresholdLearner.compute_max_iter() 计算
        min(avg_rounds * 2, 20).

        Args:
            audit_history: AuditHistory 实例, 提供历史审计记录.

        Returns:
            int | None: 推荐的 max_iter, 或 None (数据不足, 使用默认值).
        """
        from auto_engineering.loop.audit_history import AuditHistory
        from auto_engineering.loop.threshold_learner import ThresholdLearner

        if not isinstance(audit_history, AuditHistory):
            return None
        entries = audit_history.read_history()
        min_samples = self.config.min_samples_for_learning
        if len(entries) < min_samples:
            return None
        learner = ThresholdLearner(audit_history)
        return learner.compute_max_iter()

    def evaluate(
        self, history: list[RoundHistory]
    ) -> ConvergenceVerdict:
        """评估当前是否应该停止循环.

        v2.5 P2-DRIFT-05: 之前签名是 `(self, state, history)`, 但 state
        参数从 v2.3 至今永远传 None (v2.3 P0-A 决策后, 运行时走
        engine.state.LoopState dataclass, CheckpointEnvelope 仅供
        checkpoint 持久化 — judge 不读 runtime state). 移除 vestigial 参数.

        Args:
            history: 历史轮次列表 (可为空)

        Returns:
            ConvergenceVerdict: 判定结果, should_stop=True 表示应停止
        """
        # 1. 硬上限检查
        verdict = self._check_hard_limit(history)
        if verdict is not None:
            return verdict

        # 2. 质量门检查
        verdict = self._check_quality_gates(history)
        if verdict is not None:
            return verdict

        # 3. 停滞检测
        verdict = self._check_stagnation(history)
        if verdict is not None:
            return verdict

        # 4. 语义收敛检查
        verdict = self._check_semantic(history)
        if verdict is not None:
            return verdict

        # 默认: 继续
        return ConvergenceVerdict.continue_()

    def _check_hard_limit(
        self, history: list[RoundHistory]
    ) -> ConvergenceVerdict | None:
        """硬上限检查: 当前轮次 >= max_iterations.

        Args:
            history: 历史轮次列表

        Returns:
            ConvergenceVerdict 或 None (None 表示未触发)
        """
        if not history:
            return None

        current_round = history[-1].round_id
        if current_round >= self.config.max_iterations:
            return ConvergenceVerdict.stop(
                level=LEVEL_HARD_LIMIT,
                reason=f"达到最大迭代次数 {self.config.max_iterations} (硬上限)",
            )
        return None

    def _check_quality_gates(
        self, history: list[RoundHistory]
    ) -> ConvergenceVerdict | None:
        """质量门检查: 最新一轮所有 Gate 全 PASS.

        Args:
            history: 历史轮次列表

        Returns:
            ConvergenceVerdict 或 None (None 表示未触发或 Gate 还没全实现)

        Note:
            v2.3 Phase D (P0.4): gate_results 是 dict[gate_name, GateVerdict],
            必须读 verdict.passed (不能 all(values), 否则 dataclass 实例永远 truthy).
            同时 GateVerdict 失败时 reason 应包含 gate message, 让 Judge 输出可读.
        """
        if not history:
            return None

        latest = history[-1]
        if not latest.gate_results:
            # 没有 Gate 结果, 不触发
            return None

        # v2.3 Phase D: gate_results 是 dict[gate_name, GateVerdict]
        # 必须读 .passed (不能 all(values), 否则 GateVerdict dataclass 实例永远 truthy)
        gate_verdicts = latest.gate_results
        failed_gates: list[tuple[str, "GateVerdict"]] = [
            (name, v) for name, v in gate_verdicts.items() if not v.passed
        ]

        if not failed_gates:
            # 全 PASS → 触发停止, reason 含门数量 (借鉴 LangGraph pregel/main.py)
            return ConvergenceVerdict.stop(
                level=LEVEL_QUALITY,
                reason=(
                    f"所有质量门通过 ({len(gate_verdicts)} 道): "
                    f"{', '.join(gate_verdicts.keys())}"
                ),
            )

        # 2026-07-05 修复 (对标审计 P0-1): 门失败 ≠ 质量达标, 不应返回 STOP.
        # 参考 LangGraph: gate 失败是诊断信号, 不是收敛条件.
        # 全通过 → QUALITY_PASS STOP (收敛); 有失败 → CONTINUE (继续修复).
        # 之前: 门失败也返回 STOP → orchestrator step 2i 需要反向补丁覆盖 judge 判決.
        # 现在: 门失败返回 None → judge 继续检查下一级 (停滞/语义), 不误判.
        return None

    def _check_stagnation(
        self, history: list[RoundHistory]
    ) -> ConvergenceVerdict | None:
        """停滞检测: 连续 N 轮无实质变化.

        Args:
            history: 历史轮次列表

        Returns:
            ConvergenceVerdict 或 None (None 表示未触发)
        """
        stagnant = detect_stagnation(
            history,
            threshold=self.config.stagnation_threshold,
            diff_ratio_threshold=self.config.stagnation_diff_ratio,
        )
        if stagnant:
            return ConvergenceVerdict.stop(
                level=LEVEL_STAGNANT,
                reason=f"连续 {self.config.stagnation_threshold} 轮产出无实质变化 "
                f"(diff_ratio < {self.config.stagnation_diff_ratio})",
            )
        return None

    def _check_semantic(
        self, history: list[RoundHistory]
    ) -> ConvergenceVerdict | None:
        """语义收敛检查: LLM 评估"本轮产出满足需求".

        Args:
            history: 历史轮次列表

        Returns:
            ConvergenceVerdict 或 None (None 表示未评估或未通过)

        Note:
            Phase 2 实现: 仅当 semantic_satisfied=True 时触发
            v2.0+ 接 LLM 调用: 内部调用 LLM 评估当前产出
        """
        if not history:
            return None

        latest = history[-1]
        if latest.semantic_satisfied is True:
            return ConvergenceVerdict.stop(
                level=LEVEL_SEMANTIC,
                reason="LLM 评估: 本轮产出满足需求",
            )
        return None
