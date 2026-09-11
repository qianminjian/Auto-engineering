"""Loop 的公共类型。

生产运行时由主 Agent 逐 Tick 驱动，状态事实统一由 EventStore 保存。
- Plan/Task DAG + check_file_isolation (确定性文件隔离检查)
- 单 Tick 状态推进、Action 编译与事务提交
- Python Core 只消费一次输入并返回一个确定性 Action。

本包不启动 Worker、不维护宿主主循环，也不承担并发调度。

生产公共包不导出历史状态模型。
状态序列化只通过 EngineState 与 EventStore 完成。
    运行时 Orchestrator / Runtime / Gates 统一走 engine.state.EngineState.
    历史辅助类型不属于生产运行时.
    生产公共包只保留当前模型导出.
"""

from auto_engineering.engine.models import Plan, Task

__all__ = ["Plan", "Task"]
