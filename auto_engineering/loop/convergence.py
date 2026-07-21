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
from typing import TYPE_CHECKING

from auto_engineering.loop.checkpoint.records import RoundHistory  # P1-7: definition moved to records

if TYPE_CHECKING:
    from auto_engineering.gates.base import GateVerdict
    from auto_engineering.loop.audit_history import AuditHistory

__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_STAGNATION_DIFF_RATIO",
    "DEFAULT_STAGNATION_THRESHOLD",
    "LEVEL_CONTINUE",
    "LEVEL_HARD_LIMIT",
    "LEVEL_NAMES",
    "LEVEL_QUALITY",
    "LEVEL_SEMANTIC",
    "LEVEL_STAGNANT",
    "ConvergenceConfig",
    "ConvergenceJudge",
    "ConvergenceVerdict",
    "RoundHistory",
    "detect_stagnation",
    "diff_ratio",
]

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
    """

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    stagnation_threshold: int = DEFAULT_STAGNATION_THRESHOLD
    stagnation_diff_ratio: float = DEFAULT_STAGNATION_DIFF_RATIO


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
                f"Invalid level {level} (reason: {reason}). "
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

    基于 diff_ratio 数值变化信号: diff_ratio < diff_ratio_threshold → 数量无变化.
    连续 threshold 轮无变化即触发停滞.

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

        if ratio < diff_ratio_threshold:
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

    def evaluate(
        self,
        history: list[RoundHistory],
        *,
        design_coverage_ok: bool = False,
        system_deep_audit_ok: bool = False,
    ) -> ConvergenceVerdict:
        """评估当前是否应该停止循环.

        v2.5 P2-DRIFT-05: 之前签名是 `(self, state, history)`, 但 state
        参数从 v2.3 至今永远传 None (v2.3 P0-A 决策后, 运行时走
        engine.state.LoopState dataclass, CheckpointEnvelope 仅供
        checkpoint 持久化 — judge 不读 runtime state). 移除 vestigial 参数.

        v5.6 §C.5: 离散 tick 路径不填充 history.semantic_satisfied (无 LLM
        自评), 改由 system_deep_audit + 设计覆盖双通过作为语义达成信号.
        两个 keyword-only 参数默认 False, 保持 v5.5 连续路径调用兼容.

        终态成功优先级 (§C.5.5): 双通过的 GOAL_ACHIEVED 优先于硬上限 —
        若恰在 max_iterations 那轮达成成功, 应报 GOAL_ACHIEVED 而非
        HARD_LIMIT (工作已完成, 报硬上限会误导).

        Args:
            history: 历史轮次列表 (可为空)
            design_coverage_ok: 设计覆盖无缺口 (无 MISSING/DIVERGED design item)
            system_deep_audit_ok: system_deep_audit 通过 (P0=0 且 P1≤阈值)

        Returns:
            ConvergenceVerdict: 判定结果, should_stop=True 表示应停止
        """
        # 0. 终态成功 (v5.6 §C.5): audit + 覆盖双通过 → GOAL_ACHIEVED, 优先于硬上限
        if system_deep_audit_ok and design_coverage_ok:
            result = ConvergenceVerdict.stop(
                level=LEVEL_SEMANTIC,
                reason=(
                    "system_deep_audit 通过且设计覆盖无缺口 "
                    "(P0=0, P1≤阈值, 无 MISSING/DIVERGED)"
                ),
            )
        else:
            # 1. 硬上限检查
            result = self._check_hard_limit(history)
            # 2. 质量门检查
            if result is None:
                result = self._check_quality_gates(history)
            # 3. 停滞检测
            if result is None:
                result = self._check_stagnation(history)
            # 默认: 继续
            if result is None:
                result = ConvergenceVerdict.continue_()

        # T69a: Record convergence event for metrics
        from auto_engineering.metrics.collector import AIOrigin, get_collector
        mc = get_collector()
        if mc is not None:
            mc.record_convergence(
                verdict=result.level_name,
                total_ticks=len(history),
                ai_origin=AIOrigin(
                    level="led",
                    agent_role="critic",
                    driver_type="agent",
                ),
            )

        return result

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
            ConvergenceVerdict STOP if all gates passed, None if not applicable
            (history empty, no gates run, or some gates failed — caller continues
            to next check).

            None semantics: 本检查无法做出判定 (非 pass/fail), 交由下一级检查.
            这和返回 CONTINUE 不同 — CONTINUE 是"判定: 继续", None 是"无判定".

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
        failed_gates: list[tuple[str, GateVerdict]] = [
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
