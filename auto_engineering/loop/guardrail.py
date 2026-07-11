"""M2 Guardrail 链 — GuardrailResult + Guardrail ABC + 6 Guardrails + Chain + handler.

设计参考: v5.6-Design-Loop.md §B2.3 (Guardrail 接口契约)
                   + §B1.8 (GuardrailResult 数据类)
                   + §B5.1 (5 Guardrail 规格 G1-G5)
                   + §B10.5 / §B3 (G6 NoDeferredBlockingGap)
                   + §B5.2 (handle_guardrail_result 3 态)
                   + 附录 C R-5 (GitDiffExists 新仓库降级)

v5.4 P2-8: drop 态已从类型系统和 handler 中完全移除.
           保留 3 态 pass/block/retry 覆盖所有场景.

模块职责:
    - GuardrailResult / Guardrail ABC: 契约定义 (action 3 态)
    - 6 Guardrail (G1-G5 + G6): 内置检查 (只用 pass/block/retry)
    - GuardrailChain: 编排 (fail-fast + timing/stage 过滤)
    - handle_guardrail_result: action 分发 (continue/stop/retry)

依赖:
    - stage_router.clear_stage_fields (Stage 字段清理复用)
    - EngineState (任意对象, duck-typed)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from auto_engineering.loop.stage_router import clear_stage_fields
from auto_engineering.utils.git import run_git as _run_git
from auto_engineering.utils.git import run_git_diff as _run_git_diff

__all__ = [
    "MAX_RETRY_PER_STAGE",
    "Action",
    "GitClean",
    "GitDiffExists",
    "Guardrail",
    "GuardrailChain",
    "GuardrailResult",
    "PlanExists",
    "RequirementValid",
    "TestsPass",
    "handle_guardrail_result",
]

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

# v5.1 P0-1: Guardrail 3 态动作 (drop 已删除, 仅保留 pass/block/retry)
Action = Literal["pass", "block", "retry"]

# v5.0 §B5.1 + §B5.2 配
MAX_RETRY_PER_STAGE = 3


@dataclass
class GuardrailResult:
    """Guardrail 检查结果 (§B1.8).

    Fields:
        action: "pass" | "block" | "retry"
                - pass:  通过,继续
                - block: 严重错误,终止主循环
                - retry: 可恢复,retry 计数 + 1
        message: 用户可读消息 (失败原因)

    v5.1 P0-1: drop 态已从契约中删除 (YAGNI, 与 retry 语义重叠).
                旧 drop 输入不再特殊处理, 按未知 action 落入防御性 "stop"
                (见 handle_guardrail_result 末尾)。

    注: 默认 action="pass" — 大多数 Guardrail pass path 返回纯 pass。
    """

    action: Action = "pass"
    message: str = ""


class Guardrail(ABC):
    """Guardrail 抽象基类 (§B2.3).

    类属性:
        name: 唯一名 (用于日志/错误)
        timing: "pre" (Stage 执行前) | "post" (Stage 执行后)
        applies_to_stages: 适用的 Stage 元组 — 过滤维度 1
        — Chain 还按 timing 过滤 (维度 2)

    实例方法:
        check(stage, state, project_root=None) → GuardrailResult:
            stage: 当前 Stage 名
            state: EngineState 实例
            project_root: 项目根目录 (默认 cwd via Chain 兜底)
    """

    name: str = ""  # 子类必须覆盖
    timing: Literal["pre", "post"] = "pre"  # 子类必须覆盖
    applies_to_stages: tuple[str, ...] = ()  # 子类必须覆盖

    @abstractmethod
    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        """执行 Guardrail 检查.

        Args:
            stage: 当前 Stage 名.
            state: EngineState 实例 (duck-typed,需有对应字段).
            project_root: 项目根目录 (None 时 Chain fallback 到 cwd).

        Returns:
            GuardrailResult 含 action + message.

        行为约束 (CrewAI 业界规范):
            - 纯函数: 不修改 state (handlers 才负责清理).
            - 异常处理: check() 内部捕获 IO 异常,降级到 retry/block,
              不抛给上层避免 Orchestrator 僵死.
        """


# ==================== G1-G5 内置 Guardrail ====================


class RequirementValid(Guardrail):
    """G1: 验证 requirement 输入合法性 (§B5.1).

    pre/architect: 在 architect 执行前验证用户输入的 requirement.
    失败 action=block (不可重试,用户输入本身有问题).
    """

    name = "RequirementValid"
    timing = "pre"
    applies_to_stages = ("architect",)

    MAX_LEN = 4096

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        req: str = getattr(state, "requirement", "") or ""
        # 1. 空检查 (空白也视为空)
        stripped = req.strip()
        if not stripped:
            return GuardrailResult(
                action="block",
                message="requirement 为空",
            )
        # 2. 长度检查
        if len(req) > self.MAX_LEN:
            return GuardrailResult(
                action="block",
                message=f"requirement 超过最大长度 {self.MAX_LEN}",
            )
        # 3. 控制字符检查: 全部内容仅控制字符 → block
        # 控制字符: 0x00-0x1F (除 0x09 \t / 0x0A \n / 0x0D \r) + 0x7F
        if all(c in "\t\n\r" or ord(c) < 0x20 or ord(c) == 0x7F for c in stripped):
            return GuardrailResult(
                action="block",
                message="requirement 仅包含控制字符",
            )
        return GuardrailResult()


class PlanExists(Guardrail):
    """G2: 验证 architect 产出 plan + file_list (§B5.1).

    post/architect: 检查 plan 非空 AND file_list 1+ 项.
    失败 action=retry (architect 可重做).
    """

    name = "PlanExists"
    timing = "post"
    applies_to_stages = ("architect",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        plan: str = getattr(state, "plan", "") or ""
        file_list: list = getattr(state, "file_list", []) or []
        if not plan:
            return GuardrailResult(
                action="retry",
                message="plan 为空,需 architect 重新产出",
            )
        if len(file_list) < 1:
            return GuardrailResult(
                action="retry",
                message="file_list 为空,需 architect 重新产出",
            )
        return GuardrailResult()


class GitDiffExists(Guardrail):
    """G3: 验证 developer 实际写入了代码 (§B5.1).

    post/developer: 用 `git diff HEAD~1..HEAD --numstat` 验证
    上一轮 Stage 产出导致源码变更. 新仓库 (无 HEAD~1) 降级到
    `git diff --cached --numstat` (v5.0 §附录 C R-5).

    失败 action=retry (developer 可重写).
    """

    name = "GitDiffExists"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root if project_root is not None else Path.cwd()

        # 先试 HEAD~1..HEAD (有 commit 的仓库)
        rc1, stdout1 = _run_git_diff(root, ["HEAD~1..HEAD"])
        if rc1 == 0:
            if stdout1.strip():
                return GuardrailResult()  # pass
            return GuardrailResult(
                action="retry",
                message="git diff HEAD~1..HEAD 为空,developer 未产生代码变更",
            )

        # 降级: HEAD~1 不存在 (新仓库), 用 --cached
        rc2, stdout2 = _run_git_diff(root, ["--cached"])
        # 即使新仓库也可能 --cached 为空 → 视作 retry 让 developer 提交
        if rc2 == 0 and stdout2.strip():
            return GuardrailResult()  # pass via cached
        return GuardrailResult(
            action="retry",
            message="新仓库且无 staged 变更,developer 需先 git add/commit",
        )


class TestsPass(Guardrail):
    """G4: 验证 developer 测试全过 (§B5.1).

    post/developer: 检查 state.test_results dict.
    判定: failed==0 AND errors==0 AND 总数 > 0.

    失败 action=retry (developer 可修复代码后重跑测试).
    """

    name = "TestsPass"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        results: dict = getattr(state, "test_results", {}) or {}
        passed = int(results.get("passed", 0) or 0)
        failed = int(results.get("failed", 0) or 0)
        errors = int(results.get("errors", 0) or 0)
        total = passed + failed + errors

        if total == 0:
            return GuardrailResult(
                action="retry",
                message="test_results 为空,developer 需跑测试",
            )
        if failed > 0 or errors > 0:
            return GuardrailResult(
                action="retry",
                message=f"测试失败: failed={failed}, errors={errors}",
            )
        return GuardrailResult()


class GitClean(Guardrail):
    """G5: 验证 developer 提交后仓库无残留变更 (§B5.1).

    post/developer: 用 `git status --porcelain` 检查 working tree
    是否干净 (未跟踪/未 staged/未提交 修改全清空).

    失败 action=block (强制 developer 必须先 commit 才能继续).
    """

    name = "GitClean"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root if project_root is not None else Path.cwd()
        rc, stdout = _run_git(root, "status", "--porcelain")
        if rc != 0:
            # git 命令失败 (非 git 目录等) → block (让 Orchestrator 报警)
            return GuardrailResult(
                action="block",
                message=f"git status 失败 rc={rc}",
            )
        if stdout.strip():
            return GuardrailResult(
                action="block",
                message="working tree 有未提交变更,需先 commit",
            )
        return GuardrailResult()


# architectural gap 禁止的 resolution (§B10.5: 契约模糊不允许延后, 须 Fill/Research)
_BLOCKING_FORBIDDEN_RESOLUTIONS = frozenset({"defer", "defer_research"})


class NoDeferredBlockingGap(Guardrail):
    """G6: has_blocking 时 architectural gap 不允许 Defer/Defer+Research (§B10.5 / B3).

    post/gap_review: 用户在 gap_review 对每个 gap 决策后, 若存在 grade==architectural
    的 gap 被标为 defer/defer_research → block (architectural 契约模糊不允许延后, 否则
    组件设计无契约依据). 决策取自 state.pending_gap_decisions (尚未 apply 到 gap_report),
    grade 取自 state.gap_report_json (gap_scan 判定). 非 design-doc 模式无 gap_report → pass.

    失败 action=block (用户须改为 Fill/Research 重提 gap_review). 判定逻辑与
    gap_analysis.GapReport.validate_resolutions 同源 (_BLOCKING_FORBIDDEN_RESOLUTIONS).
    """

    name = "NoDeferredBlockingGap"
    timing = "post"
    applies_to_stages = ("gap_review",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        raw = getattr(state, "gap_report_json", None)
        if not raw:
            return GuardrailResult()  # 非 design-doc 模式: 无 architectural 约束
        try:
            report = json.loads(raw)
        except (ValueError, TypeError):
            # fail-closed: gap_report 损坏时不放行 (契约完整性未知)
            return GuardrailResult(
                action="block", message="gap_report_json 解析失败, 无法校验阻塞 gap")
        if not report.get("has_blocking"):
            return GuardrailResult()  # 无 architectural gap → 无约束
        grade_by_id = {
            g.get("id"): g.get("grade") for g in report.get("gaps", [])}
        deferred = [
            d.get("gap_id")
            for d in (getattr(state, "pending_gap_decisions", None) or [])
            if grade_by_id.get(d.get("gap_id")) == "architectural"
            and d.get("resolution") in _BLOCKING_FORBIDDEN_RESOLUTIONS
        ]
        if deferred:
            return GuardrailResult(
                action="block",
                message=(
                    f"architectural gap {deferred} 被标为 Defer/Defer+Research — "
                    "契约模糊不允许延后 (§B10.5); 请改为 Fill 或 Research 重提 gap_review"),
            )
        return GuardrailResult()


# ==================== GuardrailChain ====================


class GuardrailChain:
    """Guardrail 链表 — fail-fast 遍历 (§B2.3).

    check(timing, stage, state, project_root=None) → GuardrailResult:
        过滤维度:
            1. timing: 只跑 timing 匹配的 Guardrail
            2. stage:  只跑 stage in applies_to_stages 的 Guardrail
        fail-fast: 第一个 action != "pass" 立即返回 (不跑后续 Guardrail)
        全 pass → 返回 GuardrailResult("pass", "")
    """

    def __init__(self, guardrails: list[Guardrail]) -> None:
        self.guardrails = list(guardrails)

    @classmethod
    def default(cls) -> GuardrailChain:
        """工厂方法: 创建默认链 (G1-G5 + G6 NoDeferredBlockingGap, §B3)."""
        return cls([
            RequirementValid(),
            PlanExists(),
            GitDiffExists(),
            TestsPass(),
            GitClean(),
            NoDeferredBlockingGap(),
        ])

    def check(
        self,
        timing: str,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        """按 (timing × stage) 过滤 + fail-fast 遍历.

        Args:
            timing: "pre" | "post".
            stage: 当前 Stage 名.
            state: EngineState 实例.
            project_root: 项目根目录 (None → fallback cwd).

        Returns:
            第一个不 pass 的 GuardrailResult, 或全 pass 时的 GuardrailResult("pass", "").
        """
        for g in self.guardrails:
            if g.timing != timing:
                continue
            if stage not in g.applies_to_stages:
                continue
            result = g.check(stage, state, project_root=project_root)
            if result.action != "pass":
                return result
        return GuardrailResult()


# ==================== handle_guardrail_result ====================


def handle_guardrail_result(
    result: GuardrailResult,
    stage: str,
    state: EngineState,
    retry_counters: dict[str, int],
) -> str:
    """处理 GuardrailResult, 返回主循环下一步动作 (§B5.2).

    Action 分发 (v5.1 P0-1: 3 态, drop 已 deprecated):
        - "pass"  → "continue" (不动计数器)
        - "block" → "stop"    (不动计数器)
        - "drop"  (deprecated) → 无专门分支, 落入未知 action → "stop"
        - "retry":
            1. counter += 1
            2. counter >= MAX_RETRY_PER_STAGE (3) → "stop" (不再清字段)
            3. counter  <  MAX_RETRY_PER_STAGE     → "retry"
               + 清空 stage 对应字段 (复用 stage_router.clear_stage_fields)

    Args:
        result: GuardrailChain.check() 返回的 GuardrailResult.
        stage: 当前 Stage 名 (用于 counter key + 字段清空).
        state: EngineState 实例 (会被修改: 清字段).
        retry_counters: 共享计数器字典 (按 stage 隔离).

    Returns:
        主循环动作: "continue" | "stop" | "retry".

    注: 防御性: 未知 action → "stop" (避免 Orchestrator 在非预期动作上僵死).
    """
    action: str = result.action

    if action == "pass":
        return "continue"

    if action == "block":
        return "stop"

    if action == "retry":
        current = retry_counters.get(stage, 0)
        # 先判定, 再累加: 已达上限 → stop 且不动 counter/state
        if current >= MAX_RETRY_PER_STAGE:
            return "stop"
        # 未耗尽: 累加 + clear stage fields + 允许 retry
        retry_counters[stage] = current + 1
        clear_stage_fields(state, stage)
        return "retry"

    # 未知 action (防御性)
    return "stop"


