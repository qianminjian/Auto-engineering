"""收敛判定的配置与值对象。

判定算法与这些数据模型分离；本模块不读取运行态、不执行循环，也不拥有
任何宿主调度职责。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_STAGNATION_THRESHOLD = 2
DEFAULT_STAGNATION_DIFF_RATIO = 0.05

LEVEL_CONTINUE = 0
LEVEL_SEMANTIC = 1
LEVEL_STAGNANT = 2
LEVEL_QUALITY = 3
LEVEL_HARD_LIMIT = 4

LEVEL_NAMES = {
    LEVEL_CONTINUE: "CONTINUE",
    LEVEL_SEMANTIC: "GOAL_ACHIEVED",
    LEVEL_STAGNANT: "STAGNANT",
    LEVEL_QUALITY: "QUALITY_PASS",
    LEVEL_HARD_LIMIT: "MAX_ITERATIONS",
}


@dataclass
class ConvergenceConfig:
    """收敛判定配置参数。"""

    max_iterations: int | None = None
    stagnation_threshold: int = DEFAULT_STAGNATION_THRESHOLD
    stagnation_diff_ratio: float = DEFAULT_STAGNATION_DIFF_RATIO


@dataclass
class ConvergenceVerdict:
    """收敛判定结果。"""

    should_stop: bool
    level: int
    reason: str

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "UNKNOWN")

    @classmethod
    def continue_(cls) -> ConvergenceVerdict:
        return cls(should_stop=False, level=LEVEL_CONTINUE, reason="继续迭代")

    @classmethod
    def stop(cls, level: int, reason: str) -> ConvergenceVerdict:
        if level not in LEVEL_NAMES:
            raise ValueError(
                f"Invalid level {level} (reason: {reason}). "
                f"Must be one of {sorted(LEVEL_NAMES.keys())}"
            )
        return cls(should_stop=True, level=level, reason=reason)


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
    "ConvergenceVerdict",
]
