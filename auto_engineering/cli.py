"""CLI 入口 — Click 命令注册.

命令:
    ae init <project>         项目环境初始化
    ae dev-loop <requirement> 单需求开发循环 (Plan B Phase 02 接 LoopEngine)
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


def _build_runtime(requirement: str) -> Any:
    """根据 ANTHROPIC_API_KEY 构建 runtime.

    - 有 API key → AgentRuntime + 注册 architect/developer/critic
    - 无 API key → ScriptedMockRuntime(fallback,测试友好)
    """
    import os

    from auto_engineering.agents.architect import ArchitectAgent
    from auto_engineering.agents.critic import CriticAgent
    from auto_engineering.agents.developer import DeveloperAgent
    from auto_engineering.llm.anthropic_provider import AnthropicProvider
    from auto_engineering.runtime.mock import ScriptedMockRuntime
    from auto_engineering.runtime.runtime import AgentRuntime

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
    runtime = AgentRuntime()
    runtime.register("architect", lambda: ArchitectAgent(llm=llm))
    runtime.register("developer", lambda: DeveloperAgent(llm=llm))
    runtime.register("critic", lambda: CriticAgent(llm=llm))
    return runtime


@dataclass
class LoopRunResult:
    """_run_loop_engine 返回值."""

    status: str
    total_steps: int
    checkpoint_id: str


def _run_loop_engine(
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
) -> LoopRunResult:
    """真实驱动 LoopEngine.run().

    P1.2: 根据 ANTHROPIC_API_KEY 自动选择 AgentRuntime(真 LLM) 或 ScriptedMockRuntime.
    dry-run 模式: 只跑 architect stage 后立即返回.
    """
    from auto_engineering.engine import LoopEngine, build_dev_loop_graph

    runtime = _build_runtime(requirement)

    engine = LoopEngine(
        build_dev_loop_graph(),
        runtime=runtime,
        checkpoint_dir=settings.checkpoint_dir,
        max_steps=max_steps,
    )

    if dry_run:
        # dry-run: 只跑 architect → 输出 plan → 退出
        click.echo("[DRY RUN] only architect stage will execute")
        runtime_dry = _build_runtime(requirement)
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
        return LoopRunResult(
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

    return LoopRunResult(
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
@click.option("--max-steps", type=int, default=3, help="最大迭代步数")
@click.option("--max-tokens", type=int, default=0, help="Token 预算上限 (0 = 无限制)")
@click.option("--max-cost", type=float, default=0.0, help="美元成本上限 (Phase 2+ 实现)")
@click.option("--multi", is_flag=True, help="多 Agent 并行模式（未来）")
@click.option("--dry-run", is_flag=True, help="只跑 architect 输出 plan")
@click.option("--log-format", type=click.Choice(["text", "json"]), default="text", help="日志格式")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "ollama", "openai"]),
    default="anthropic",
    help="LLM 提供方",
)
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
def dev_loop(
    requirement: str,
    max_steps: int,
    max_tokens: int,
    max_cost: float,
    multi: bool,
    dry_run: bool,
    log_format: str,
    llm_provider: str,
    project_root: str,
):
    """单需求开发循环 (Architect → Developer → Critic)."""
    # T10: --llm-provider 仅 anthropic 实装
    if llm_provider != "anthropic":
        click.echo(
            f"[未实现] --llm-provider={llm_provider} 暂未实装。"
            f"v1.0 仅支持 anthropic。请使用 --llm-provider=anthropic",
            err=True,
        )
        raise SystemExit(6)

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

    # 加载 Settings (含 max_tokens/max_steps 等)
    from auto_engineering.config.settings import Settings

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

    # 调用驱动器
    try:
        result = _run_loop_engine(
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

    # 总结输出
    click.echo(
        f"\n✓ dev-loop complete: status={result.status}, "
        f"steps={result.total_steps}, checkpoint={result.checkpoint_id}"
    )


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


if __name__ == "__main__":
    main()
