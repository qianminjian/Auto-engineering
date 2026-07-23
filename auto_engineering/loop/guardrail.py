"""M2 Guardrail 链 — GuardrailResult + Guardrail ABC + 12 Guardrails + Chain.

设计参考: v5.6-Design-Loop.md §B2.3 (Guardrail 接口契约)
                   + §B1.8 (GuardrailResult 数据类)
                   + §B5.1 (5 Guardrail 规格 G1-G5)
                   + §B10.5 / §B3 (G6 NoDeferredBlockingGap)
                   + §B3.1/B3.2/B3.3 (G7 REDGuardrail / G8 FreshGuardrail / G9 RegressionGuardrail)
                   + §B5.2 (handle_guardrail_result 3 态)
                   + 附录 C R-5 (GitDiffExists 新仓库降级)

v5.4 P2-8: drop 态已从类型系统和 handler 中完全移除.
           保留 3 态 pass/block/retry 覆盖所有场景.

模块职责:
    - GuardrailResult / Guardrail ABC: 契约定义 (action 3 态)
    - 9 Guardrail (G1-G6 基线 + G7/G8/G9): 内置检查 (只用 pass/block/retry)
    - GuardrailChain: 编排 (fail-fast + timing/stage 过滤)
    - Orchestrator 内联 _handle_guardrail_result: action 分发 (continue/stop/retry/rerun_gates)

依赖:
    - stage_router.clear_stage_fields (Stage 字段清理复用)
    - EngineState (任意对象, duck-typed)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING, ClassVar, Literal

from auto_engineering.engine.gap_analysis import (
    _BLOCKING_FORBIDDEN as _BLOCKING_FORBIDDEN_RESOLUTIONS,
)
from auto_engineering.shared.guardrail import (
    Action,
    Guardrail,
    GuardrailResult,
)
from auto_engineering.loop.guardrails.stateful import (
    FreshGuardrail,
    REDGuardrail,
    RegressionGuardrail,
)
from auto_engineering.utils.git import run_git as _run_git
from auto_engineering.utils.git import run_git_diff as _run_git_diff

__all__ = [
    "MAX_RETRY_PER_STAGE",
    "Action",
    "AuditTimingGuardrail",
    "FileAccessGuardrail",
    "FreshGuardrail",
    "GitClean",
    "GitDiffExists",
    "Guardrail",
    "GuardrailChain",
    "GuardrailResult",
    "PlanExists",
    "REDGuardrail",
    "RegressionGuardrail",
    "RequirementValid",
    "TestsPass",
]

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

# P1-3: GuardrailResult + Guardrail ABC 已提取到 gates/guardrail_base.py
# Action / GuardrailResult / Guardrail 从共享模块导入
# 本地仅保留 Action re-export + MAX_RETRY_PER_STAGE + 具体 Guardrail 实现

MAX_RETRY_PER_STAGE = 3


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
        resolved_root = project_root if project_root is not None else Path.cwd()

        # 先试 HEAD~1..HEAD (有 commit 的仓库)
        rc1, stdout1 = _run_git_diff(resolved_root, ["HEAD~1..HEAD"])
        if rc1 == 0:
            if stdout1.strip():
                return GuardrailResult()  # pass
            return GuardrailResult(
                action="retry",
                message="git diff HEAD~1..HEAD 为空,developer 未产生代码变更",
            )

        # 降级: HEAD~1 不存在 (新仓库), 用 --cached
        rc2, stdout2 = _run_git_diff(resolved_root, ["--cached"])
        if rc2 == 0 and stdout2.strip():
            return GuardrailResult()  # pass via cached

        # 降级: --cached 也为空, 但 HEAD 存在 → StandaloneDriver auto_commit 路径
        # developer 已通过 _auto_commit() 提交, 检查 HEAD 是否包含文件变更
        rc3, _ = _run_git(resolved_root, "rev-parse", "HEAD")
        if rc3 == 0:
            rc4, stdout4 = _run_git(resolved_root, "diff-tree", "--no-commit-id", "-r", "HEAD")
            if rc4 == 0 and stdout4.strip():
                return GuardrailResult()  # pass: HEAD commit 包含文件变更
            # 降级: diff-tree 对 root commit 返回空 (无 parent 可 diff)
            # → git show --stat (不依赖 parent, 列出 HEAD 的文件变更)
            rc5, stdout5 = _run_git(resolved_root, "show", "--stat", "--format=", "HEAD")
            if rc5 == 0 and stdout5.strip():
                return GuardrailResult()

        return GuardrailResult(
            action="retry",
            message="新仓库且无变更 (staged/committed),developer 需先 git add/commit",
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
        if not isinstance(results, dict):
            return GuardrailResult(
                action="retry",
                message=f"test_results 应为 dict, 实际为 {type(results).__name__}: {str(results)[:100]}",
            )
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
        resolved_root = project_root if project_root is not None else Path.cwd()
        rc, stdout = _run_git(resolved_root, "status", "--porcelain")
        if rc != 0:
            # git 命令失败 (非 git 目录等) → block (让 Orchestrator 报警)
            return GuardrailResult(
                action="block",
                message=f"git status 失败 rc={rc}",
            )
        # 只检查 tracked 文件的变更 (M/A/D/R/C), 忽略 untracked (??) 和 ignored (!!)
        dirty_lines = [
            l for l in stdout.splitlines()
            if l.strip() and not l.startswith("??") and not l.startswith("!!")
        ]
        if dirty_lines:
            return GuardrailResult(
                action="block",
                message="working tree 有未提交变更,需先 commit",
            )
        return GuardrailResult()


# architectural gap 禁止的 resolution (§B10.5: 契约模糊不允许延后, 须 Fill/Research)
# _BLOCKING_FORBIDDEN_RESOLUTIONS 复用 gap_analysis SSOT (顶部 import) — A4 消除常量 DRY.
# gap_analysis._BLOCKING_FORBIDDEN 是 architectural gap 禁止 resolution 的唯一定义源.


class NoDeferredBlockingGap(Guardrail):
    """G6: has_blocking 时 architectural gap 不允许 Defer/Defer+Research (§B10.5 / B3).

    post/gap_review: 用户在 gap_review 对每个 gap 决策后, 若存在 grade==architectural
    的 gap 被标为 defer/defer_research → block (architectural 契约模糊不允许延后, 否则
    组件设计无契约依据). 决策取自 state.pending_gap_decisions (尚未 apply 到 gap_report),
    grade 取自 state.gap_report_json (gap_scan 判定). 非 design-doc 模式无 gap_report → pass.

    失败 action=block (用户须改为 Fill/Research 重提 gap_review). 与
    gap_analysis.GapReport.validate_resolutions **共享禁止集常量**
    (_BLOCKING_FORBIDDEN, 已复用 SSOT) 但**校验时序不同**: 本 Guardrail 校验
    pending_gap_decisions (apply 前拦截), validate_resolutions 校验 report 内
    已 apply 的 resolution (apply 后审查) — 故不可合并为同一方法.
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


# G7 REDGuardrail / G8 FreshGuardrail / G9 RegressionGuardrail
# 已提取到 auto_engineering/loop/guardrails/stateful.py (P1-2)


# ==================== G11 FileAccessGuardrail ====================


class FileAccessGuardrail(Guardrail):
    """G11: 检查 developer 文件操作范围是否在 batch_plan 声明内 (T62 + T62a).

    post/developer: 收集 batch_plan 中所有 task 的 file_targets，用 pathspec
    glob 匹配对比 files_changed 是否全部在声明范围内。白名单路径
    (.ae-state/**、_scratch/**) 自动放行。首次运行无 batch_plan → skip pass。

    T109e L4: PII 内容扫描 — 检查 developer 创建的源代码文件是否包含
    身份证号/手机号/银行卡号/API Key 等敏感信息。

    设计 ref: v5.6-Design-Loop.md appendix E §E.4。
    """

    name = "FileAccessGuardrail"
    timing = "post"
    applies_to_stages = ("developer",)

    _AUTO_ALLOW_PATTERNS: ClassVar[list[str]] = [
        ".ae-state/**",
        "_scratch/**",
        ".gitignore",
        "pyproject.toml",
    ]

    _SCAN_FILE_EXTS: ClassVar[set[str]] = {
        ".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".yaml", ".yml",
        ".java", ".go", ".rs", ".vue", ".svelte",
    }

    def __init__(self) -> None:
        import pathspec

        self._paths_spec_module = pathspec
        self._auto_allow_spec = pathspec.PathSpec.from_lines(
            "gitignore", self._AUTO_ALLOW_PATTERNS
        )
    @staticmethod
    def _get_pii_redactor():
        from auto_engineering.pii.redactor import get_pii_redactor
        return get_pii_redactor()

    def _scan_file_for_pii(self, filepath: Path) -> list[dict]:
        """T109e: 扫描单个文件内容中的 PII."""
        try:
            content = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        redactor = self._get_pii_redactor()
        return redactor.scan_dict({"content": content})

    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        if stage not in self.applies_to_stages:
            return GuardrailResult()

        files_changed = getattr(state, "files_changed", []) or []
        if not files_changed:
            return GuardrailResult()

        batch_plan = getattr(state, "batch_plan", []) or []

        # 收集所有 batch_plan 中声明的 file_targets
        allowed_patterns: list[str] = []
        for batch in batch_plan:
            for task in batch.get("tasks", []):
                for ft in task.get("file_targets", []):
                    allowed_patterns.append(ft)

        if not allowed_patterns:
            return GuardrailResult()  # 无约束则放行（首次运行）

        target_spec = self._paths_spec_module.PathSpec.from_lines(
            "gitignore", allowed_patterns
        )

        # 检查 files_changed
        out_of_bounds: list[str] = []
        for f in files_changed:
            if self._auto_allow_spec.match_file(f):
                continue
            if not target_spec.match_file(f):
                out_of_bounds.append(f)

        if out_of_bounds:
            return GuardrailResult(
                action="block",
                message=(
                    f"越界文件修改（不在 batch_plan file_targets 内）: "
                    f"{', '.join(out_of_bounds)}"
                ),
            )

        # T109e L4: PII 内容扫描 — 检查创建的源代码文件
        from auto_engineering.config.runtime_config import get_default_config
        _cfg = get_default_config()
        if _cfg.pii_guardrail and project_root:
            pii_files: list[str] = []
            for f in files_changed:
                fpath = project_root / f
                if not fpath.suffix or fpath.suffix not in self._SCAN_FILE_EXTS:
                    continue
                if not fpath.exists():
                    continue
                findings = self._scan_file_for_pii(fpath)
                if findings:
                    pii_files.append(f"{f} ({len(findings)} matches)")
            if pii_files:
                mode = _cfg.pii_guardrail_mode
                if mode == "block":
                    return GuardrailResult(
                        action="retry",
                        message=(
                            f"PII detected in changed files: "
                            f"{'; '.join(pii_files)}"
                        ),
                    )
                else:
                    _logger.warning(
                        "G11 PII scan: %d files with PII detected: %s",
                        len(pii_files), "; ".join(pii_files))

        return GuardrailResult()

    def _is_auto_allowed(self, filepath: str) -> bool:
        return self._auto_allow_spec.match_file(filepath)


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
        """工厂方法: 默认链 (G1-G9 基线 + G10 PIIGuardrail + G11 FileAccessGuardrail
        + G12 AuditTimingGuardrail, §B3 + T112)."""
        from auto_engineering.pii.guardrail import PIIGuardrail

        return cls([
            RequirementValid(),
            PlanExists(),
            GitDiffExists(),
            TestsPass(),
            GitClean(),
            NoDeferredBlockingGap(),
            REDGuardrail(),
            FreshGuardrail(),
            RegressionGuardrail(),
            PIIGuardrail(),
            FileAccessGuardrail(),
            AuditTimingGuardrail(),
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
            project_root: 项目根目录 (None → fallback 当前目录).

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
                # S-4: 注入命中的 Guardrail 名, 供 handler 分源计数 + FreshGuardrail 分流
                if not result.guardrail_name:
                    result.guardrail_name = g.name
                return result
        return GuardrailResult()



# ==================== G12 AuditTimingGuardrail (T112) ====================


class AuditTimingGuardrail(Guardrail):
    """G12: 审计阶段 pass-through 检测 — 证据组合检测器 (T112).

    三重证据：E1 耗时过短 + E2 findings 空 + E3 p0/p1 全零。
    E2/E3 不独立（findings 空 → p0/p1 必零），合并为一个内容信号：
        effective = E1 + max(E2, E3)
        effective == 2 → retry（快 + 内容空，双重确认）
        effective == 1 → pass（单维度触发，仅 WARN 日志）
        effective == 0 → pass（正常）

    冷启动（action_timestamp == 0.0）→ skip pass。
    仅适用于 spawn 阶段：component_verifier, plate_deep_audit,
    system_verifier, system_deep_audit, critic。

    设计 ref: IMPLEMENTATION-TRACKER.md T112 详细 (2026-07-21 深度分析)。
    """

    name = "AuditTimingGuardrail"
    timing = "post"
    applies_to_stages = (
        "component_verifier", "plate_deep_audit",
        "system_verifier", "system_deep_audit", "critic",
    )

    _STAGE_MIN_SECONDS: dict[str, float] = {
        "component_verifier": 5.0,
        "plate_deep_audit": 10.0,
        "system_verifier": 5.0,
        "system_deep_audit": 10.0,
        "critic": 3.0,
    }

    def check(
        self,
        stage: str,
        state: "EngineState",
        project_root: Path | None = None,
    ) -> GuardrailResult:
        import time

        action_ts = getattr(state, "action_timestamp", 0.0) or 0.0
        if action_ts == 0.0:
            return GuardrailResult()  # cold start

        threshold = self._STAGE_MIN_SECONDS.get(stage)
        if threshold is None:
            return GuardrailResult()  # not applicable

        elapsed = time.time() - action_ts
        e1 = 1 if elapsed < threshold else 0

        findings = getattr(state, "findings", None)
        e2 = 1 if (findings is None or (isinstance(findings, list) and len(findings) == 0)) else 0

        p0 = getattr(state, "p0_count", None) or 0
        p1 = getattr(state, "p1_count", None) or 0
        e3 = 1 if (p0 == 0 and p1 == 0) else 0

        effective = e1 + max(e2, e3)

        if effective >= 2:
            return GuardrailResult(
                action="retry",
                message=(
                    f"AuditTimingGuardrail: {stage} 疑似 pass-through "
                    f"(elapsed={elapsed:.1f}s < {threshold}s, "
                    f"findings={'空' if e2 else '有内容'}, "
                    f"p0={p0}, p1={p1})"
                ),
            )

        if effective == 1:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "AuditTimingGuardrail: %s 单证据触发 (elapsed=%.1fs, "
                "threshold=%.0fs, e1=%d, e2=%d, e3=%d) — WARN only",
                stage, elapsed, threshold, e1, e2, e3,
            )

        return GuardrailResult()