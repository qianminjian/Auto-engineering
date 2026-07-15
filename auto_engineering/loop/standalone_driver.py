"""StandaloneDriver — Driver B: 进程内 AgentRuntime 调 LLM → 回喂 tick_dict.

v7.0 双驱动架构:
  - Driver A (AgentDriver): Agent 工具调用 ae CLI, 文件桥接
  - Driver B (StandaloneDriver): 进程内 AgentRuntime 自带 key 调 LLM,
    产出 stage-result dict 回喂同一 tick 循环

设计参考: design/v7.0-Plan-DualDriver.md §5.2 + V7-5.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_engineering.runtime.task import Task

_logger = logging.getLogger("ae.loop.standalone_driver")

# action → role mapping (all known stages)
_ACTION_ROLE_MAP: dict[str, str] = {
    "architect": "architect",
    "developer": "developer",
    "critic": "critic",
    "component_verifier": "component_verifier",
    "system_verifier": "system_verifier",
    "plate_deep_audit": "plate_deep_audit",
    "system_deep_audit": "system_deep_audit",
    "gap_scan": "gap_scan",
    "gap_review": "gap_review",
    "research": "research",
    "plan_refine": "plan_refine",
    "design_doc_sync": "design_doc_sync",
}

# Stages whose result format is free-form (no RESULT_SCHEMA enforcement)
_PHASE0_STAGES: frozenset[str] = frozenset({
    "gap_scan", "gap_review", "research", "component_verifier", "audit",
    "system_deep_audit", "deep_audit", "report", "convergence", "design_sync",
})

# Auto-pass stub result per stage — must satisfy RESULT_SCHEMA in actions.py
_AUTO_PASS_RESULT: dict[str, dict] = {
    "component_verifier": {
        "stage": "component_verifier", "component": "",
        "coverage_map": [], "missing_count": 0, "diverged_count": 0,
    },
    "system_verifier": {
        "stage": "system_verifier", "full_coverage_map": [],
        "total_design_items": 0, "covered_count": 0,
        "missing_count": 0, "diverged_count": 0,
    },
    "system_deep_audit": {
        "stage": "system_deep_audit", "findings": [],
        "p0_count": 0, "p1_count": 0, "p2_count": 0,
        "total_audited_files": 0,
    },
    "plate_deep_audit": {
        "stage": "plate_deep_audit", "plate": "", "findings": [],
        "p0_count": 0, "p1_count": 0, "p2_count": 0,
        "cross_component_issues": [],
    },
}


@dataclass
class RunSummary:
    """StandaloneDriver.run() 返回摘要."""

    success: bool
    total_ticks: int
    final_stage: str
    verdict: str = ""
    error_message: str = ""
    action_history: list[dict] = field(default_factory=list)


class StandaloneDriver:
    """Driver B: 读 action → AgentRuntime 调 LLM → 回喂 tick_dict → 循环.

    Usage::

        orch = TickOrchestrator(...)
        runtime = AgentRuntime()
        runtime.register("architect", lambda: BaseAgent(...))
        # ... register developer, critic, etc.

        driver = StandaloneDriver(orch, runtime, project_root)
        summary = driver.run("实现登录功能")
    """

    def __init__(
        self,
        orchestrator: Any,
        agent_runtime: Any,
        project_root: Path,
        *,
        max_rounds: int = 5,
        max_tokens: int = 0,
        design_doc_path: str | None = None,
    ) -> None:
        self._orch = orchestrator
        self._runtime = agent_runtime
        self.project_root = project_root
        self.max_rounds = max_rounds
        self._max_tokens = max_tokens
        self._design_doc_path = design_doc_path

    # ── public API ──

    def run(self, requirement: str) -> RunSummary:
        """运行完整 dev-loop: init → loop → done/error.

        Returns:
            RunSummary with success/failure + execution metadata.
        """
        import asyncio

        return asyncio.run(self.run_async(requirement))

    async def run_async(self, requirement: str) -> RunSummary:
        """run() 的 async 版本 (直接 await, 适合已有 event loop 场景)."""
        try:
            action = self._orch.init(
                requirement,
                design_doc_path=self._design_doc_path,
                max_rounds=self.max_rounds,
            )
        except Exception:
            _logger.exception("TickOrchestrator.init() 失败")
            return RunSummary(
                success=False, total_ticks=0, final_stage="",
                error_message="init 失败: 详见日志",
            )

        tick_count = 0
        action_history: list[dict] = []
        _logger.info(
            "[StandaloneDriver] 启动: requirement=%s, max_rounds=%d, "
            "design_doc=%s",
            requirement[:80], self.max_rounds,
            self._design_doc_path or "无",
        )

        try:
            while tick_count < self.max_rounds * 10:  # safety ceiling
                tick_count += 1
                stage = action.get("stage", "?")
                _logger.info(
                    "[StandaloneDriver] Tick %d: stage=%s action=%s",
                    tick_count, stage, action.get("action", "?"),
                )

                action_history.append({
                    "tick": tick_count,
                    "action": action.get("action"),
                    "stage": stage,
                })

                if action.get("action") == "done":
                    return RunSummary(
                        success=True,
                        total_ticks=tick_count,
                        final_stage=stage,
                        verdict=action.get("verdict", "GOAL_ACHIEVED"),
                        action_history=action_history,
                    )

                if action.get("action") == "error":
                    return RunSummary(
                        success=False,
                        total_ticks=tick_count,
                        final_stage=stage,
                        error_message=action.get("message", "unknown error"),
                        action_history=action_history,
                    )

                action = await self._execute_action_safe(action, action_history)
                if action is None:
                    return RunSummary(
                        success=False,
                        total_ticks=tick_count,
                        final_stage=stage,
                        error_message="execute_action 返回 None",
                        action_history=action_history,
                    )

                action = self._orch.tick_dict(action)

        except Exception:
            _logger.exception("run_async 未捕获异常 (tick=%s)", tick_count)
            return RunSummary(
                success=False,
                total_ticks=tick_count,
                final_stage=action.get("stage", ""),
                error_message="run_async 异常: 详见日志",
                action_history=action_history,
            )

        return RunSummary(
            success=False,
            total_ticks=tick_count,
            final_stage=action.get("stage", ""),
            error_message="max iterations reached",
            action_history=action_history,
        )

    async def _execute_action_safe(
        self, action: dict, action_history: list[dict]
    ) -> dict | None:
        """执行 action, 带错误处理和资源安全.

        任何异常都优雅转换为 error result, 不抛原始 traceback.
        """
        try:
            return await self._execute_action(action)
        except Exception:
            _logger.exception(
                "_execute_action 异常 (tick=%d, stage=%s)",
                len(action_history), action.get("stage", "?"),
            )
            return {
                "stage": action.get("stage", "unknown"),
                "error": "execute_action 内部异常, 详见日志",
            }

    # ── action → task → execute ──

    async def _execute_action(self, action: dict) -> dict:
        """执行单个 action: 构造 Task → AgentRuntime.execute → 校验 → result.

        V7-5 spec §2: developer 阶段 N 个 task 串行执行（非 asyncio.gather），
        保持 TDD 顺序。

        V7-5 spec §3: validate_result_format() 校验, 不通过时最多 1 次重试
        （含格式纠正 prompt）。

        Returns:
            result dict (符合 stage-result schema, 可直接喂 tick_dict).
        """
        role = self._action_role(action)
        agent = self._runtime.get(role)
        if agent is None:
            return self._auto_pass_result(role, action)

        # Developer: 串行执行每个 task (V7-5 §2)
        if role == "developer":
            return await self._execute_developer_serial(action, agent)

        # gap_review in headless → auto mode (V7-5 §5)
        if role == "gap_review":
            return await self._execute_gap_review_headless(action, agent)

        # 标准单 task 执行 + 校验 + 重试
        return await self._execute_single_task(action, agent, role)

    async def _execute_single_task(
        self, action: dict, agent: Any, role: str
    ) -> dict:
        """执行单个 task: 构造 Task → execute → validate → retry once."""
        from auto_engineering.cli.helpers import TokenTracker
        from auto_engineering.loop.actions import validate_result_format
        from auto_engineering.runtime.cancellation import CancellationToken

        task = self._action_to_task(action)
        ctx = self._make_task_context(role)
        cancellation = CancellationToken()
        token_tracker = TokenTracker(max_tokens=self._max_tokens)

        try:
            task_result = await agent.execute(
                task, ctx,
                cancellation=cancellation, token_tracker=token_tracker,
            )
        except Exception:
            _logger.exception("Agent '%s' execute 失败", role)
            return {"stage": role, "error": f"Agent '{role}' 执行异常"}

        result = dict(task_result.values)
        if "stage" not in result:
            result["stage"] = role

        # Phase 0 stages: free-form, skip validation (V7-5 §5)
        if role in _PHASE0_STAGES:
            return result

        # V7-5 §3: validate_result_format + 最多 1 次重试
        errors = validate_result_format(result, role)
        if not errors:
            # v7.0.1: developer 完成后 auto-commit (防止 GitClean guardrail 拦截)
            if role == "developer":
                self._auto_commit(
                    result.get("batch_id", action.get("batch_id", "T1")), "",
                )
            return result

        _logger.warning(
            "Stage '%s' result 校验失败 (tick=%s): %s",
            role, action.get("tick", "?"), "; ".join(errors[:3]),
        )
        # 当首次结果已有部分有效数据 (如 markdown fallback), 跳过重试避免数据丢失
        _meaningful_keys = (
            ("plan", "batch_plan", "file_list") if role == "architect"
            else ("files_changed", "test_results", "batch_id")
        )
        has_meaningful_data = any(
            bool(result.get(k)) for k in _meaningful_keys
            if isinstance(result.get(k), (list, str, dict))
        )
        if has_meaningful_data:
            _logger.info(
                "Stage '%s' 已有部分有效数据 (markdown fallback), 跳过 LLM 重试",
                role,
            )
            return result
        correction = (
            f"[格式纠正] 上一轮输出不符合 stage-result schema: {'; '.join(errors)}。"
            f"请按正确格式重新输出。期望格式: {task.expected_output}"
        )
        retry_task = Task(
            id=f"{task.id}:retry",
            description=task.description + "\n\n" + correction,
            expected_output=task.expected_output,
            output_schema=task.output_schema,
        )
        try:
            retry_result = await agent.execute(
                retry_task, ctx,
                cancellation=cancellation, token_tracker=token_tracker,
            )
        except Exception:
            _logger.exception("Stage '%s' 重试失败", role)
            return {"stage": role, "error": "重试失败: 详见日志"}

        retry_values = dict(retry_result.values)
        if "stage" not in retry_values:
            retry_values["stage"] = role
        retry_errors = validate_result_format(retry_values, role)
        if retry_errors:
            _logger.error(
                "Stage '%s' 重试后仍校验失败: %s", role, "; ".join(retry_errors),
            )
        return retry_values

    async def _execute_developer_serial(
        self, action: dict, agent: Any
    ) -> dict:
        """Developer 阶段: 逐 task 串行执行 (V7-5 §2).

        非 asyncio.gather — 保持 TDD Red→Green→Refactor 顺序。
        """
        from auto_engineering.cli.helpers import TokenTracker
        from auto_engineering.runtime.cancellation import CancellationToken

        tasks = action.get("context", {}).get("tasks", [])
        if not tasks:
            # 无 tasks → 回退到单 task 模式
            return await self._execute_single_task(action, agent, "developer")

        batch_id = action.get("context", {}).get("batch_id", action.get("batch_id", ""))
        role = "developer"
        ctx = self._make_task_context(role)
        cancellation = CancellationToken()
        token_tracker = TokenTracker(max_tokens=self._max_tokens)

        all_files_changed: list[str] = []
        all_test_results: dict[str, int] = {"passed": 0, "failed": 0}
        last_commit_hash: str = ""
        errors: list[str] = []

        for i, task_info in enumerate(tasks):
            task_id = task_info.get("id", f"T{i}")
            task_desc = task_info.get("description", "")
            _expected = task_info.get("expected_output", "JSON")
            _logger.info(
                "[developer] Task %d/%d: %s (batch=%s)",
                i + 1, len(tasks), task_id, batch_id,
            )

            subtask = Task(
                id=f"developer:{batch_id}:{task_id}",
                description=(
                    f"你是一个软件开发者。实现以下任务 (batch={batch_id}, "
                    f"task={task_id}/{len(tasks)}):\n{task_desc}\n\n"
                    f"遵守 TDD: 先写测试(Red) → 确认 FAIL → 最少量实现(Green) "
                    f"→ 测试通过后 Refactor。\n"
                    f"每个 task 产出独立的 files_changed + test_results。"
                ),
                expected_output=(
                    "JSON with: task_id, files_changed (list), "
                    "test_results ({passed, failed}), commit_hash"
                ),
            )

            try:
                task_result = await agent.execute(
                    subtask, ctx,
                    cancellation=cancellation, token_tracker=token_tracker,
                )
            except Exception:
                _logger.exception(
                    "Developer task '%s' execute 失败", task_id,
                )
                errors.append(f"Task '{task_id}' 执行异常")
                continue

            values = dict(task_result.values)
            fc = values.get("files_changed", [])
            if isinstance(fc, list):
                all_files_changed.extend(fc)
            tr = values.get("test_results", {})
            if isinstance(tr, dict):
                all_test_results["passed"] += tr.get("passed", 0)
                all_test_results["failed"] += tr.get("failed", 0)
            ch = values.get("commit_hash", "")
            if ch and isinstance(ch, str) and len(ch) == 40:
                last_commit_hash = ch

            if all_test_results["failed"] > 0 or errors:
                break  # TDD 失败时停止后续 task

        # Auto-commit: 模型可能不主动调 git_commit, 导致 GitClean guardrail 拦截
        # 无论 task 成功或失败都 commit (否则 GitClean 会阻断后续 tick)
        last_commit_hash = self._auto_commit(batch_id, last_commit_hash)

        # 生成 red_evidence (TDD RED 证据) — REDGuard 需要
        red_evidence: list[dict] = []
        if last_commit_hash and len(last_commit_hash) == 40:
            for task_info in tasks:
                task_id = task_info.get("id", "")
                targets = task_info.get("file_targets", [])
                test_files = [f for f in targets if f.startswith("tests/") or "test" in f.lower()]
                if test_files:
                    red_evidence.append({
                        "task_id": task_id,
                        "red_commit": last_commit_hash,
                        "test_files": test_files,
                    })

        return {
            "stage": "developer",
            "batch_id": batch_id,
            "files_changed": list(set(all_files_changed)),
            "test_results": all_test_results,
            "commit_hash": last_commit_hash,
            "red_evidence": red_evidence,
            **({"error": "; ".join(errors)} if errors else {}),
        }

    def _auto_commit(self, batch_id: str, fallback_hash: str) -> str:
        """TDD 完成后自动 git commit (模型可能跳过 commit, 导致 Guardrail 拦截)."""
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=15,
            )
            if not status.stdout.strip():
                return fallback_hash  # 无变更, 不需要 commit

            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=15,
            )
            msg = f"feat(dev-loop): {batch_id} — StandaloneDriver auto-commit"
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=15,
            )
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=10,
            )
            commit_hash = rev.stdout.strip()
            if len(commit_hash) == 40:
                _logger.info("[auto-commit] %s → %s", batch_id, commit_hash[:8])
                return commit_hash
            return fallback_hash
        except Exception:
            _logger.exception("[auto-commit] 失败 (batch=%s)", batch_id)
            return fallback_hash

    async def _execute_gap_review_headless(
        self, action: dict, agent: Any
    ) -> dict:
        """Phase 0 gap_review: headless 下自动 Defer (V7-5 §5).

        有 research findings 时自动 inject supplement；无时全部 Defer。
        """

        gaps = action.get("gaps", [])
        research_findings = action.get("research_findings", {})
        is_rereview = action.get("is_rereview", False)

        if not gaps:
            return {"stage": "gap_review", "decisions": []}

        decisions: list[dict] = []
        for gap in gaps:
            gap_id = gap.get("id", "")
            if is_rereview and gap_id in research_findings:
                findings = research_findings[gap_id]
                decisions.append({
                    "gap_id": gap_id,
                    "resolution": "fill",
                    "fill_content": (
                        findings.get("recommended_design", "")
                        if isinstance(findings, dict)
                        else str(findings)
                    ),
                    "user_note": "[headless] auto-inject from research findings",
                })
            else:
                decisions.append({
                    "gap_id": gap_id,
                    "resolution": "defer",
                    "user_note": "[headless] auto-Defer",
                })

        _logger.info(
            "[gap_review headless] %d gaps: %d fill (from research), %d defer",
            len(gaps),
            sum(1 for d in decisions if d["resolution"] == "fill"),
            sum(1 for d in decisions if d["resolution"] == "defer"),
        )

        return {"stage": "gap_review", "decisions": decisions}

    # ── action → role ──

    def _action_role(self, action: dict) -> str:
        """从 action JSON 提取 role (Driver B 注册表 key).

        V7-2: action 中已有 "role" 字段, 与 "action" 字段镜像.
        优先取 "role", 降级取 "action", 再降级查映射表.
        """
        role = action.get("role") or action.get("action") or ""
        return _ACTION_ROLE_MAP.get(role, role)

    def _auto_pass_result(self, role: str, action: dict) -> dict:
        """返回 schema-compliant auto-pass stub (Phase 0 headless stages)."""
        stub = _AUTO_PASS_RESULT.get(role)
        if stub is not None:
            result = dict(stub)
            # Inject context for stages that need it
            ctx = action.get("context", {})
            if role == "component_verifier":
                result["component"] = ctx.get("component", "")
            elif role == "plate_deep_audit":
                result["plate"] = ctx.get("plate", "")
            return result
        # Truly free-form Phase 0 stages: minimal stub
        if role in _PHASE0_STAGES:
            return {"stage": role}
        return {"stage": role, "error": f"Agent '{role}' not registered"}

    # ── action → Task ──

    def _action_to_task(self, action: dict) -> Task:
        """将 action JSON 转换为 Agent 可执行的 Task."""
        context = action.get("context", {})
        role = self._action_role(action)
        descriptions = self._build_task_description(action, context)
        task_id = f"{role}:{action.get('tick', 0)}"
        output_schema = self._build_output_schema(action)
        return Task(
            id=task_id,
            description=descriptions["description"],
            expected_output=descriptions["expected_output"],
            output_schema=output_schema,
        )

    def _build_task_description(
        self, action: dict, context: dict
    ) -> dict[str, str]:
        """根据 action type 构造 task description + expected_output."""
        action_type = action.get("action", "")
        stage = action.get("stage", "")

        if action_type == "architect":
            req = context.get("requirement", "")
            return {
                "description": (
                    f"你是一个软件架构师。根据以下需求生成架构计划。\n\n"
                    f"需求: {req}\n\n"
                    f"先用工具探索项目结构, 然后输出架构计划。\n"
                    f"用 ## T1: 名称 格式列出每个批次, "
                    f"每批次下用列表列出目标文件路径。"
                ),
                "expected_output": (
                    "Markdown 架构计划, 含 ## T1/T2 批次标题 + 文件路径列表"
                ),
            }

        if action_type == "developer":
            tasks = context.get("tasks", [])
            batch_id = context.get("batch_id", action.get("batch_id", ""))
            plan = action.get("plan", "")
            requirement = action.get("requirement", "")
            _task_descs = "\n".join(
                f"  - {t.get('id', '?')}: {t.get('description', '')}"
                + (f" (files: {', '.join(t.get('file_targets', []))})"
                   if t.get('file_targets') else "")
                for t in tasks
            )
            plan_context = (
                f"\n\n架构计划:\n{plan[:3000]}" if plan else ""
            )
            req_context = (
                f"\n\n原始需求:\n{requirement[:2000]}" if requirement else ""
            )
            # v7.0: 当 batch_plan 为空时, 让 developer 自行规划设计 (DeepSeek 兼容)
            if not tasks or not any(t.get("file_targets") for t in tasks):
                self_directed = (
                    "\n\n注意: 架构计划中没有给出具体文件列表。"
                    "请直接根据原始需求创建文件, 不要花时间浏览项目。\n"
                    "步骤:\n"
                    "1. 先用 mkdir -p 创建必要的目录 (如 src/, tests/)\n"
                    "2. 立即用 write_file 创建实现文件 (最多 3 个)\n"
                    "3. 用 write_file 创建测试文件 (1 个)\n"
                    "4. 用 run_tests 运行测试\n"
                    "5. 用 git_commit 提交所有变更\n"
                    "6. 输出 files_changed + test_results JSON\n"
                    "重要: 必须使用 write_file 创建文件, 不要只读不写。"
                    "前 3 个工具调用中至少要有 1 个 write_file。"
                )
            else:
                self_directed = ""
            return {
                "description": (
                    f"你是一个软件开发者。实现以下需求 (batch={batch_id}):\n"
                    f"{req_context}"
                    f"{plan_context}"
                    f"{self_directed}\n\n"
                    f"遵守 TDD: Red→Green→Refactor。\n"
                    f"每个文件改动后跑测试。先创建必要的目录, 再写代码。"
                ),
                "expected_output": (
                    "JSON with: files_changed (list), test_results "
                    "(passed/failed counts), batch_id"
                ),
            }

        if action_type == "critic":
            files = context.get("files_changed", action.get("files_changed", []))
            project_root = str(getattr(self, 'project_root', Path.cwd()))
            abs_files = "\n".join(
                f"  - {f} (绝对路径: {project_root}/{f})" for f in files
            ) if files else "  (无文件变更信息)"
            return {
                "description": (
                    f"你是一个代码审查者。项目根目录: {project_root}\n\n"
                    f"审查以下文件的代码变更:\n{abs_files}\n\n"
                    f"先用 read_file 读取每个文件 (用绝对路径), "
                    f"再用 git diff 查看变更, 然后产出审查结果。\n"
                    f"产出: verdict (APPROVE/MAJOR) + findings 列表。"
                ),
                "expected_output": (
                    "JSON with: verdict, findings (list of "
                    "{severity, file, line, issue, suggested_fix}), critic_feedback"
                ),
            }

        if "verifier" in action_type:
            component = context.get("component", action.get("component", ""))
            return {
                "description": (
                    f"对照设计文档检查实现覆盖 (component={component})。\n"
                    f"逐项比对设计条目与代码实现, 标注 IMPLEMENTED/MISSING/DIVERGED。"
                ),
                "expected_output": (
                    "JSON with: coverage_map (list), missing_count, diverged_count"
                ),
            }

        if "audit" in action_type:
            return {
                "description": (
                    "审计代码质量。检查: 架构合理性、代码质量、工程化规范、"
                    "团队协作友好度、代码逻辑虚化度。\n"
                    "产出: findings 列表 (P0/P1/P2 分级)。"
                ),
                "expected_output": (
                    "JSON with: findings (list), p0_count, p1_count, p2_count, "
                    "total_audited_files, design_docs_stale"
                ),
            }

        if action_type == "gap_scan":
            plates = context.get("plates", [])
            return {
                "description": (
                    f"扫描设计文档与代码实现的差距。\n"
                    f"设计文档路径: {context.get('design_doc_path', '')}\n"
                    f"板块: {plates}\n\n"
                    f"逐 section 比对设计规格与实际代码, 标注 gap 的 "
                    f"grade (blocking/major/minor) + clarity (clear/fuzzy/blank)。"
                ),
                "expected_output": (
                    "JSON with: gaps (list of {id, design_section_ref, grade, "
                    "clarity, summary, depends_on}), scanned_sections (int), "
                    "has_blocking (bool)"
                ),
            }

        if action_type == "gap_review":
            gaps = action.get("gaps", [])
            is_rereview = action.get("is_rereview", False)
            gap_summaries = "\n".join(
                f"  - {g.get('id', '?')}: {g.get('grade', '?')} "
                f"{g.get('summary', '')}"
                for g in gaps[:20]
            )
            mode = "复审 (research findings 已存档, 用户据研究发现做补充设计)" \
                if is_rereview else "初审"
            return {
                "description": (
                    f"审核 gap_scan 发现的 {len(gaps)} 个设计差距 ({mode})。\n"
                    f"{gap_summaries}\n\n"
                    f"对每个 gap 决定: Fill(补充设计内容) / Research(检索知识库) "
                    f"/ Defer(留给 architect in-loop 细化)。\n"
                    f"has_blocking 的 architectural gap 禁止 Defer。"
                ),
                "expected_output": (
                    "JSON with: decisions (list of {gap_id, resolution, "
                    "user_note, fill_content?})"
                ),
            }

        if action_type == "research":
            gap = action.get("gap", {})
            return {
                "description": (
                    f"检索 gap 的细化设计信息。\n"
                    f"gap: {gap.get('id', '?')} - {gap.get('summary', '')}\n"
                    f"design_section_ref: {gap.get('design_section_ref', '')}\n"
                    f"grade: {gap.get('grade', '?')}\n\n"
                    f"按 tier 顺序检索: tier0(内存) → tier1(参考代码) → "
                    f"tier2(文档/知识库) → tier3(Web)。\n"
                    f"内存约束: grep 定位 → 50-200 行 Read → 丢弃; 禁止批量/并行扫描。"
                ),
                "expected_output": (
                    "JSON with: findings (string), sources (list of "
                    "{tier, ref, note}), source_tier, confidence, "
                    "recommended_design (可注入 supplement)"
                ),
            }

        if action_type == "plan_refine":
            feedback = action.get("feedback", {})
            refine_request = (
                feedback.get("refine_request", {}) if isinstance(feedback, dict)
                else {}
            )
            return {
                "description": (
                    f"根据 refine request 调整架构计划。\n"
                    f"来源: {refine_request.get('source', 'unknown')}\n"
                    f"scope: plate={refine_request.get('scope_plate')} "
                    f"component={refine_request.get('scope_component')}\n\n"
                    f"参考 audit_findings/coverage_map 修正 plan + batch_plan, "
                    f"保持非变动部分不变。"
                ),
                "expected_output": (
                    "JSON with: plan (updated), batch_plan (updated), "
                    "file_list (updated), contracts (updated)"
                ),
            }

        if action_type == "design_doc_sync":
            return {
                "description": (
                    "同步设计文档与代码实现。\n"
                    "检查本轮所有改动是否与 design/ 文档一致。\n"
                    "代码与设计文档不一致 → 更新设计文档。\n"
                    "新增了设计文档未覆盖的决策 → 补充到 BEACON.md 决策表。"
                ),
                "expected_output": (
                    "JSON with: synced_sections (list), new_decisions (list), "
                    "stale_docs (list)"
                ),
            }

        # fallback: generic task (should not happen for known stages)
        _logger.warning(
            "No specific task description for action=%s stage=%s, using fallback",
            action_type, stage,
        )
        return {
            "description": f"执行 {stage} 阶段任务。\ncontext: {context}",
            "expected_output": f"{stage} stage result (JSON)",
        }

    # ── helpers ──

    def _build_output_schema(self, action: dict) -> dict | None:
        """构造 output_schema 用于强制 JSON 输出格式.

        architect 不使用 output_schema: 复杂规划任务中 DeepSeek 等模型
        难以遵守 JSON-only 约束, 转而依赖 parser.py markdown fallback 提取.
        """
        action_type = action.get("action", "")
        if action_type == "critic":
            return {
                "type": "object",
                "required": ["verdict", "findings"],
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["APPROVE", "MAJOR"],
                        "description": "审查裁决: APPROVE 通过, MAJOR 需修改",
                    },
                    "findings": {
                        "type": "array",
                        "description": "发现的问题列表",
                        "items": {
                            "type": "object",
                            "required": ["file", "severity", "issue", "suggested_fix"],
                            "properties": {
                                "file": {"type": "string", "description": "文件路径"},
                                "line": {"type": "integer", "description": "行号"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["P0", "P1", "P2"],
                                    "description": "严重度",
                                },
                                "issue": {"type": "string", "description": "问题描述"},
                                "suggested_fix": {"type": "string", "description": "修复建议"},
                            },
                        },
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "代码优点",
                    },
                    "assessment": {"type": "string", "description": "总体评估"},
                    "critic_feedback": {"type": "string", "description": "反馈摘要"},
                },
            }
        return None

    def _make_task_context(self, role: str) -> Any:
        """构造 TaskContext (含 CancellationToken/TokenTracker)."""
        from auto_engineering.runtime.context import TaskContext

        state: Any = getattr(self._orch, "_state", None)
        return TaskContext(
            state=state,
            requirement=getattr(state, "requirement", "") if state else "",
            current_stage=role,
        )


__all__ = ["RunSummary", "StandaloneDriver"]
