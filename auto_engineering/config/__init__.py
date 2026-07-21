"""项目配置.

核心类:
    ProjectEnvironment  — init/dev-loop 共享契约
    load_ae_answers()  — 低级 .ae-answers.yml 加载函数
"""

from .environment import ProjectEnvironment, load_ae_answers

__all__ = [
    "ProjectEnvironment",
    "load_ae_answers",
]
