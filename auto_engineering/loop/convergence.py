"""v2.0 4 级收敛判定.

设计来源: design/v2.0-Analysis-Loop.md §4.7

4 级判定(从硬到软):
1. 硬上限 (level=4): max_iterations 达到 → 立即停止
2. 质量门 (level=3): 7 道 Gate 全 PASS → 停止
3. 停滞检测 (level=2): N 轮产出无实质变化 → 停止
4. 语义收敛 (level=1): LLM 评估"本轮产出满足需求" → 停止
0. 继续 (level=0): 默认, 未触发任何停止条件

API:
    judge = ConvergenceJudge(config)
    verdict = judge.evaluate(state, history)
    if verdict.should_stop: ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
class RoundHistory:
    """单轮历史记录.

    用于停滞检测算法: 计算与上一轮的 diff 变化率.

    Attributes:
        round_id: 轮次 ID (1-indexed)
        files_changed: 本轮修改的文件数
        lines_added: 本轮新增行数
        lines_removed: 本轮删除行数
        gate_results: v2.3 Phase D (P0.4) — 保留完整 Verdict 对象 dict[gate_name, Verdict].
                      之前是 dict[str, bool], 丢失 verdict.message 语义.
                      用 Any 是为了避免与 gates 模块循环引用 (RoundHistory 在 convergence.py,
                      Verdict 在 gates/base.py). 实际值始终为 Verdict.
        semantic_satisfied: LLM 语义评估是否通过 (Phase 3+ LLM 调用, Phase 2 可为 None)
        tasks_run: v2.3 Phase C — 本轮实际跑的 task IDs (供 Orchestrator 增量选择参考)
        task_outcomes: v2.3 Phase C — 本轮每个 task 的最终状态
            {task_id: "completed" | "failed" | "cancelled"}, 供下一轮 _select_round_tasks
            区分"已完成 (跳过)" vs "失败 (重跑)"
    """

    round_id: int
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    gate_results: dict[str, Any] = field(default_factory=dict)  # 实际值: Verdict
    semantic_satisfied: bool | None = None  # None = 未评估
    tasks_run: list[str] = field(default_factory=list)
    task_outcomes: dict[str, str] = field(default_factory=dict)


@dataclass
class Verdict:
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
    def continue_(cls) -> Verdict:
        """继续执行的便捷构造."""
        return cls(should_stop=False, level=LEVEL_CONTINUE, reason="继续迭代")

    @classmethod
    def stop(cls, level: int, reason: str) -> Verdict:
        """停止执行的便捷构造 (level 校验)."""
        if level not in LEVEL_NAMES:
            raise ValueError(
                f"Invalid level {level}. Must be one of {sorted(LEVEL_NAMES.keys())}"
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

    算法:
        1. 从最新一轮往前回溯, 累计"无变化"轮数
        2. 连续 N 轮 diff_ratio < diff_ratio_threshold → 停滞
        3. 任一轮 diff_ratio >= threshold → 重置计数器 (有变化就不算停滞)

    Args:
        history: 历史轮次列表, 按时间顺序 (index 0 = 最早, -1 = 最新)
        threshold: 连续多少轮无变化触发停滞
        diff_ratio_threshold: diff 变化率阈值 (低于此值视为无变化)

    Returns:
        True = 触发停滞, False = 未停滞
    """
    if len(history) < threshold + 1:
        # 需要至少 threshold + 1 轮才能比较
        return False

    # 从最新一轮往前检查连续 N 轮
    consecutive_no_change = 0
    # 从倒数第 2 轮开始(因为 diff_ratio 需要两轮比较)
    for i in range(len(history) - 1, 0, -1):
        current = history[i]
        previous = history[i - 1]
        ratio = diff_ratio(current, previous)
        if ratio < diff_ratio_threshold:
            consecutive_no_change += 1
            if consecutive_no_change >= threshold:
                return True
        else:
            # 出现变化, 重置计数器
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
        current_versions: 本轮末的 channel_versions dict (LoopState.channel_versions)

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
        2. 质量门 (level=3): 所有 7 道 Gate 全 PASS
        3. 停滞检测 (level=2): 连续 N 轮无实质变化
        4. 语义收敛 (level=1): LLM 评估通过

    注意: 硬上限 > 质量门 > 停滞 > 语义
    (高优先级先检查, 一旦触发立即停止)

    Usage:
        judge = ConvergenceJudge()
        verdict = judge.evaluate(state, history)
        if verdict.should_stop:
            print(f"停止: {verdict.reason}")
    """

    def __init__(self, config: ConvergenceConfig | None = None) -> None:
        """初始化.

        Args:
            config: 收敛配置, None = 默认配置
        """
        self.config = config or ConvergenceConfig()

    def evaluate(
        self, state: Any, history: list[RoundHistory]
    ) -> Verdict:
        """评估当前是否应该停止循环.

        Args:
            state: 当前 LoopState (Phase 2 暂不直接读取, 保留接口供 Phase 3+ 使用)
            history: 历史轮次列表 (可为空)

        Returns:
            Verdict: 判定结果, should_stop=True 表示应停止
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
        return Verdict.continue_()

    def _check_hard_limit(
        self, history: list[RoundHistory]
    ) -> Verdict | None:
        """硬上限检查: 当前轮次 >= max_iterations.

        Args:
            history: 历史轮次列表

        Returns:
            Verdict 或 None (None 表示未触发)
        """
        if not history:
            return None

        current_round = history[-1].round_id
        if current_round >= self.config.max_iterations:
            return Verdict.stop(
                level=LEVEL_HARD_LIMIT,
                reason=f"达到最大迭代次数 {self.config.max_iterations} (硬上限)",
            )
        return None

    def _check_quality_gates(
        self, history: list[RoundHistory]
    ) -> Verdict | None:
        """质量门检查: 最新一轮所有 Gate 全 PASS.

        Args:
            history: 历史轮次列表

        Returns:
            Verdict 或 None (None 表示未触发或 Gate 还没全实现)

        Note:
            v2.3 Phase D (P0.4): gate_results 是 dict[gate_name, Verdict],
            必须读 verdict.passed (不能 all(values), 否则 dataclass 实例永远 truthy).
            同时 Verdict 失败时 reason 应包含 gate message, 让 Judge 输出可读.
        """
        if not history:
            return None

        latest = history[-1]
        if not latest.gate_results:
            # 没有 Gate 结果, 不触发
            return None

        # v2.3 Phase D: gate_results 是 dict[gate_name, Verdict]
        # 必须读 .passed (不能 all(values), 否则 Verdict dataclass 实例永远 truthy)
        gate_verdicts = latest.gate_results
        failed_gates: list[tuple[str, Any]] = [
            (name, v) for name, v in gate_verdicts.items() if not v.passed
        ]

        if not failed_gates:
            # 全 PASS → 触发停止, reason 含门数量 (借鉴 LangGraph pregel/main.py)
            return Verdict.stop(
                level=LEVEL_QUALITY,
                reason=(
                    f"所有质量门通过 ({len(gate_verdicts)} 道): "
                    f"{', '.join(gate_verdicts.keys())}"
                ),
            )

        # v2.3 Phase D-fix: 任一 Gate FAIL → 触发停止 (质量门是"门", 不通过应关).
        # 修复前: 返回 None, 让停滞检测/语义评估"误判"失败原因.
        # 修复后: 直接 Verdict.stop(level=LEVEL_QUALITY), reason 含 gate name + message,
        # 让 Orchestrator runtime smoke 输出 "质量门失败 (1 道): fake_failing: intentional...".
        # 取前 3 道失败详情, 避免 reason 过长.
        failed_details = "; ".join(
            f"{name}: {verdict.message}" for name, verdict in failed_gates[:3]
        )
        return Verdict.stop(
            level=LEVEL_QUALITY,
            reason=f"质量门失败 ({len(failed_gates)} 道): {failed_details}",
        )

    def _check_stagnation(
        self, history: list[RoundHistory]
    ) -> Verdict | None:
        """停滞检测: 连续 N 轮无实质变化.

        Args:
            history: 历史轮次列表

        Returns:
            Verdict 或 None (None 表示未触发)
        """
        stagnant = detect_stagnation(
            history,
            threshold=self.config.stagnation_threshold,
            diff_ratio_threshold=self.config.stagnation_diff_ratio,
        )
        if stagnant:
            return Verdict.stop(
                level=LEVEL_STAGNANT,
                reason=f"连续 {self.config.stagnation_threshold} 轮产出无实质变化 "
                f"(diff_ratio < {self.config.stagnation_diff_ratio})",
            )
        return None

    def _check_semantic(
        self, history: list[RoundHistory]
    ) -> Verdict | None:
        """语义收敛检查: LLM 评估"本轮产出满足需求".

        Args:
            history: 历史轮次列表

        Returns:
            Verdict 或 None (None 表示未评估或未通过)

        Note:
            Phase 2 实现: 仅当 semantic_satisfied=True 时触发
            Phase 3+ 接 LLM 调用: 内部调用 LLM 评估当前产出
        """
        if not history:
            return None

        latest = history[-1]
        if latest.semantic_satisfied is True:
            return Verdict.stop(
                level=LEVEL_SEMANTIC,
                reason="LLM 评估: 本轮产出满足需求",
            )
        return None
