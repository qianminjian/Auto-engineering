"""Send — 多 Agent 动态路由消息(v2.0+ 预留).

参考 LangGraph Send: Agent 运行时决定下一个 Agent 和参数.
v1.0 不实现 PUSH 消费,仅保留 dataclass 定义供未来扩展.
"""

from dataclasses import dataclass


@dataclass
class Send:
    """动态路由消息. 由 Agent 输出携带,LoopEngine 在下一轮消费 _pending_sends."""

    node: str        # 目标 Stage/Agent 名
    arg: dict        # 传给目标的参数
