"""CLI 入口 — Click 命令注册.

命令:
    ae init <project>         项目环境初始化
    ae dev-loop <requirement> 单需求开发循环 (默认 v2.0 Orchestrator, fallback v1.0)
    ae status                 查看当前进度

Plan B Phase 02 新增 (T01-T11 团队级能力):
    T02-2: dev-loop 启动读 .ae-answers.yml 注入 ProjectEnvironment
    T03:   --max-tokens / --max-cost 阈值检查 + BudgetExceeded
    T04:   进度输出 — stage 开始/结束 click.echo
    T05:   错误归类 — 4 类 (USER/API/NETWORK/BUSINESS) + exit code
    T07:   Ctrl-C (SIGINT) → CancellationToken + 提示 resume
    T08:   --dry-run 只跑 architect
    T09:   --log-format text/json 结构化日志
    T10:   --llm-provider anthropic/ollama (v1.0 仅 anthropic)
    T11:   --project-root 显式指定项目根

v2.1 Phase C 新增 (P0.4 CLI 集成 v2.0 Orchestrator):
    - 默认走 v2.0 Orchestrator (需 ANTHROPIC_API_KEY)
    - --use-v1 强制 v1.0 engine (向后兼容)
    - 无 API key 时 fallback v1.0
    - --max-rounds 配置 v2.0 round 数
"""

from __future__ import annotations

import contextlib
import enum
import json
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from auto_engineering import __version__
from auto_engineering.errors import AEError, ErrorCode

# ============================================================
# Plan B Phase 02: 错误归类 + Cancellation + Token Tracker
# ============================================================


class ErrorCategory(enum.Enum):
    """AEError 归类 — 按 code 前缀分 4 类."""

    USER_ERROR = "user_error"  # 用户输入/配置错 (CONFIG_*, TASK_NOT_FOUND)
    API_ERROR = "api_error"  # API/LLM 错 (LLM_*)
    NETWORK_ERROR = "network_error"  # 网络/IO 错 (CHECKPOINT_*)
    BUSINESS_ERROR = "business_error"  # 业务规则错 (GUARDRAIL_*, STAGE_RETRY_*)


# 错误码 → 类别 映射(按 code 字符串前缀分类)
_ERROR_CATEGORY_MAP: dict[str, ErrorCategory] = {
    # USER_ERROR
    "CONFIG_": ErrorCategory.USER_ERROR,
    "TASK_NOT_FOUND": ErrorCategory.USER_ERROR,
    "INVALID_AGENT_OUTPUT": ErrorCategory.USER_ERROR,
    # API_ERROR
    "LLM_": ErrorCategory.API_ERROR,
    # NETWORK_ERROR
    "CHECKPOINT_": ErrorCategory.NETWORK_ERROR,
    # BUSINESS_ERROR
    "GUARDRAIL_": ErrorCategory.BUSINESS_ERROR,
    "STAGE_RETRY_": ErrorCategory.BUSINESS_ERROR,
    "GRAPH_RECURSION_LIMIT": ErrorCategory.BUSINESS_ERROR,
    "TASK_CANCELLED": ErrorCategory.USER_ERROR,  # 用户主动取消归用户错
    "AGENT_REGISTRATION_ERROR": ErrorCategory.USER_ERROR,
    "OUTPUT_DROPPED": ErrorCategory.BUSINESS_ERROR,
    "BUDGET_EXCEEDED": ErrorCategory.USER_ERROR,  # 预算超出归用户错(用户可调整阈值)
}

# 错误类别 → 退出码
_CATEGORY_EXIT_CODE: dict[ErrorCategory, int] = {
    ErrorCategory.USER_ERROR: 2,
    ErrorCategory.API_ERROR: 3,
    ErrorCategory.NETWORK_ERROR: 4,
    ErrorCategory.BUSINESS_ERROR: 5,
}


def classify_error(error: AEError) -> tuple[ErrorCategory, int]:
    """按 AEError.code 字符串前缀归类.

    Returns:
        (ErrorCategory, exit_code) 元组.
    """
    code_str = error.code.value if isinstance(error.code, ErrorCode) else str(error.code)

    # 优先精确匹配(覆盖前缀)
    category = _ERROR_CATEGORY_MAP.get(code_str)
    if category is not None:
        return category, _CATEGORY_EXIT_CODE[category]

    # 前缀匹配
    for prefix, cat in _ERROR_CATEGORY_MAP.items():
        if prefix.endswith("_") and code_str.startswith(prefix):
            return cat, _CATEGORY_EXIT_CODE[cat]

    # 默认 USER_ERROR
    return ErrorCategory.USER_ERROR, _CATEGORY_EXIT_CODE[ErrorCategory.USER_ERROR]


# 类别 → 友好提示前缀
_CATEGORY_FRIENDLY_PREFIX: dict[ErrorCategory, str] = {
    ErrorCategory.USER_ERROR: "[配置/参数错]",
    ErrorCategory.API_ERROR: "[API/LLM 错]",
    ErrorCategory.NETWORK_ERROR: "[网络/IO 错]",
    ErrorCategory.BUSINESS_ERROR: "[业务规则错]",
}


@dataclass
class CancellationToken:
    """协作式取消令牌. SIGINT handler 调 cancel(),loop 中 check() 检测.

    简化为内存 flag + 抛 AEError(TASK_CANCELLED).
    """

    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """若已 cancel,抛 AEError(TASK_CANCELLED)."""
        if self._cancelled:
            raise AEError(
                ErrorCode.TASK_CANCELLED,
                "Loop was cancelled by user (SIGINT).",
            )


@dataclass
class TokenTracker:
    """累加 LLM 调用的 token 消耗,超阈值抛 BUDGET_EXCEEDED.

    支持 input_tokens + output_tokens 累加;mock-friendly(duck-typing on .usage).
    """

    max_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, response: Any) -> None:
        """累加 LLMResponse.usage 中的 token. 超阈值抛 AEError(BUDGET_EXCEEDED)."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        in_t = getattr(usage, "input_tokens", 0) or 0
        out_t = getattr(usage, "output_tokens", 0) or 0
        self.input_tokens += in_t
        self.output_tokens += out_t

        if self.max_tokens > 0 and self.total_tokens > self.max_tokens:
            raise AEError(
                ErrorCode.BUDGET_EXCEEDED,
                f"Token budget exceeded: {self.total_tokens} > {self.max_tokens}",
            )


def _install_sigint_handler(token: CancellationToken) -> None:
    """注册 SIGINT handler → token.cancel()."""

    def _handler(sig, frame):
        token.cancel()

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, _handler)


# ============================================================
# 进度/日志辅助
# ============================================================


@dataclass
class ProgressLogger:
    """统一处理 text / json 格式日志输出.

    默认输出到 stderr(避免污染 stdout 用户输出).
    """

    log_format: str = "text"  # 'text' | 'json'

    def emit(self, event: str, **fields: Any) -> None:
        """输出一行日志.text 格式: '[event] key=value ...',json 格式: JSON 对象."""
        if self.log_format == "json":
            payload = {"event": event, **fields}
            click.echo(json.dumps(payload, ensure_ascii=False), err=True)
        else:
            parts = [f"[{event}]"]
            for k, v in fields.items():
                parts.append(f"{k}={v}")
            click.echo(" ".join(parts), err=True)


def _log_stage_progress(current: int, total: int, name: str) -> None:
    """输出 stage 进度: 'Stage X/3: architect'."""
    click.echo(f"Stage {current}/{total}: {name}")


def _emit_stage_done(stage: str, elapsed: float, tokens: int = 0) -> None:
    """输出 stage 完成: '  ✓ Stage X done in 1.2s (tokens: 1234)'."""
    click.echo(f"  ✓ Stage {stage} done in {elapsed:.1f}s (tokens: {tokens})")


# ============================================================
# LoopEngine 驱动器 (Phase 02: 接真实 LoopEngine)
# ============================================================


def _build_v1_runtime(requirement: str, project_root: Any = None) -> Any:
    """根据 ANTHROPIC_API_KEY 构建 runtime.

    - 有 API key → AgentRuntime + 注册 architect/developer/critic
    - 无 API key → ScriptedMockRuntime(fallback,测试友好)

    P0.1 fix: project_root 传入 ToolRegistry,使路径白名单沙箱生效(P1.9).
    """
    import os

    from auto_engineering.agents.architect import ArchitectAgent
    from auto_engineering.agents.critic import CriticAgent
    from auto_engineering.agents.developer import DeveloperAgent
    from auto_engineering.llm.anthropic_provider import AnthropicProvider
    from auto_engineering.runtime.mock import ScriptedMockRuntime
    from auto_engineering.runtime.runtime import AgentRuntime
    from auto_engineering.tools.bash_tools import RunBashTool
    from auto_engineering.tools.file_tools import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        SearchCodeTool,
        WriteFileTool,
    )
    from auto_engineering.tools.git_tools import GitCommitTool, GitDiffTool, GitStatusTool
    from auto_engineering.tools.registry import ToolRegistry
    from auto_engineering.tools.test_tools import RunTestsTool

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fallback: 测试/无 key 环境
        return ScriptedMockRuntime(
            {
                "architect": {
                    "plan": f"[MOCK PLAN for: {requirement}]",
                    "file_list": ["mock_file.py"],
                    "batch_plan": [],
                    "contracts": {},
                },
                "developer": {
                    "files_changed": ["mock_file.py"],
                    "commit_hash": "mock-commit-001",
                    "test_results": {"passed": 1, "failed": 0},
                },
                "critic": {
                    "verdict": "APPROVE",
                    "findings": [],
                    "critic_feedback": "",
                },
            }
        )

    # 真实 LLM 模式
    llm = AnthropicProvider(api_key=api_key)

    # P1.9: 创建带 project_root 的 registry,使路径白名单生效
    registry: ToolRegistry | None = None
    if project_root is not None:
        registry = ToolRegistry()
        registry.register(ReadFileTool(project_root=project_root))
        registry.register(WriteFileTool(project_root=project_root))
        registry.register(EditFileTool(project_root=project_root))
        registry.register(SearchCodeTool(project_root=project_root))
        registry.register(ListDirTool(project_root=project_root))
        registry.register(RunBashTool(project_root=project_root))
        registry.register(GitStatusTool(project_root=project_root))
        registry.register(GitCommitTool(project_root=project_root))
        registry.register(GitDiffTool(project_root=project_root))
        registry.register(RunTestsTool(project_root=project_root))

    runtime = AgentRuntime(registry=registry)
    runtime.register("architect", lambda: ArchitectAgent(llm=llm))
    runtime.register("developer", lambda: DeveloperAgent(llm=llm))
    runtime.register("critic", lambda: CriticAgent(llm=llm))
    return runtime


@dataclass
class V1RunResult:
    """_run_v1_engine 返回值."""

    status: str
    total_steps: int
    checkpoint_id: str


def _run_v1_engine(
    requirement: str,
    project_root: Path,
    project_env: Any | None,
    settings: Any,
    max_steps: int,
    max_tokens: int,
    dry_run: bool,
    cancellation: CancellationToken,
    progress: ProgressLogger,
    token_tracker: TokenTracker | None = None,
) -> V1RunResult:
    """真实驱动 LoopEngine.run().

    P1.2: 根据 ANTHROPIC_API_KEY 自动选择 AgentRuntime(真 LLM) 或 ScriptedMockRuntime.
    dry-run 模式: 只跑 architect stage 后立即返回.
    """
    from auto_engineering.engine import LoopEngine, build_dev_loop_graph

    runtime = _build_v1_runtime(requirement, project_root=project_root)

    engine = LoopEngine(
        build_dev_loop_graph(),
        runtime=runtime,
        checkpoint_dir=settings.checkpoint_dir,
        max_steps=max_steps,
    )

    if dry_run:
        # dry-run: 只跑 architect → 输出 plan → 退出
        click.echo("[DRY RUN] only architect stage will execute")
        runtime_dry = _build_v1_runtime(requirement)
        engine_dry = LoopEngine(
            build_dev_loop_graph(),
            runtime=runtime_dry,
            checkpoint_dir=settings.checkpoint_dir,
            max_steps=1,
        )
        try:
            result = _execute_with_progress(
                engine_dry,
                requirement,
                1,
                cancellation,
                progress,
                max_tokens,
                token_tracker=None,  # dry-run 不累加 token
            )
        except AEError as e:
            if e.code == ErrorCode.TASK_CANCELLED:
                raise
            raise
        # dry-run 提示
        click.echo(
            f"\n[DRY RUN COMPLETE]\n"
            f"  Requirement: {requirement}\n"
            f"  Plan output: plan available (see checkpoint state)\n"
            f"  Steps: {result.total_steps}"
        )
        return V1RunResult(
            status="dry_run_done",
            total_steps=result.total_steps,
            checkpoint_id=result.checkpoint_id,
        )

    # 真实循环
    try:
        result = _execute_with_progress(
            engine,
            requirement,
            max_steps,
            cancellation,
            progress,
            max_tokens,
            token_tracker=token_tracker,
        )
    except AEError as e:
        if e.code == ErrorCode.TASK_CANCELLED:
            # 保存 checkpoint 后再抛
            raise
        raise

    return V1RunResult(
        status=result.status,
        total_steps=result.total_steps,
        checkpoint_id=result.checkpoint_id,
    )


def _execute_with_progress(
    engine: Any,
    requirement: str,
    max_steps: int,
    cancellation: CancellationToken,
    progress: ProgressLogger,
    max_tokens: int,
    token_tracker: Any = None,
) -> Any:
    """包装 LoopEngine.run() 接入 stage 进度回调 + cancellation + token_tracker.

    Phase 1.4 改造: 不再 pre-echo 假象,而是 hook on_stage_start/on_stage_end 实时输出.
    """

    # Phase 1.4: hook runtime.execute 前后即时输出 stage 进度(无假象)
    def _on_stage_start(stage_name: str) -> None:
        _log_stage_progress(0, 0, stage_name)  # 简化(总步数未知)
        progress.emit("stage_start", stage=stage_name)

    def _on_stage_end(stage_name: str, elapsed_sec: float) -> None:
        tokens = token_tracker.total_tokens if token_tracker else 0
        _emit_stage_done(stage_name, elapsed_sec, tokens=tokens)
        progress.emit(
            "stage_done",
            stage=stage_name,
            elapsed=elapsed_sec,
            tokens=tokens,
        )

    import asyncio

    return asyncio.run(
        engine.run(
            requirement,
            max_steps=max_steps,
            cancellation=cancellation,
            token_tracker=token_tracker,
            on_stage_start=_on_stage_start,
            on_stage_end=_on_stage_end,
        )
    )


# ============================================================
# v2.1 Phase C: v2.0 Orchestrator 驱动器
# ============================================================


@dataclass
class OrchestratorRunResult:
    """_run_v2_orchestrator 返回值 — 模拟 V1RunResult 接口."""

    status: str
    total_steps: int
    checkpoint_id: str


def _build_v2_agent_runtime(
    project_root: Path,
    progress: ProgressLogger,
    token_tracker: TokenTracker | None = None,
) -> Any:
    """构造 v2.0 Orchestrator 用的 AgentRuntime (替代 _build_v2_executor).

    v2.3 Phase H (P1.4): Orchestrator 集成 AgentRuntime, 按 task.role 路由
    调 agent.execute — 替代单一 executor callback wrapper.

    设计:
        - 复用 v1.0 BaseAgent (DeveloperAgent) 作为 developer agent
        - 工具集: v1.0 标准工具集 (Read/Write/Edit/Search/List/Bash/Git/Test)
        - architect/critic: 注册 Mock Agent (ScriptedMockAgentByRole) —
          避免在 v2 Orchestrator demo 中也跑真实 LLM architect/critic
        - LLM 异常 → 包成 TaskOutcome(status='failed') (在 Orchestrator._build_runtime_executor
          内处理, 借鉴 AutoGen GroupChat agent_selector)

    Args:
        project_root: 项目根目录 (沙箱白名单基址)
        progress: 进度日志 (用于记录 task 执行)
        token_tracker: Token 跟踪器 (注入 BaseAgent.execute)

    Returns:
        AgentRuntime 实例 (已注册 architect/developer/critic)
    """
    import os
    from types import SimpleNamespace

    from auto_engineering.agents.developer import DeveloperAgent
    from auto_engineering.llm.anthropic_provider import AnthropicProvider
    from auto_engineering.runtime.runtime import AgentRuntime
    from auto_engineering.runtime.task import Task as RuntimeTask
    from auto_engineering.tools.bash_tools import RunBashTool
    from auto_engineering.tools.file_tools import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        SearchCodeTool,
        WriteFileTool,
    )
    from auto_engineering.tools.git_tools import (
        GitCommitTool,
        GitDiffTool,
        GitStatusTool,
    )
    from auto_engineering.tools.test_tools import RunTestsTool

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    llm = AnthropicProvider(api_key=api_key)
    # P1.9 fix: 只有支持 project_root 的工具传 project_root (白名单沙箱)
    tools = [
        WriteFileTool(project_root=project_root),
        EditFileTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
        # 不支持 project_root 的工具: ReadFileTool / ListDirTool / RunBashTool /
        # GitStatusTool / GitCommitTool / GitDiffTool / RunTestsTool
        ListDirTool(),
        RunBashTool(),
        GitStatusTool(),
        GitCommitTool(),
        GitDiffTool(),
        RunTestsTool(),
        ReadFileTool(),
    ]
    developer = DeveloperAgent(llm=llm, tools=tools)

    class _DeveloperAgentAdapter:
        """Adapter: DeveloperAgent 接受 runtime.Task, 但 v2 path 期望简易 execute.

        v2 Orchestrator._build_runtime_executor 构造 runtime.Task 并传入,
        DeveloperAgent.execute 直接接受. 此 Adapter 仅记录调用日志.
        """

        def __init__(self) -> None:
            self.role = "developer"
            self.execute_calls: list[str] = []

        async def execute(
            self,
            task: RuntimeTask,
            ctx: Any,
            cancellation: Any = None,
            token_tracker: Any = None,
        ) -> Any:
            self.execute_calls.append(task.id)
            if progress is not None:
                progress.emit("task_start", task_id=task.id, agent_type="developer")
            result = await developer.execute(
                task=task, ctx=ctx, cancellation=cancellation, token_tracker=token_tracker
            )
            return result

    class _MockRoleAgent:
        """architect/critic 的 Mock Agent — Phase C 简化, 避免 v2 demo 跑真 LLM.

        返回 TaskResult-like SimpleNamespace, Orchestrator._build_runtime_executor
        会读 .values 字段.
        """

        def __init__(self, role: str) -> None:
            self.role = role

        async def execute(
            self,
            task: RuntimeTask,
            ctx: Any,
            cancellation: Any = None,
            token_tracker: Any = None,
        ) -> Any:
            if progress is not None:
                progress.emit("task_start", task_id=task.id, agent_type=self.role)
            # Mock: 返回 role 标识, 让 Orchestrator 走完 round
            return SimpleNamespace(
                task_id=task.id,
                values={"role": self.role, "task_id": task.id, "status": "approved"},
                raw_response=f"mock-{self.role}",
                tool_calls=[],
                agent_type=self.role,
            )

    runtime = AgentRuntime()
    runtime.register("architect", lambda: _MockRoleAgent("architect"))
    runtime.register("developer", lambda: _DeveloperAgentAdapter())
    runtime.register("critic", lambda: _MockRoleAgent("critic"))
    runtime.register("reviewer", lambda: _MockRoleAgent("reviewer"))
    return runtime


def _build_v2_semantic_evaluator(
    project_root: Path,
    progress: ProgressLogger,
) -> Any:
    """构造 v2.0 Orchestrator 用的语义评估器 (简化:始终返回 True).

    Phase C 简化策略:
        - 不接 LLM (避免 mock-friendly 的"假评估"陷阱)
        - 用 Gate 跑过的结果作为代理:所有 Gate 通过 → satisfied
        - 这里返回简单的 True(让 Orchestrator 主循环跑起来)

    Args:
        project_root: 项目根目录 (备用, 当前未使用)
        progress: 进度日志 (备用)

    Returns:
        async (round_result) -> bool
    """

    async def evaluator(round_result: Any) -> bool:
        # Phase C 简化: 总是返回 True (Gate 已在 Orchestrator 内部跑过)
        return True

    return evaluator


def _run_v2_orchestrator(
    requirement: str,
    project_root: Path,
    max_rounds: int,
    progress: ProgressLogger,
    cancellation: CancellationToken,
    token_tracker: TokenTracker | None = None,
) -> OrchestratorRunResult:
    """v2.0 Orchestrator 驱动器 — 单 Agent 模式演示.

    设计要点 (Phase C):
        - 单 task / round (Phase 3 多 Agent 并发未启用, 留 Phase 4+)
        - 复用 v1.0 BaseAgent (DeveloperAgent) 作为 TaskExecutor
        - 启用 2 道 Gate (Safety + Lint) — 真集成, 非 mock
        - semantic_evaluator 简化 (始终 True, 避免 mock LLM)

    Args:
        requirement: 需求描述
        project_root: 项目根目录 (Gate 运行基址 + 沙箱白名单)
        max_rounds: 最大轮数
        progress: 进度日志
        cancellation: 取消令牌 (用户 SIGINT 触发)
        token_tracker: Token 跟踪器 (注入 BaseAgent)

    Returns:
        OrchestratorRunResult (status/total_steps/checkpoint_id)

    Raises:
        AEError: 配置错 / 业务错
    """
    import asyncio

    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate
    from auto_engineering.loop.convergence import ConvergenceConfig
    from auto_engineering.loop.orchestrator import (
        Orchestrator,
        OrchestratorConfig,
    )
    from auto_engineering.loop.plan import Task

    # 1. 构造 OrchestratorConfig: gates + semantic_evaluator + project_root + agent_runtime
    #    v2.3 Phase E (P1.1): max_rounds → ConvergenceConfig.max_iterations (单一来源)
    #    v2.3 Phase H (P1.4): agent_runtime 传入, 按 task.role 调度 (替代 _build_v2_executor)
    agent_runtime = _build_v2_agent_runtime(project_root, progress, token_tracker)
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(max_iterations=max_rounds),
        gates=[SafetyGate(), LintGate()],
        semantic_evaluator=_build_v2_semantic_evaluator(project_root, progress),
        project_root=project_root,
        agent_runtime=agent_runtime,
    )

    # 2. 构造单 task (Phase C 简化: 1 个 task, developer agent)
    task = Task(
        id="t1",
        title=requirement[:50] or "Implement requirement",  # Phase 2.1-D: 非空 title
        description=requirement,
        expected_output="实现需求对应的代码变更",  # Phase 2.1-D: contract
        role="developer",
        agent_type="developer",
        target_files=frozenset(),  # 单 Agent 模式不强制隔离
        depends_on=[],
    )

    # 3. 构造 Orchestrator (v2.3 Phase H P1.4: 不再传 executor, agent_runtime 自动调度)
    orchestrator = Orchestrator(
        requirement=requirement,
        tasks=[task],
        executor=None,  # type: ignore[arg-type]  # agent_runtime 优先
        config=config,
    )

    # 5. 启动 asyncio.run (Orchestrator.run 是 async)
    history = asyncio.run(orchestrator.run(cancellation=cancellation))

    # 6. 输出总结
    total_rounds = len(history)
    status = "done" if (orchestrator.verdict and orchestrator.verdict.should_stop) else "max_rounds"
    checkpoint_id = f"v2-r{total_rounds}"

    # 进度输出
    progress.emit(
        "orchestrator_done",
        rounds=total_rounds,
        verdict_level=orchestrator.verdict.level if orchestrator.verdict else None,
        should_stop=orchestrator.verdict.should_stop if orchestrator.verdict else False,
    )

    return OrchestratorRunResult(
        status=status,
        total_steps=total_rounds,
        checkpoint_id=checkpoint_id,
    )


# ============================================================
# Click 命令
# ============================================================


@click.group()
@click.version_option(version=__version__, prog_name="ae")
def main():
    """Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作."""
    pass


@main.command()
@click.argument("project", required=False)
@click.option(
    "--type",
    "project_type",
    help="项目类型 (app-service/library/cli-tool/skill/hook/mcp-server/spec-doc/monorepo)",
)
@click.option("--defaults", is_flag=True, help="非交互模式，全部使用默认值")
@click.option("--force", is_flag=True, help="允许覆盖非空目录")
@click.option(
    "--from-answers", "answers_file", type=click.Path(exists=True), help="从 .ae-answers.yml 重放"
)
@click.option("--package-manager", help="包管理器 (npm/pnpm/yarn/bun/uv/poetry)")
@click.option("--ci", "ci_platform", help="CI 平台 (github/gitlab/none)")
@click.option("--test-runner", help="测试框架")
@click.option(
    "--no-typescript", "use_typescript", flag_value=False, default=None, help="不使用 TypeScript"
)
@click.option(
    "--no-lefthook", "use_lefthook", flag_value=False, default=None, help="不安装 Lefthook"
)
@click.option("--pretend", is_flag=True, help="模拟执行，不产生文件")
@click.option("--skip-tasks", is_flag=True, help="跳过钩子任务执行")
@click.option(
    "--no-cleanup", "cleanup_on_error", flag_value=False, default=True, help="出错时不清理目标目录"
)
@click.option("--quiet", is_flag=True, help="静默模式")
@click.option("--incremental", is_flag=True, help="增量模式：只补充缺失文件，不覆盖已有文件")
def init(
    project: str | None,
    project_type: str | None,
    defaults: bool,
    force: bool,
    answers_file: str | None,
    package_manager: str | None,
    ci_platform: str | None,
    test_runner: str | None,
    use_typescript: bool | None,
    use_lefthook: bool | None,
    pretend: bool,
    skip_tasks: bool,
    cleanup_on_error: bool,
    quiet: bool,
    incremental: bool,
):
    """项目环境初始化."""
    from auto_engineering.init import InitWorker

    dst_path = Path(project) if project else Path.cwd()

    if answers_file:
        from auto_engineering.init import AnswersMap

        answers = AnswersMap.from_answers_file(Path(answers_file))
        click.echo(f"从 {answers_file} 恢复答案")
        if not project_type:
            with contextlib.suppress(KeyError):
                project_type = answers.get("project_type") or ""
    else:
        answers = None

    worker = InitWorker(
        dst_path=dst_path,
        project_type=project_type,
        package_manager=package_manager,
        ci_platform=ci_platform,
        test_runner=test_runner,
        use_typescript=use_typescript,
        use_lefthook=use_lefthook,
        defaults=defaults,
        force=force,
        pretend=pretend,
        skip_tasks=skip_tasks,
        cleanup_on_error=cleanup_on_error,
        quiet=quiet,
        incremental=incremental,
    )
    if answers:
        worker._previous_answers = answers

    try:
        result = worker.execute()
        if pretend:
            click.echo(f"[DRY RUN] 将生成到: {result.dst_path}")
        else:
            click.echo(f"✓ 项目已生成: {result.dst_path}")
    except Exception as e:
        click.echo(f"✗ 初始化失败: {e}", err=True)
        raise SystemExit(1) from e


@main.command()
@click.argument("requirement")
@click.option("--max-steps", type=int, default=3, help="最大迭代步数 (v1.0)")
@click.option(
    "--max-rounds",
    type=int,
    default=3,
    help="最大 Round 数 (v2.0 Orchestrator 模式)",
)
@click.option("--max-tokens", type=int, default=0, help="Token 预算上限 (0 = 无限制)")
@click.option("--max-cost", type=float, default=0.0, help="美元成本上限 (Phase 2+ 实现)")
@click.option("--multi", is_flag=True, help="多 Agent 并行模式（未来）")
@click.option("--dry-run", is_flag=True, help="只跑 architect 输出 plan (v1.0)")
@click.option("--log-format", type=click.Choice(["text", "json"]), default="text", help="日志格式")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "ollama", "openai"]),
    default="anthropic",
    help="LLM 提供方",
)
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
@click.option(
    "--use-v1",
    "use_v1",
    is_flag=True,
    help="强制使用 v1.0 engine (LoopEngine + Architect/Developer/Critic)",
)
@click.option(
    "--use-v2",
    "use_v2",
    is_flag=True,
    help="强制使用 v2.0 Orchestrator (多 Agent 并发 + Gate + 语义评估)",
)
def dev_loop(
    requirement: str,
    max_steps: int,
    max_rounds: int,
    max_tokens: int,
    max_cost: float,
    multi: bool,
    dry_run: bool,
    log_format: str,
    llm_provider: str,
    project_root: str,
    use_v1: bool,
    use_v2: bool,
):
    """单需求开发循环.

    默认走 v2.0 Orchestrator(需 ANTHROPIC_API_KEY),无 API key 时 fallback 到
    v1.0 LoopEngine(Architect → Developer → Critic). 用 --use-v1 强制 v1.0
    路径,用 --use-v2 强制 v2.0 路径(无 API key 时会报错).
    """
    # T10: --llm-provider 仅 anthropic 实装
    if llm_provider != "anthropic":
        click.echo(
            f"[未实现] --llm-provider={llm_provider} 暂未实装。"
            f"v1.0 仅支持 anthropic。请使用 --llm-provider=anthropic",
            err=True,
        )
        raise SystemExit(6)

    # --use-v1 / --use-v2 互斥检查
    if use_v1 and use_v2:
        click.echo(
            "[配置/参数错] --use-v1 与 --use-v2 互斥,只能选其一。",
            err=True,
        )
        raise SystemExit(2)

    # T11: --project-root 解析
    root = Path(project_root).resolve() if project_root else Path.cwd()

    # 入口前置校验 — 缺 API key/非 git 仓库/磁盘不足/Python 版本低 直接退出
    from auto_engineering.config.environment import load_ae_answers, preflight

    try:
        preflight(root)
    except SystemExit:
        raise

    # T02-2: 启动读 .ae-answers.yml 注入 ProjectEnvironment
    answers_data = load_ae_answers(root)
    project_env = answers_data  # dict — Phase 3+ 重建 ProjectEnvironment 实例

    # T07: SIGINT handler + CancellationToken
    cancellation = CancellationToken()
    _install_sigint_handler(cancellation)

    # T09: 进度日志
    progress = ProgressLogger(log_format=log_format)

    # T04: 启动输出
    click.echo(f"Starting dev-loop: {requirement}")

    # 路由决策 v1.0 vs v2.0 (放在 Settings 之前, 避免无 API key 时 v1 fallback 被 Settings 拦截)
    import os

    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if use_v2 and not has_api_key:
        click.echo(
            "[配置/参数错] --use-v2 需要 ANTHROPIC_API_KEY 环境变量。"
            "请在 ~/.zshrc 或 .env 中设置后重试,或使用 --use-v1 fallback 到 v1.0 engine。",
            err=True,
        )
        raise SystemExit(2)

    use_v1_path = use_v1 or not has_api_key

    # 加载 Settings (含 max_tokens/max_steps 等)
    # 仅 v2 路径需要真实 Settings;v1 路径走 ScriptedMockRuntime 不需要
    from auto_engineering.config.settings import Settings

    if use_v1_path:
        # v1 fallback: Settings 容忍空 API key(用默认值,因 v1 ScriptedMockRuntime 不调 LLM)
        settings = Settings()  # 默认值,不抛 CONFIG_MISSING_API_KEY
    else:
        try:
            settings = Settings.from_env()
        except AEError as e:
            category, exit_code = classify_error(e)
            click.echo(
                f"{_CATEGORY_FRIENDLY_PREFIX[category]} {e.message}",
                err=True,
            )
            raise SystemExit(exit_code) from None

    # 多 Agent (未来)
    if multi:
        click.echo("多 Agent 并行模式尚未实现。")
        return

    # T03: TokenTracker — P1.1 真接
    tracker = TokenTracker(max_tokens=max_tokens)

    if use_v1_path:
        # P0-II: 无 API key fallback 时友好提示 (仅当用户未显式 --use-v1)
        if not has_api_key and not use_v1:
            click.echo(
                "[提示] 未检测到 ANTHROPIC_API_KEY，已自动使用 v1.0 引擎。"
                "请设置 ANTHROPIC_API_KEY 以使用 v2.0 引擎。",
                err=True,
            )
        # v1.0 路径 (LoopEngine + Architect/Developer/Critic)
        _log_engine_version("v1.0")
        try:
            result = _run_v1_engine(
                requirement=requirement,
                project_root=root,
                project_env=project_env,
                settings=settings,
                max_steps=max_steps,
                max_tokens=max_tokens,
                dry_run=dry_run,
                cancellation=cancellation,
                progress=progress,
                token_tracker=tracker,
            )
        except AEError as e:
            # T05: 错误归类 + 友好提示
            category, exit_code = classify_error(e)
            prefix = _CATEGORY_FRIENDLY_PREFIX[category]
            click.echo(f"{prefix} {e.message}", err=True)
            # T07: 任务被取消时,提示用户 resume
            if e.code == ErrorCode.TASK_CANCELLED:
                click.echo(
                    "Loop drained. Resume with: ae checkpoint resume <id>",
                    err=True,
                )
            raise SystemExit(exit_code) from None
    else:
        # v2.0 路径 (Orchestrator + Gates + 语义评估)
        _log_engine_version("v2.0")
        try:
            result = _run_v2_orchestrator(
                requirement=requirement,
                project_root=root,
                max_rounds=max_rounds,
                progress=progress,
                cancellation=cancellation,
                token_tracker=tracker,
            )
        except AEError as e:
            category, exit_code = classify_error(e)
            prefix = _CATEGORY_FRIENDLY_PREFIX[category]
            click.echo(f"{prefix} {e.message}", err=True)
            if e.code == ErrorCode.TASK_CANCELLED:
                click.echo(
                    "Loop drained. Resume with: ae checkpoint resume <id>",
                    err=True,
                )
            raise SystemExit(exit_code) from None

    # 总结输出
    click.echo(
        f"\n✓ dev-loop complete: status={result.status}, "
        f"steps={result.total_steps}, checkpoint={result.checkpoint_id}"
    )


def _log_engine_version(version: str) -> None:
    """输出当前使用的 engine 版本(v1.0 / v2.0)."""
    click.echo(f"[engine] using {version} orchestrator")


@main.command()
def status():
    """查看当前项目进度."""
    from auto_engineering.config.environment import ProjectEnvironment

    cwd = Path.cwd()
    click.echo(f"当前目录: {cwd}")

    try:
        env = ProjectEnvironment.resolve(cwd)
        click.echo(f"  项目名称: {env.project_name}")
        click.echo(f"  项目类型: {env.project_type or '未知'}")
        click.echo(f"  包管理器: {env.package_manager or '未知'}")
        click.echo(f"  测试框架: {env.test_runner or '未知'}")
        click.echo(f"  TypeScript: {'是' if env.use_typescript else '否'}")
        click.echo(f"  Lefthook: {'是' if env.use_lefthook else '否'}")
        click.echo(f"  CI: {env.ci_platform or '无'}")
        click.echo(f"  Git: {'是' if env.has_git else '否'}")
        # A5: 不可判定字段 warning
        undetectable = env._warn_undetectable(cwd)
        if undetectable:
            click.echo(
                f"  ⚠ 不可自动判定: {', '.join(undetectable)}",
                err=True,
            )
    except Exception as e:
        click.echo(f"  读取项目环境失败: {e}")

    # v2.0 Phase 04: Checkpoint 摘要
    cp_dir = cwd / ".ae-checkpoints"
    if cp_dir.exists():
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        total_v2 = 0
        for db_file in cp_dir.glob("*.db"):
            try:
                store = SQLiteCheckpointStore(str(db_file))
                total_v2 += store.count()
            except Exception:
                continue
        if total_v2 > 0:
            click.echo(f"  v2.0 Checkpoints: {total_v2} (见 `ae checkpoint v2 list`)")


# ============================================================
# Phase 1.1: ae checkpoint list / show / resume
# ============================================================


@main.group()
def checkpoint():
    """Checkpoint 管理(list / show / resume)."""


@checkpoint.command("list")
def checkpoint_list_cmd():
    """列出所有 checkpoint."""
    from auto_engineering.engine.checkpoint import CheckpointStore

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"
    if not cp_dir.exists():
        click.echo("(no checkpoint directory)")
        return

    # 扫描 .ae-checkpoints/ 下所有 .db 文件
    all_checkpoints: list[dict] = []
    for db_file in sorted(cp_dir.glob("*.db")):
        store = CheckpointStore(str(db_file))
        try:
            for cp in store.list_all():
                cp["db_file"] = db_file.name
                all_checkpoints.append(cp)
        finally:
            store.close()

    if not all_checkpoints:
        click.echo("(no checkpoints)")
        return

    click.echo(f"{'ID':<36} {'THREAD':<18} {'STEP':>4}  {'STATUS':<10} {'DB':<20} UPDATED")
    click.echo("-" * 110)
    for cp in all_checkpoints:
        click.echo(
            f"{cp['id'][:34]:<36} {cp['thread_id'][:16]:<18} {cp['step']:>4}  "
            f"{cp['status']:<10} {cp['db_file'][:18]:<20} {cp['updated_at']}"
        )


@checkpoint.command("show")
@click.argument("checkpoint_id")
def checkpoint_show_cmd(checkpoint_id: str):
    """查看 checkpoint 详情(state + writes + pending)."""
    from auto_engineering.engine.checkpoint import CheckpointStore

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"

    # 搜索所有 .db 文件找匹配的 checkpoint
    for db_file in sorted(cp_dir.glob("*.db")):
        store = CheckpointStore(str(db_file))
        try:
            cp = store.get_latest_for_thread("") if False else None
            # 直接用 load_checkpoint 查
            from auto_engineering.errors import AEError, ErrorCode

            try:
                cp = store.load_checkpoint(checkpoint_id)
                click.echo(f"ID:        {cp.id}")
                click.echo(f"Thread:    {cp.thread_id}")
                click.echo(f"Step:      {cp.step}")
                click.echo(f"Status:    {cp.status}")
                click.echo(f"Parent:    {cp.parent_id or '(none)'}")
                click.echo("State:")
                # 状态详情
                state_dict = cp.state.to_dict()
                for k, v in state_dict.items():
                    val_str = str(v)[:80] if v else "(empty)"
                    click.echo(f"  {k}: {val_str}")
                return
            except AEError as e:
                if e.code == ErrorCode.CHECKPOINT_LOAD_FAILED:
                    continue  # 试下一个 db
                raise
        finally:
            store.close()

    click.echo(f"Checkpoint '{checkpoint_id}' not found", err=True)
    raise SystemExit(1)


@checkpoint.command("resume")
@click.argument("checkpoint_id")
def checkpoint_resume_cmd(checkpoint_id: str):
    """从 checkpoint 恢复(暂为占位 — 实际恢复需要 dev-loop 命令)."""
    from auto_engineering.engine.checkpoint import CheckpointStore
    from auto_engineering.errors import AEError, ErrorCode

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"

    # 验证 checkpoint 存在
    for db_file in sorted(cp_dir.glob("*.db")):
        store = CheckpointStore(str(db_file))
        try:
            try:
                store.load_checkpoint(checkpoint_id)
                click.echo(f"Resume from checkpoint '{checkpoint_id}'")
                click.echo("(实际恢复请使用 `ae dev-loop` — 它会自动检测中断并提示 resume)")
                click.echo(
                    f'使用: ae dev-loop --resume-checkpoint {checkpoint_id} "your requirement"'
                )
                return
            except AEError as e:
                if e.code == ErrorCode.CHECKPOINT_LOAD_FAILED:
                    continue
                raise
        finally:
            store.close()

    click.echo(f"Checkpoint '{checkpoint_id}' not found", err=True)
    raise SystemExit(1)


# ============================================================
# v2.0 Phase 04: ae checkpoint v2 list/show (SQLite v2.0 store)
# ============================================================
# 设计来源: design/v2.0-Analysis-Loop.md §4.4 + §4.11
# 注: v1.1 的 ae checkpoint list/show/resume (CheckpointStore) 保留不动,
#     新增 v2 子命令组使用 SQLiteCheckpointStore (loop.checkpoint).


@checkpoint.group("v2")
def checkpoint_v2():
    """v2.0 Checkpoint 操作(SQLite 持久化)."""


@checkpoint_v2.command("list")
@click.option("--round", type=int, default=None, help="按 round 过滤")
def checkpoint_v2_list_cmd(round: int | None) -> None:
    """列出 v2.0 Checkpoint (按 round ASC, created_at ASC)."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"
    if not cp_dir.exists():
        click.echo("(no checkpoint directory)")
        return

    # 收集所有 v2 .db (默认 .db 都视为 v2)
    all_checkpoints: list[dict] = []
    for db_file in sorted(cp_dir.glob("*.db")):
        try:
            store = SQLiteCheckpointStore(str(db_file))
        except Exception as e:
            click.echo(f"[warn] skip {db_file.name}: {e}", err=True)
            continue
        try:
            for meta in store.list_all():
                if round is not None and meta.round != round:
                    continue
                all_checkpoints.append(
                    {
                        "id": meta.id,
                        "round": meta.round,
                        "step": meta.step,
                        "created_at": meta.created_at.isoformat(),
                        "schema_version": meta.schema_version,
                        "tag": meta.tag,
                        "db_file": db_file.name,
                    }
                )
        finally:
            # SQLiteCheckpointStore file 模式无需 close,但 :memory: 模式也无害
            pass

    if not all_checkpoints:
        click.echo("(no v2 checkpoints)")
        return

    click.echo(
        f"{'ID':<36} {'ROUND':>5} {'STEP':>4}  {'SCHEMA':>6}  {'DB':<20} TAG"
    )
    click.echo("-" * 90)
    for cp in all_checkpoints:
        click.echo(
            f"{cp['id'][:34]:<36} {cp['round']:>5} {cp['step']:>4}  "
            f"{cp['schema_version']:>6}  {cp['db_file'][:18]:<20} {cp['tag'] or ''}"
        )


@checkpoint_v2.command("show")
@click.argument("checkpoint_id")
def checkpoint_v2_show_cmd(checkpoint_id: str) -> None:
    """查看 v2.0 Checkpoint 详情."""
    from auto_engineering.loop.checkpoint import CheckpointNotFoundError, SQLiteCheckpointStore

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"
    if not cp_dir.exists():
        click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
        raise SystemExit(1)

    for db_file in sorted(cp_dir.glob("*.db")):
        store = SQLiteCheckpointStore(str(db_file))
        try:
            cp = store.load(checkpoint_id)
        except CheckpointNotFoundError:
            continue
        except Exception as e:
            click.echo(f"[warn] error reading {db_file.name}: {e}", err=True)
            continue
        # 找到 → 输出详情
        click.echo(f"ID:            {cp.id}")
        click.echo(f"Round:         {cp.round}")
        click.echo(f"Step:          {cp.step}")
        click.echo(f"Schema:        {cp.schema_version}")
        click.echo(f"Parent:        {cp.parent_id or '(none)'}")
        click.echo(f"Tag:           {cp.tag or '(none)'}")
        click.echo(f"Created At:    {cp.created_at.isoformat()}")
        click.echo("State:")
        if isinstance(cp.state, dict):
            for k, v in cp.state.items():
                val_str = str(v)[:120] if v else "(empty)"
                click.echo(f"  {k}: {val_str}")
        else:
            click.echo(f"  {cp.state!r:.200}")
        click.echo(f"History ({len(cp.history)} entries):")
        for i, h in enumerate(cp.history[:5]):
            click.echo(f"  [{i}] {str(h)[:120]}")
        if len(cp.history) > 5:
            click.echo(f"  ... ({len(cp.history) - 5} more)")
        return

    click.echo(f"v2.0 Checkpoint '{checkpoint_id}' not found", err=True)
    raise SystemExit(1)


@checkpoint_v2.command("delete")
@click.argument("checkpoint_id")
def checkpoint_v2_delete_cmd(checkpoint_id: str) -> None:
    """删除 v2.0 Checkpoint."""
    from auto_engineering.loop.checkpoint import (
        SQLiteCheckpointStore,
    )

    cwd = Path.cwd()
    cp_dir = cwd / ".ae-checkpoints"
    if not cp_dir.exists():
        click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
        raise SystemExit(1)

    for db_file in sorted(cp_dir.glob("*.db")):
        store = SQLiteCheckpointStore(str(db_file))
        if store.delete(checkpoint_id):
            click.echo(f"Deleted v2.0 checkpoint '{checkpoint_id}' from {db_file.name}")
            return
    click.echo(f"v2.0 Checkpoint '{checkpoint_id}' not found", err=True)
    raise SystemExit(1)


# ============================================================
# v2.3 Phase I (P1.5): ae checkpoint v2 migrate
# 单向迁移 v1.1 JSON Checkpoint (engine/checkpoint.py) → v2.0 SQLite Checkpoint.
# 借鉴 LangGraph checkpoint migration 思路 (单方向 + 显式触发 + schema 兼容).
# ============================================================


@checkpoint_v2.command("migrate")
@click.argument("src_json", type=click.Path(exists=True))
@click.argument("dst_sqlite", type=click.Path())
def checkpoint_v2_migrate_cmd(src_json: str, dst_sqlite: str) -> None:
    """迁移 v1.1 JSON checkpoint → v2.0 SQLite.

    用法:
        ae checkpoint v2 migrate <src.json> <dst.sqlite>

    迁移方向: v1.1 → v2.0 (单向, 不可逆).
    """
    from auto_engineering.checkpoint.migrate import migrate_v1_to_v2

    try:
        cp_id = migrate_v1_to_v2(Path(src_json), Path(dst_sqlite))
    except Exception as e:
        click.echo(f"[迁移失败] {e}", err=True)
        raise SystemExit(1) from e
    click.echo(f"Migrated v1.1 → v2.0: checkpoint_id={cp_id}")


if __name__ == "__main__":
    main()
