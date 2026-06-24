"""LoopEngine — while True 执行循环. 参考 LangGraph pregel/_loop.py:592-712.

核心 API:
    LoopEngine.run()      — 全链路 async. tick → execute → after_tick
    LoopEngine.tick()     — 决定下一步 Stage(单步)
    LoopEngine.after_tick() — 持久化 + step 自增
    LoopEngine.resume()   — 从 checkpoint 恢复

v3.0 修复:
    §2.1 interrupt_after 处理补 return False(与 interrupt_before 对齐)
    §4.1 length 校验从 §7.4 前置到 §4.1 主代码

v3.1 B 类修复 (Plan A Phase 2):
    B1 (P0): run() while 循环检查 status.startswith('interrupt') → break
        (与 D4 同源,已在 d128ba2 commit 修复)
    B6 (P2): resume() 拒绝从 status='done' 的 checkpoint 恢复
        Why: done 表示循环已正常结束,resume 只会触发空跑或重复终止.

v3.1 P3 设计选择(不修):
    B2 design choice: GuardrailRetrySignal 不继承 AEError(详见 errors.py)
        Why: RetryPolicy 期望捕获后处理,不混入 fatal 流.
    B4 design choice: 运行时 runtime 类型签名 (AgentRuntime | None)
        Why: Phase 1 MockRuntime 简化签名,Phase 2+ 接真实 Runtime 时再收紧.
    B7-B9 design choice: dev_loop 边硬编码 architect→developer→critic
        Why: v1.0 范围,Phase 2+ 引入 builder 配置化.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.errors import (
    AEError,
    ErrorCode,
    GuardrailRetrySignal,
    OutputDropped,
)
from auto_engineering.engine.checkpoint import Checkpoint, CheckpointStore
from auto_engineering.engine.graph import Stage, StageGraph
from auto_engineering.engine.state import LoopState

if TYPE_CHECKING:
    from auto_engineering.runtime.runtime import AgentRuntime


@dataclass
class StageResult:
    """Stage 执行结果. writes 是 dict[channel_name, value],与 stage.output_channels 对应."""

    stage: str
    writes: dict[str, Any]
    raw: Any = None  # Agent 返回的原始结果(Phase 2+)


@dataclass
class LoopResult:
    """LoopEngine.run() 的返回值."""

    status: str         # "done" | "out_of_steps" | "drained" | "error"
    state: LoopState
    total_steps: int
    checkpoint_id: str

    @classmethod
    def from_checkpoint(cls, checkpoint: Checkpoint) -> "LoopResult":
        return cls(
            status=checkpoint.status,
            state=checkpoint.state,
            total_steps=checkpoint.step,
            checkpoint_id=checkpoint.id,
        )


class LoopInterrupted(Exception):
    """Loop 被中断(interrupt_before/after 触发),可从 checkpoint 恢复."""

    def __init__(self, checkpoint_id: str):
        self.checkpoint_id = checkpoint_id
        super().__init__(
            f"Loop interrupted. Resume with: ae checkpoint resume {checkpoint_id}"
        )


class LoopDrained(Exception):
    """Loop 被优雅关闭(checkpoint 已保存)."""

    def __init__(self, checkpoint_id: str):
        self.checkpoint_id = checkpoint_id
        super().__init__(f"Loop drained. Checkpoint saved: {checkpoint_id}")


class LoopEngine:
    """while True 主循环. tick → execute → after_tick.

    Phase 1 不调 LLM,传 MockRuntime 即可跑通完整 3-Stage 路径.
    Phase 2+ 接真实 AgentRuntime + Guardrail 中间件.
    """

    STAGE_RETRY_LIMIT = 3  # GuardrailRetrySignal 最多重试 3 次

    def __init__(
        self,
        graph: StageGraph,
        runtime: "AgentRuntime | None" = None,
        checkpoint_dir: str = ".ae-checkpoints",
        max_steps: int = 10,
        interrupt_before: set[str] | None = None,
        interrupt_after: set[str] | None = None,
    ):
        self.graph = graph
        self.runtime = runtime
        self.checkpoint_dir = checkpoint_dir
        self.max_steps = max_steps
        self.interrupt_before = interrupt_before or set()
        self.interrupt_after = interrupt_after or set()

        # 运行时状态(每次 run() 时重置,但 resume() 跳过重置)
        self.checkpoint: Checkpoint | None = None
        self.store: CheckpointStore | None = None
        self.current_task: Stage | None = None
        self.step: int = 0
        self.status: str = "pending"

    def _init_checkpoint(self, requirement: str) -> None:
        """创建新 checkpoint + 初始化 store. resume() 跳过此方法."""
        thread_id = str(uuid.uuid4())
        state = LoopState(requirement=requirement)
        self.checkpoint = Checkpoint.create(thread_id=thread_id, state=state)
        self.store = CheckpointStore(
            Path(self.checkpoint_dir) / f"{thread_id}.db"
        )
        self.store.save_checkpoint(self.checkpoint)
        self.step = 0
        self.status = "pending"

    async def run(
        self,
        requirement: str = "",
        max_steps: int | None = None,
    ) -> LoopResult:
        """全链路 async: tick → execute → after_tick.

        行为:
            - run() 第一次调用: _init_checkpoint(requirement) → 进入 while
            - resume() 后调用: self.checkpoint 已设置,跳过初始化
            - max_steps: 优先用参数,fallback 构造器值
        """
        steps = max_steps if max_steps is not None else self.max_steps

        if self.runtime is None:
            raise AEError(
                ErrorCode.AGENT_REGISTRATION_ERROR,
                "LoopEngine.runtime is None. Pass a runtime (or MockRuntime) to run().",
            )

        if self.checkpoint is None:
            self._init_checkpoint(requirement)

        retry_count = 0
        try:
            while True:
                if not self.tick(steps):
                    break
                try:
                    result = await self.runtime.execute(
                        self.current_task,
                        self.checkpoint.state,
                    )
                except OutputDropped:
                    # 静默丢弃当前 Stage 输出,跳过 after_tick,进入下一轮
                    continue
                except GuardrailRetrySignal as e:
                    retry_count += 1
                    if retry_count >= self.STAGE_RETRY_LIMIT:
                        raise AEError(
                            ErrorCode.STAGE_RETRY_EXCEEDED,
                            f"Stage {self.current_task.name} 重试超过 {self.STAGE_RETRY_LIMIT} 次",
                            original_error=e,
                        ) from e
                    await asyncio.sleep(2 ** retry_count)
                    continue  # 跳过 after_tick,重试当前 Stage

                self.after_tick(result)
                retry_count = 0  # 成功后重置

                if self.status == "done":
                    break
                # v3.1 D4 修复: interrupt_after 命中后必须 break,
                # 否则 while 会再次进入 tick() 调度下一 Stage,违反中断语义.
                if self.status.startswith("interrupt"):
                    break

            # 同步最终 status 到 checkpoint(确保 LoopResult 准确反映终止原因)
            self.checkpoint.status = self.status
            # v3.1 B6: 持久化最终 status 到 DB,resume() 才能正确校验
            if self.store:
                self.store.save_checkpoint(self.checkpoint)
            return LoopResult.from_checkpoint(self.checkpoint)
        except AEError as e:
            if e.code == ErrorCode.TASK_CANCELLED and self.store and self.checkpoint:
                self.checkpoint.status = "drained"
                self.store.save_checkpoint(self.checkpoint)
            raise

    def tick(self, max_steps: int) -> bool:
        """决定下一步 Stage. 返回 True 继续,False 结束.

        顺序:
            1. step >= max_steps → status='out_of_steps', return False
            2. graph.next_stage(state) → None → status='done', return False
            3. interrupt_before 命中 → status='interrupt_before', return False
            4. interrupt_after 由调用方 after_tick 检查,不在 tick 处理
        """
        if self.step >= max_steps:
            self.status = "out_of_steps"
            return False

        next_stage = self.graph.next_stage(self.checkpoint.state)
        if next_stage is None:
            self.status = "done"
            return False

        self.current_task = next_stage
        self.checkpoint.state.current_stage = next_stage.name

        if self.interrupt_before and self.current_task.name in self.interrupt_before:
            self.status = "interrupt_before"
            return False

        return True

    def after_tick(self, result: StageResult) -> None:
        """持久化 writes + step 自增 + interrupt_after 检查.

        v3.0 §2.1 修复: interrupt_after 命中时 return False(原文档仅设置 status 不 return,
        实际代码会继续下一轮,违反中断语义).
        """
        self.checkpoint.apply_writes(result.writes)
        self.checkpoint.increment_step()
        self.store.save_checkpoint(self.checkpoint)
        if result.writes:
            self.store.save_writes(
                self.checkpoint.id, self.current_task.name, result.writes
            )
        self.step += 1

        if self.interrupt_after and self.current_task.name in self.interrupt_after:
            self.status = "interrupt_after"
            # v3.1 D4 修复: run() 的 while 循环在 after_tick 之后检测到 status='interrupt_after' 立即 break,
            # 不再进入下一轮 tick(). 中断语义由 run() 统一处理.

    async def resume(self, checkpoint_id: str) -> LoopResult:
        """从 checkpoint 恢复. 加载 → 设置 self.checkpoint → run().

        run() 检测到 self.checkpoint 已设置,跳过 _init_checkpoint().

        v3.1 B6 修复: 拒绝从 status='done' 的 checkpoint 恢复.
        Why: done 表示循环已正常结束,resume 只会触发空跑或重复终止.
        应抛 AEError 让用户明确知道无需 resume.
        """
        if self.store is None:
            raise AEError(
                ErrorCode.CHECKPOINT_LOAD_FAILED,
                "Cannot resume: no checkpoint store. Run the loop first.",
            )
        self.checkpoint = self.store.load_checkpoint(checkpoint_id)
        if self.checkpoint.status == "done":
            raise AEError(
                ErrorCode.CHECKPOINT_LOAD_FAILED,
                f"Cannot resume checkpoint {checkpoint_id}: status='done' (loop already completed)",
            )
        self.step = self.checkpoint.step + 1
        self.status = "pending"
        return await self.run()
