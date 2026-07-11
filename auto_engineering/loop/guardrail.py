"""M2 Guardrail 链 — GuardrailResult + Guardrail ABC + 9 Guardrails + Chain + handler.

设计参考: v5.6-Design-Loop.md §B2.3 (Guardrail 接口契约)
                   + §B1.8 (GuardrailResult 数据类)
                   + §B5.1 (5 Guardrail 规格 G1-G5)
                   + §B10.5 / §B3 (G6 NoDeferredBlockingGap)
                   + §B3.1/B3.2/B3.3 (G7 REDGuard / G8 FreshGate / G9 RegressionGate)
                   + §B5.2 (handle_guardrail_result 3 态)
                   + 附录 C R-5 (GitDiffExists 新仓库降级)

v5.4 P2-8: drop 态已从类型系统和 handler 中完全移除.
           保留 3 态 pass/block/retry 覆盖所有场景.

模块职责:
    - GuardrailResult / Guardrail ABC: 契约定义 (action 3 态)
    - 9 Guardrail (G1-G6 基线 + G7/G8/G9): 内置检查 (只用 pass/block/retry)
    - GuardrailChain: 编排 (fail-fast + timing/stage 过滤)
    - handle_guardrail_result: action 分发 (continue/stop/retry/rerun_gates)

依赖:
    - stage_router.clear_stage_fields (Stage 字段清理复用)
    - EngineState (任意对象, duck-typed)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
    "FreshGate",
    "GitClean",
    "GitDiffExists",
    "Guardrail",
    "GuardrailChain",
    "GuardrailResult",
    "PlanExists",
    "REDGuard",
    "RegressionGate",
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

    guardrail_name: 命中的 Guardrail 名 (Chain 在非 pass 时注入). 供
        handle_guardrail_result 按 f"{stage}:{guardrail_name}" 分源计数
        (S-4), 并让 FreshGate(G8) 走 rerun_gates 特化 retry 语义.
    """

    action: Action = "pass"
    message: str = ""
    guardrail_name: str = ""


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


# ==================== G7/G8 helpers (B3.1 / B3.2) ====================

# 严格模式 (opt-in): REDGuard checkout red_commit 重跑测试确认 FAIL.
# 默认 False — 信任 developer 提交的 red_evidence, 避免 checkout 重跑成本 (B3.1).
_STRICT_RED = os.environ.get("AE_STRICT_RED", "") == "1"


def _is_test_file(path: str) -> bool:
    """判定路径是否为测试文件 (tests/ 目录 或 test_*/*_test 命名)."""
    p = str(path).replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (
        p.startswith("tests/")
        or "/tests/" in p
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _git_log_first_touching(
    test_files: list[str], before: str, cwd: Path,
) -> str | None:
    """定位先于 impl commit 且触碰 test_files 的最近独立测试 commit.

    `git log <before> -- <test_files>` 列出 before 可达且触碰这些文件的
    commit (新→旧). 排除 impl commit 自身 (TDD 要求测试是**独立且更早**的
    commit, 见 B3.1 + S-12), 取剩余最新者. 无独立测试 commit → None.
    """
    if not test_files:
        return None
    rc, out = _run_git(cwd, "log", "--format=%H", before, "--", *test_files)
    if rc != 0:
        return None
    commits = [c.strip() for c in out.splitlines() if c.strip()]
    commits = [c for c in commits if c != before]  # 排除实现 commit 自身
    return commits[0] if commits else None


def _git_is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    """git merge-base --is-ancestor: ancestor 是否为 descendant 的祖先."""
    if not ancestor or not descendant:
        return False
    rc, _ = _run_git(cwd, "merge-base", "--is-ancestor", ancestor, descendant)
    return rc == 0


def _find_evidence(red_evidence: list[dict], task_id: str) -> dict | None:
    """从 red_evidence 找匹配 task_id 的条目 (B3.1)."""
    for ev in red_evidence or []:
        if isinstance(ev, dict) and ev.get("task_id") == task_id:
            return ev
    return None


def _run_test_at_commit(
    test_commit: str, test_id: str | None, project_root: Path,
) -> str:
    """严格模式: checkout 测试文件到 red_commit 重跑, 返回 'FAIL'/'PASS'/'UNKNOWN'.

    仅 _STRICT_RED opt-in 时调用 (默认路径信任 red_evidence, 不进本函数).
    checkout <red_commit> -- (whole tree 只读跑) 成本高且需 clean tree;
    此处用 `git stash`-free 的只读方式: 在临时 worktree 跑, 失败降级 UNKNOWN
    (严格模式下 UNKNOWN 不阻塞, 由调用方按 != 'FAIL' 判定).
    """
    if not test_id:
        return "UNKNOWN"
    import tempfile
    root = Path(project_root)
    try:
        with tempfile.TemporaryDirectory() as wt:
            rc, _ = _run_git(root, "worktree", "add", "--detach", wt, test_commit)
            if rc != 0:
                return "UNKNOWN"
            try:
                proc = subprocess.run(
                    ["python", "-m", "pytest", "-k", test_id, "-q", "--no-header"],
                    cwd=wt, capture_output=True, text=True, timeout=120,
                )
                return "FAIL" if proc.returncode != 0 else "PASS"
            finally:
                _run_git(root, "worktree", "remove", "--force", wt)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _aggregate_sha(files_changed: list[str], project_root: Path) -> str:
    """聚合 files_changed 内容的 sha256 (B3.2 files_snapshot_sha).

    对排序后的 (相对路径, 内容) 逐项 update, 保证确定性. 缺失文件用占位符
    (代码被删除也是一种变更, 应影响哈希). files_changed 为空 → 空内容哈希.
    """
    h = hashlib.sha256()
    root = Path(project_root)
    for f in sorted(files_changed or []):
        h.update(str(f).encode("utf-8"))
        h.update(b"\0")
        try:
            h.update((root / f).read_bytes())
        except OSError:
            h.update(b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


# ==================== G7 REDGuard / G8 FreshGate ====================


class REDGuard(Guardrail):
    """G7: TDD RED commit-time 校验 (§B3.1).

    post/developer: 对本轮 batch 的每个 task, 若含测试文件, 校验存在一个
    **先于实现 commit** 的独立测试 commit 且当时 FAIL:
        1. `git log impl -- test_files` 定位先于实现的测试 commit (排除 impl 自身)
        2. merge-base --is-ancestor 确认测试 commit 是实现 commit 祖先
        3. 默认信任 red_evidence (red_commit 匹配); _STRICT_RED 则 checkout 重跑

    纯配置/文档 task (无测试文件) 豁免. 无运行时句柄 (batch_state/_plan) 或无
    impl commit_hash → pass (无对象可校验). 失败 action=retry (补证据后重试).

    与 G3/G4 不重叠: G3/G4 确认"有改动 + 测试绿", REDGuard 补充"测试先于实现且曾红".
    """

    name = "REDGuard"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root if project_root is not None else Path.cwd()
        impl_commit: str = getattr(state, "commit_hash", "") or ""
        if not impl_commit:
            return GuardrailResult()  # 无实现 commit, 无对象可校验 (G3/G4 已覆盖有无改动)

        batch_state = getattr(state, "batch_state", None)
        plan = getattr(state, "_plan", None)
        if batch_state is None or plan is None:
            return GuardrailResult()  # 非 batch 运行时 (无句柄) → 不阻塞
        try:
            tasks = batch_state.current_batch_tasks(plan)
        except Exception:  # 句柄不完整时降级放行 (纯函数不抛给上层, 见 ABC check 约束)
            return GuardrailResult()

        red_evidence = getattr(state, "red_evidence", []) or []
        for task in tasks:
            targets = list(getattr(task, "target_files", []) or [])
            test_files = [f for f in targets if _is_test_file(f)]
            if not test_files:
                continue  # 纯配置/文档 task 豁免
            task_id = getattr(task, "id", "?")
            test_commit = _git_log_first_touching(test_files, impl_commit, root)
            if test_commit is None:
                return GuardrailResult(
                    action="retry",
                    message=f"task {task_id}: 无先于实现的测试 commit — 违反 TDD RED",
                )
            if not _git_is_ancestor(test_commit, impl_commit, root):
                return GuardrailResult(
                    action="retry",
                    message=f"task {task_id}: 测试 commit 非实现 commit 祖先",
                )
            ev = _find_evidence(red_evidence, task_id)
            if ev and ev.get("red_commit") == test_commit:
                continue  # 信任 developer 记录的 RED 证据
            if _STRICT_RED:
                test_id = ev.get("test_id") if ev else None
                if _run_test_at_commit(test_commit, test_id, root) != "FAIL":
                    return GuardrailResult(
                        action="retry",
                        message=f"task {task_id}: 测试在 red_commit 未 FAIL — 非真 RED",
                    )
            else:
                return GuardrailResult(
                    action="retry",
                    message=f"task {task_id}: 缺 red_evidence — 补充后重试",
                )
        return GuardrailResult()


class FreshGate(Guardrail):
    """G8: Gate 证据新鲜度锁定 (§B3.2).

    post/developer + post/critic: gate_results 每项记录运行时 files_changed 的
    聚合 sha256 (files_snapshot_sha, 由 run_gates 生产者契约注入, S-3). 若当前
    工作树聚合 sha 与某 Gate 记录不符 → 代码在 Gate 后又变更 → 证据陈旧 → retry.

    retry 语义特化 (S-4): 不清 stage 字段/不丢弃已提交实现, 而是触发 rerun_gates
    (仅重跑 Gate 刷新 gate_results). 由 handle_guardrail_result 依 guardrail_name 分流.
    旧格式 (无 files_snapshot_sha) 或空 gate_results → pass (无可比对基线).
    """

    name = "FreshGate"
    timing = "post"
    applies_to_stages = ("developer", "critic")

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root if project_root is not None else Path.cwd()
        gate_results: dict = getattr(state, "gate_results", {}) or {}
        if not gate_results:
            return GuardrailResult()
        files_changed = getattr(state, "files_changed", []) or []
        current_sha = _aggregate_sha(files_changed, root)
        for gate_name, r in gate_results.items():
            snapshot = (r or {}).get("files_snapshot_sha") if isinstance(r, dict) else None
            if snapshot and snapshot != current_sha:
                return GuardrailResult(
                    action="retry",
                    message=f"Gate {gate_name} 证据陈旧(代码在其后又变更) — 强制重跑 Gate",
                )
        return GuardrailResult()


# ==================== G9 helpers (B3.3) ====================


def _run_test(test_id: str, project_root: Path) -> str:
    """跑单个测试 (`pytest -k <test_id>`), 返回 'PASS'/'FAIL'/'UNKNOWN'.

    显式传 project_root 作为唯一 collection root (限定采集范围, 避免向上
    climb 到父项目 pyproject 触发 testpaths 全量采集); `-o addopts=` 清空
    继承的 addopts (不依赖父配置); `-B` 禁写 .pyc (revert/restore 同秒内
    git checkout 会令 mtime 相同, 陈旧字节码会掩盖源码回退 → 必须禁缓存).
    returncode==0 → PASS, 其余 → FAIL, 子进程异常 → UNKNOWN.
    """
    if not test_id:
        return "UNKNOWN"
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", str(project_root), "-k", test_id,
             "-q", "--no-header", "-o", "addopts=", "-p", "no:cacheprovider"],
            cwd=str(project_root), capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return "PASS" if proc.returncode == 0 else "FAIL"


def _git_checkout_paths(ref: str, files: list[str], root: Path) -> int:
    """git checkout <ref> -- <files>: 回退/恢复指定文件到 ref 版本. 返回 rc.

    同时更新 index + working tree, 故 restore("HEAD") 后 working tree 干净.
    """
    if not files:
        return 0
    rc, _ = _run_git(root, "checkout", ref, "--", *files)
    return rc


def _git_rm(files: list[str], root: Path) -> int:
    """git rm -f <files>: 移除文件 (模拟'修复前不存在'). 返回 rc.

    S-19: 实现文件在 impl_commit 中新建时, checkout impl^ 会 pathspec 报错;
    改用 git rm 让文件消失, 再由 restore("HEAD") 恢复.
    """
    if not files:
        return 0
    rc, _ = _run_git(root, "rm", "-f", *files)
    return rc


def _current_regression_task(state: EngineState):
    """从运行时 batch 句柄取当前 batch 首个 kind=='regression_fix' task, 无则 None.

    与 REDGuard 同源读 state.batch_state / state._plan (TickOrchestrator 注入).
    非 batch 运行时 (无句柄) 或无回归修复 task → None (Gate 判 N/A pass).
    """
    batch_state = getattr(state, "batch_state", None)
    plan = getattr(state, "_plan", None)
    if batch_state is None or plan is None:
        return None
    try:
        tasks = batch_state.current_batch_tasks(plan)
    except Exception:  # 句柄不完整时降级 (纯函数不抛给上层, 见 ABC check 约束)
        return None
    for task in tasks or []:
        if getattr(task, "kind", "") == "regression_fix":
            return task
    return None


class RegressionGate(Guardrail):
    """G9: 回归修复测试有效性校验 — revert→MUST FAIL→restore (§B3.3).

    post/developer: 仅当本轮 batch 含 kind=="regression_fix" task 时生效.
    验证该 task 新增/修改的回归测试**确实能捕捉被修复的回归**:
        1. checkout impl_commit^ 回退实现文件 (新建文件 pathspec 报错 → git rm 模拟)
        2. 回归测试 MUST FAIL (回退后仍 PASS ⇒ 测试无效, 未真正覆盖回归)
        3. finally checkout HEAD 恢复实现 (working tree 复原)
        4. 恢复后回归测试 MUST PASS

    失败 action=block (而非 retry): 无效回归测试须重写, 非重跑 Agent 可修复.
    非回归修复轮次 / 无运行时句柄 → pass (N/A). 与 G7 REDGuard 互补:
    REDGuard 校验"测试先于实现且曾红", RegressionGate 校验"测试真能红".
    """

    name = "RegressionGate"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root if project_root is not None else Path.cwd()
        task = _current_regression_task(state)
        if task is None:
            return GuardrailResult()  # 非回归修复轮次 → N/A pass

        task_id = getattr(task, "id", "?")
        test_id = getattr(task, "regression_test_id", "") or ""
        impl_commit = getattr(state, "commit_hash", "") or ""
        targets = list(getattr(task, "target_files", []) or [])
        impl_files = [f for f in targets if not _is_test_file(f)]

        if not impl_files:
            return GuardrailResult(
                action="block",
                message=f"回归修复 task {task_id} 无实现文件 — 无法验证回归测试有效性",
            )
        if not test_id:
            return GuardrailResult(
                action="block",
                message=f"回归修复 task {task_id} 缺 regression_test_id — 无法定位回归测试",
            )
        if not impl_commit:
            return GuardrailResult(
                action="block",
                message=f"回归修复 task {task_id} 无实现 commit_hash — 无法回退验证",
            )

        try:
            rc = _git_checkout_paths(f"{impl_commit}^", impl_files, root)
            if rc != 0:
                # S-19: 实现文件在 impl_commit 中新建, impl^ 无该 pathspec → git rm
                _git_rm(impl_files, root)
            if _run_test(test_id, root) != "FAIL":
                return GuardrailResult(
                    action="block",
                    message=(
                        f"回归测试 {test_id} 在回退实现后仍未 FAIL — "
                        "测试无效, 未真正捕捉回归"),
                )
        finally:
            _git_checkout_paths("HEAD", impl_files, root)

        if _run_test(test_id, root) != "PASS":
            return GuardrailResult(
                action="block",
                message=f"回归测试 {test_id} 恢复实现后未 PASS — 测试或实现不稳定",
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
        """工厂方法: 默认链 (G1-G6 基线 + G7 REDGuard + G8 FreshGate + G9 RegressionGate, §B3)."""
        return cls([
            RequirementValid(),
            PlanExists(),
            GitDiffExists(),
            TestsPass(),
            GitClean(),
            NoDeferredBlockingGap(),
            REDGuard(),
            FreshGate(),
            RegressionGate(),
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
            第一个不 pass 的 GuardrailResult (注入命中的 guardrail_name),
            或全 pass 时的 GuardrailResult("pass", "").
        """
        for g in self.guardrails:
            if g.timing != timing:
                continue
            if stage not in g.applies_to_stages:
                continue
            result = g.check(stage, state, project_root=project_root)
            if result.action != "pass":
                # S-4: 注入命中的 Guardrail 名, 供 handler 分源计数 + FreshGate 分流
                if not result.guardrail_name:
                    result.guardrail_name = g.name
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
            1. counter += 1 (S-4: key = f"{stage}:{guardrail_name}", 空名退回 stage)
            2. counter >= MAX_RETRY_PER_STAGE (3) → "stop" (不再清字段)
            3. counter  <  MAX_RETRY_PER_STAGE:
               - FreshGate(G8) → "rerun_gates" (只重跑 Gate, **不清** stage 字段,
                 避免丢弃已提交实现; S-4 特化语义)
               - 其余 (G3/G4/G7...) → "retry" + 清空 stage 字段 (重跑 Agent)

    Args:
        result: GuardrailChain.check() 返回的 GuardrailResult (含 guardrail_name).
        stage: 当前 Stage 名 (用于 counter key + 字段清空).
        state: EngineState 实例 (会被修改: 清字段).
        retry_counters: 共享计数器字典 (S-4: 按 stage:guardrail 隔离).

    Returns:
        主循环动作: "continue" | "stop" | "retry" | "rerun_gates".

    注: 防御性: 未知 action → "stop" (避免 Orchestrator 在非预期动作上僵死).
    """
    action: str = result.action

    if action == "pass":
        return "continue"

    if action == "block":
        return "stop"

    if action == "retry":
        # S-4: 同 stage 多 retry 型 Guardrail 各自独立预算 (key=stage:guardrail_name);
        # 空 guardrail_name (旧直调) 退回 stage 单键, 保持向后兼容.
        gname = getattr(result, "guardrail_name", "") or ""
        key = f"{stage}:{gname}" if gname else stage
        current = retry_counters.get(key, 0)
        # 先判定, 再累加: 已达上限 → stop 且不动 counter/state
        if current >= MAX_RETRY_PER_STAGE:
            return "stop"
        retry_counters[key] = current + 1
        # FreshGate(G8) retry 特化: 只重跑 Gate 刷新证据, 不清 stage 字段 (不丢实现)
        if gname == "FreshGate":
            return "rerun_gates"
        # 通用 retry: 清 stage 字段 + 重跑 Agent
        clear_stage_fields(state, stage)
        return "retry"

    # 未知 action (防御性)
    return "stop"


