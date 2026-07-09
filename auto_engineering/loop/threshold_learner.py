"""v5.5 — P1 阈值自动学习 + max_iter 自适应.

设计来源: design/v5.6-Design-Loop.md §B6.5c, §B6.5d

从审计历史 JSONL 学习:
- compute_p1_threshold(): 从历史 P1 计数算 p75, 作为推荐阈值
- compute_max_iter(): 从运行历史平均轮数评估 max_iter
- should_adjust(): 安全机制, 变化 >50% 需人工确认
"""

from __future__ import annotations

import statistics

from auto_engineering.loop.audit_history import AuditHistory

__all__ = ["ThresholdLearner"]


class ThresholdLearner:
    """P1 阈值 + max_iter 自适应学习器.

    Args:
        audit_history: AuditHistory 实例, 提供历史审计记录.
    """

    MIN_SAMPLES = 5  # 类级默认, 实例可覆盖

    def __init__(self, audit_history: AuditHistory, min_samples: int | None = None):
        self._history = audit_history
        if min_samples is not None:
            self.MIN_SAMPLES = min_samples

    def compute_p1_threshold(self) -> int:
        """从历史 P1 计数算 p75, 作为推荐阈值.

        Returns:
            int: max(int(p75), 1). 冷启动时返回 6.
        """
        entries = self._history.read_history()
        if len(entries) < self.MIN_SAMPLES:
            return 6  # 冷启动默认值
        p1_counts = [e["p1_count"] for e in entries]
        p75 = statistics.quantiles(p1_counts, n=4)[2]  # 75th percentile
        return max(int(p75), 1)

    def compute_max_iter(self) -> int:
        """从运行历史平均轮数评估 max_iter.

        Returns:
            int: min(int(avg_rounds * 2), 20). 冷启动时返回 10.
            avg_rounds 从 JSONL 的 "rounds" 字段读取, 缺失时默认 1.
        """
        entries = self._history.read_history()
        if len(entries) < self.MIN_SAMPLES:
            return 10  # 冷启动默认值
        rounds = [e.get("rounds", 1) for e in entries]
        avg_rounds = statistics.mean(rounds)
        return min(int(avg_rounds * 2), 20)

    def auto_tune_threshold(self, current: int) -> int | None:
        """若连续 3 次 P1 计数一致且变化 ≤50%, 返回新阈值; 否则 None.

        算法:
            1. 读取全部历史记录
            2. 取最近 3 条, 若 P1 计数不全相同 → 返回 None
            3. 全相同 → 调用 compute_p1_threshold() 算推荐值
            4. should_adjust(recommended, current) 检查变化幅度
            5. 通过 → 返回 recommended; 未通过 → 返回 None

        Args:
            current: 当前 P1 阈值.

        Returns:
            int | None: 新阈值 (自动调整), 或 None (不调整).
        """
        entries = self._history.read_history()
        if len(entries) < 3:
            return None
        last_3 = entries[-3:]
        p1s = [e["p1_count"] for e in last_3]
        if len(set(p1s)) != 1:  # 最近 3 次 P1 计数不全相同
            return None
        recommended = self.compute_p1_threshold()
        if self.should_adjust(recommended, current):
            return recommended
        return None

    def should_adjust(self, recommended: int, current: int) -> bool:
        """安全机制: 变化 >50% 时返回 False (需人工确认).

        Args:
            recommended: 推荐的阈值.
            current: 当前的阈值.

        Returns:
            bool: True 如果变化 <= 50% (可自动调整), 否则 False.
        """
        if current == 0:
            return True
        change_pct = abs(recommended - current) / current
        return change_pct <= 0.5
