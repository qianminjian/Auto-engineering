"""Auto-Engineering — 宿主驱动的确定性 Loop 工程内核。

运行边界:
    主 Agent/Host Driver 负责连续消费 Action、调用原生 Worker、观察并回写结果。
    Python Core 每次只执行一个确定性 Tick：校验输入、提交事件、投影状态并生成
    下一条 Action。EventStore 是新运行的事实源，EngineState 是可重建投影。

Python Core 不启动 LLM、Worker 或长期协调循环；宿主差异通过 Host Adapter 隔离。
公开入口包括 `ae doctor`、`ae dev-loop` 和 `ae status`，具体运行协议以当前设计
文档及宿主 Skill/Command 为准。
"""

# T3-1: __version__ 是 auto_engineering 包的版本,用于 CLI --version / ae init --version
# 与 _ae_version (模板引擎版本) 不同: _ae_version 在 answers.py BUILTIN_VARS 中,
# 用于模板渲染上下文,判断模板引擎的能力支持
__version__ = "5.8.0-rc.5"

__all__ = ["__version__"]
