"""项目配置.

核心类:
    Settings            — 全局配置
    ProjectEnvironment  — init/dev-loop 共享契约

v1.1 Plan B 新增:
    load_ae_answers()   — 低级 .ae-answers.yml 加载函数
    preflight()         — 入口前置校验
"""

from .environment import ProjectEnvironment, load_ae_answers, preflight
from .settings import Settings

__all__ = [
    "Settings",
    "ProjectEnvironment",
    "load_ae_answers",
    "preflight",
]
