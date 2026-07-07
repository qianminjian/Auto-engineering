"""Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作.

架构:
    Python 控制流（确定性）        LLM 调用（智能）
    ┌──────────────────────┐     ┌──────────────────┐
    │ engine/loop.py        │     │ agents/           │
    │   while True:         │────→│   architect.py   │
    │     tick()            │     │   developer.py   │
    │     agent.execute()   │     │   critic.py      │
    │     gates.check()     │←────│                  │
    │     after_tick()      │     └──────────────────┘
    └──────────────────────┘

命令:
    ae doctor             环境预检
    ae dev-loop <req>     单需求开发循环
    ae status             查看当前进度
    ae agent <role>       单 Agent 调用 (architect/developer/critic)

设计文档: design/v5.0-Design-Loop.md
GitHub: https://github.com/qianminjian/Auto-engineering

2026-07-04 v5.0 final: 整合 main 分支 (Self-Refine + suggested_fix + plugin mode
修复 + 大量 test/docs) + v5.0-plugin-loop-final 分支 (4 个 plugin mode bug
真实修复).
"""

# T3-1: __version__ 是 auto_engineering 包的版本,用于 CLI --version / ae init --version
# 与 _ae_version (模板引擎版本) 不同: _ae_version 在 answers.py BUILTIN_VARS 中,
# 用于模板渲染上下文,判断模板引擎的能力支持
__version__ = "5.5.0"

__all__ = ["__version__"]
