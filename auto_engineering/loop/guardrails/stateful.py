"""G7/G8/G9 状态化 Guardrail — REDGuardrail, FreshGuardrail, RegressionGuardrail.

提取自 loop/guardrail.py (P1-2: guardrail.py 过大 — 1101 行, 12 类).

G7 REDGuardrail (§B3.1): TDD RED commit-time 校验
G8 FreshGuardrail (§B3.2): Gate 证据新鲜度锁定
G9 RegressionGuardrail (§B3.3): 回归修复测试有效性校验
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from auto_engineering.engine.guardrail_types import (
    Guardrail,
    GuardrailResult,
)
from auto_engineering.utils.git import run_git as _real_git

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

_logger = logging.getLogger(__name__)

# Injectable runners (defaults → real implementations; tests can inject stubs).
_run_git = _real_git
_test_runner = None  # None → use subprocess.run(["python", "-m", "pytest", ...])


def set_git_runner(runner) -> None:
    """Inject a stub git runner (tests only). Call with None to restore default."""
    global _run_git
    _run_git = _real_git if runner is None else runner


def set_test_runner(runner) -> None:
    """Inject a stub pytest runner (tests only). Call with None to restore default."""
    global _test_runner
    _test_runner = runner

# ==================== G7/G8 helpers (B3.1 / B3.2) ====================

# 严格模式 (opt-in): REDGuardrail checkout red_commit 重跑测试确认 FAIL.
# 默认 False — 信任 developer 提交的 red_evidence, 避免 checkout 重跑成本 (B3.1).
# P0-6: 延迟读取 — 模块导入时不再读 os.environ, 通过 _get_strict_red() 惰性求值
_STRICT_RED: bool | None = None  # None = 未初始化, 首次访问时从 RuntimeConfig 读取


def _get_strict_red() -> bool:
    """Lazy init for _STRICT_RED from RuntimeConfig (P0-6).

    AE_PRODUCTION=1 also activates strict RED (P1-12).
    """
    global _STRICT_RED
    if _STRICT_RED is None:
        from auto_engineering.config.runtime_config import get_default_config
        cfg = get_default_config()
        _STRICT_RED = cfg.strict_red or cfg.production_enabled
    return _STRICT_RED


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


def _git_commit_touches(commit: str, files: list[str], cwd: Path) -> bool:
    """检查 commit 是否触碰了 files 中的任何文件."""
    if not commit or not files:
        return False
    rc, _ = _run_git(cwd, "diff-tree", "--no-commit-id", "-r", commit, "--", *files)
    return rc == 0 and bool(_.strip())


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
    root = Path(project_root)
    _git = _run_git  # local ref for injectable override
    try:
        with tempfile.TemporaryDirectory() as wt:
            rc, _ = _git(root, "worktree", "add", "--detach", wt, test_commit)
            if rc != 0:
                return "UNKNOWN"
            try:
                if _test_runner is not None:
                    return _test_runner(test_commit, test_id, Path(wt))
                proc = subprocess.run(
                    ["python", "-m", "pytest", "-k", test_id, "-q", "--no-header"],
                    cwd=wt, capture_output=True, text=True, timeout=120,
                )
                return "FAIL" if proc.returncode != 0 else "PASS"
            finally:
                _git(root, "worktree", "remove", "--force", wt)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def aggregate_files_sha(files_changed: list[str], project_root: Path) -> str:
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


# ==================== G7 REDGuardrail / G8 FreshGuardrail ====================


class REDGuardrail(Guardrail):
    """G7: TDD RED commit-time 校验 (§B3.1).

    post/developer: 对本轮 batch 的每个 task, 若含测试文件, 校验存在一个
    **先于实现 commit** 的独立测试 commit 且当时 FAIL:
        1. `git log impl -- test_files` 定位先于实现的测试 commit (排除 impl 自身)
        2. merge-base --is-ancestor 确认测试 commit 是实现 commit 祖先
        3. 默认信任 red_evidence (red_commit 匹配); _STRICT_RED 则 checkout 重跑

    纯配置/文档 task (无测试文件) 豁免. 无运行时句柄 (batch_state/_plan) 或无
    impl commit_hash → pass (无对象可校验). 失败 action=retry (补证据后重试).

    与 G3/G4 不重叠: G3/G4 确认"有改动 + 测试绿", REDGuardrail 补充"测试先于实现且曾红".
    """

    name = "REDGuardrail"
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
        except (TypeError, ValueError, AttributeError):  # 句柄不完整时降级放行 (纯函数不抛给上层, 见 ABC check 约束)
            _logger.warning("_build_redguard_state: batch state parse failed, guardrail degraded", exc_info=True)
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
                # Check if impl_commit itself touches test files (GREEN commit 不应改测试)
                impl_touches_test = _git_commit_touches(impl_commit, test_files, root)
                detail = (
                    " — GREEN commit 修改了测试文件, 测试应在独立 RED commit 中创建"
                    if impl_touches_test else ""
                )
                return GuardrailResult(
                    action="retry",
                    message=f"task {task_id}: 无先于实现的测试 commit — 违反 TDD RED{detail}",
                )
            if not _git_is_ancestor(test_commit, impl_commit, root):
                return GuardrailResult(
                    action="retry",
                    message=f"task {task_id}: 测试 commit 非实现 commit 祖先",
                )
            ev = _find_evidence(red_evidence, task_id)
            if ev and ev.get("red_commit") == test_commit:
                continue  # 信任 developer 记录的 RED 证据
            if _get_strict_red():
                test_id = ev.get("test_id") if ev else None
                if _run_test_at_commit(test_commit, test_id, root) != "FAIL":
                    return GuardrailResult(
                        action="retry",
                        message=f"task {task_id}: 测试在 red_commit 未 FAIL — 非真 RED",
                    )
            else:
                return GuardrailResult(
                    action="retry",
                    message=(
                        f"task {task_id}: 缺 red_evidence — "
                        f"red_evidence 格式应为 [{{'task_id': '{task_id}', "
                        f"'red_commit': '<hash>'}}], 当前为 "
                        f"{type(red_evidence).__name__}"
                        + (f"[{type(red_evidence[0]).__name__}]" if red_evidence else "")
                        + ("" if red_evidence else " (空列表)")
                    ),
                )
        return GuardrailResult()


class FreshGuardrail(Guardrail):
    """G8: Gate 证据新鲜度锁定 (§B3.2).

    post/developer + post/critic: gate_results 每项记录运行时 files_changed 的
    聚合 sha256 (files_snapshot_sha, 由 run_gates 生产者契约注入, S-3). 若当前
    工作树聚合 sha 与某 Gate 记录不符 → 代码在 Gate 后又变更 → 证据陈旧 → retry.

    retry 语义特化 (S-4): 不清 stage 字段/不丢弃已提交实现, 而是触发 rerun_gates
    (仅重跑 Gate 刷新 gate_results). 由 handle_guardrail_result 依 guardrail_name 分流.
    旧格式 (无 files_snapshot_sha) 或空 gate_results → pass (无可比对基线).
    """

    name = "FreshGuardrail"
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
        current_sha = aggregate_files_sha(files_changed, root)
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

    与 REDGuardrail 同源读 state.batch_state / state._plan (TickOrchestrator 注入).
    非 batch 运行时 (无句柄) 或无回归修复 task → None (Gate 判 N/A pass).
    """
    batch_state = getattr(state, "batch_state", None)
    plan = getattr(state, "_plan", None)
    if batch_state is None or plan is None:
        return None
    try:
        tasks = batch_state.current_batch_tasks(plan)
    except (TypeError, ValueError, AttributeError):  # 句柄不完整时降级 (纯函数不抛给上层, 见 ABC check 约束)
        _logger.warning("_find_regression_task: batch state parse failed, gate degraded", exc_info=True)
        return None
    for task in tasks or []:
        if getattr(task, "kind", "") == "regression_fix":
            return task
    return None


class RegressionGuardrail(Guardrail):
    """G9: 回归修复测试有效性校验 — revert→MUST FAIL→restore (§B3.3).

    post/developer: 仅当本轮 batch 含 kind=="regression_fix" task 时生效.
    验证该 task 新增/修改的回归测试**确实能捕捉被修复的回归**:
        1. checkout impl_commit^ 回退实现文件 (新建文件 pathspec 报错 → git rm 模拟)
        2. 回归测试 MUST FAIL (回退后仍 PASS ⇒ 测试无效, 未真正覆盖回归)
        3. finally checkout HEAD 恢复实现 (working tree 复原)
        4. 恢复后回归测试 MUST PASS

    失败 action=block (而非 retry): 无效回归测试须重写, 非重跑 Agent 可修复.
    非回归修复轮次 / 无运行时句柄 → pass (N/A). 与 G7 REDGuardrail 互补:
    REDGuardrail 校验"测试先于实现且曾红", RegressionGuardrail 校验"测试真能红".
    """

    name = "RegressionGuardrail"
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
