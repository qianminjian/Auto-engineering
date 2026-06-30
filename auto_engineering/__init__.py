"""Init-Engineering — Agent Skill 模式项目环境初始化工具.

两种初始化模式：
    存量项目：通过代码分析自动识别项目类型、依赖、配置，自动化初始化
    新项目：向导式询问确认方向，生成定制化项目骨架

命令:
    ae init <project>         项目环境初始化
"""

# T3-1: __version__ 是 auto_engineering 包的版本,用于 CLI --version / ae init --version
# 与 _ae_version (模板引擎版本) 不同: _ae_version 在 answers.py BUILTIN_VARS 中,
# 用于模板渲染上下文,判断模板引擎的能力支持
__version__ = "0.1.0"
