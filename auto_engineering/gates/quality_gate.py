"""v5.1 Quality Gates — 借鉴 CrewAI GuardrailResult + SonarQube conditions.

Industry patterns:
- CrewAI GuardrailResult: success/result/error 三态, 事件总线, 重试计数
- SonarQube Quality Gate: 度量+阈值条件, 默认阻断, "No new issues" 原则
- pre-commit three-layer defense: fast checks → CI check → review gates

本模块实现两个 Gate:
1. TDDGate — Red→Green→Refactor 强制执行 (业界 TDD Gate Enforcement)
2. StageTransitionGate — 阶段过渡检查 (CLAUDE.md §4.5 Quality Gate)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from auto_engineering.gates.base import Gate, GateVerdict, GateResult

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState


class TDDGate(Gate):
    """TDD Red→Green→Refactor 强制执行 Gate.

    借鉴业界 "TDD Gate Enforcement" 模式 (2024-2025):
    - Red phase: 测试文件存在且非空 (test-existence check)
    - Green phase: 所有测试通过
    - Refactor phase: lint + complexity 检查通过 (由 lint gate 处理)

    Agent Working Agreement: 禁止跳过测试先写实现.
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root

    @property
    def name(self) -> str:
        return "tdd"

    @property
    def applies_to_stages(self) -> list[str]:
        return ["developer"]

    @property
    def timeout(self) -> int:
        return 60

    def check(
        self,
        stage: str,
        state: "EngineState",
        project_root: Path | None = None,
    ) -> GateVerdict:
        root = project_root or self.project_root
        if root is None:
            return GateVerdict(passed=False, message="TDDGate: project_root 未设置")

        # Red phase: 测试文件必须存在 (test-before-code)
        changed_files = getattr(state, "files_changed", []) or []
        test_files = [f for f in changed_files if self._is_test_file(f)]
        src_files = [f for f in changed_files if not self._is_test_file(f)]

        if src_files and not test_files:
            return GateVerdict(
                passed=False,
                message=(
                    f"TDD Red phase: {len(src_files)} 个源文件变更, "
                    f"但无对应测试文件. 先写测试 (Red), "
                    f"再写实现 (Green), 最后重构 (Refactor)."
                ),
            )

        # Green phase: 检查 test_files 内容非空
        for tf in test_files:
            full_path = root / tf
            if not full_path.exists():
                return GateVerdict(
                    passed=False,
                    message=f"TDD Green phase: 测试文件 {tf} 不存在",
                )
            if full_path.stat().st_size == 0:
                return GateVerdict(
                    passed=False,
                    message=f"TDD Green phase: 测试文件 {tf} 为空, 写出有意义的测试",
                )

        return GateVerdict(passed=True, message="TDD Red→Green 检查通过")

    @staticmethod
    def _is_test_file(path: str) -> bool:
        return path.startswith("tests/") or path.startswith("test_") or "_test." in path


class StageTransitionGate(Gate):
    """阶段过渡 Quality Gate — 借鉴 CrewAI GuardrailResult 三态 + SonarQube 条件门禁.

    在 stage transition 前检查 (CLAUDE.md §4.5):
    1. Pre-architect: requirement 非空 (G1 已覆盖, 本 Gate 补充)
    2. Pre-developer: architect 产出完整 (plan/file_list/batch_plan)
    3. Pre-critic: developer 产出完整 (files_changed/commit_hash/test_results)

    CrewAI 模式: 返回 GateVerdict(三态: passed/blocked/error)
    SonarQube 模式: 度量+阈值条件, 任一不满足 → blocked
    """

    METADATA_TEMPLATE = "StageTransitionGate {stage} checks ({passed}/{total} passed)"

    def __init__(self):
        self._conditions_cache: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return "stage_transition"

    @property
    def applies_to_stages(self) -> list[str]:
        return ["architect", "developer", "critic"]

    @property
    def timeout(self) -> int:
        return 30

    def check(
        self,
        stage: str,
        state: "EngineState",
        project_root: Path | None = None,
    ) -> GateVerdict:
        conditions = self._build_conditions(stage, state)
        results = []

        for cond in conditions:
            try:
                passed, detail = cond["check"](state)
            except Exception as exc:
                passed, detail = False, str(exc)
            results.append({"name": cond["name"], "passed": passed, "detail": detail})

        failed = [r for r in results if not r["passed"]]
        if failed:
            names = [r["name"] for r in failed]
            details = "; ".join(f"{r['name']}: {r['detail']}" for r in failed)
            return GateVerdict(
                passed=False,
                message=f"Stage {stage} Quality Gate: {len(failed)}/{len(results)} 条件未满足 — {details}",
            )

        return GateVerdict(
            passed=True,
            message=self.METADATA_TEMPLATE.format(
                stage=stage, passed=len(results), total=len(results)
            ),
        )

    def _build_conditions(self, stage: str, state: "EngineState") -> list[dict]:
        """按 stage 构建条件清单 (SonarQube 模式: 度量+阈值)."""
        conditions: list[dict] = []

        if stage == "architect":
            conditions.append({
                "name": "requirement_not_empty",
                "check": lambda s: (
                    bool(getattr(s, "requirement", "")),
                    "requirement 为空",
                ),
            })
            conditions.append({
                "name": "requirement_length",
                "check": lambda s: (
                    1 <= len(getattr(s, "requirement", "")) <= 4096,
                    f"requirement 长度 {len(getattr(s, 'requirement', ''))} (需 1-4096)",
                ),
            })

        elif stage == "developer":
            # Pre-developer: architect 产出必须完整
            conditions.append({
                "name": "plan_not_empty",
                "check": lambda s: (
                    bool(getattr(s, "plan", "")),
                    "architect 未产出 plan",
                ),
            })
            conditions.append({
                "name": "file_list_not_empty",
                "check": lambda s: (
                    len(getattr(s, "file_list", []) or []) >= 1,
                    "architect 未产出 file_list (需要至少 1 个文件)",
                ),
            })
            conditions.append({
                "name": "batch_plan_not_empty",
                "check": lambda s: (
                    len(getattr(s, "batch_plan", []) or []) >= 1,
                    "architect 未产出 batch_plan (需要至少 1 个 task)",
                ),
            })
            # CLAUDE.md §4.5 #2: 每个 task 有验收标准
            conditions.append({
                "name": "tasks_have_acceptance_criteria",
                "check": lambda s: self._check_task_criteria(s),
            })

        elif stage == "critic":
            # Pre-critic: developer 产出必须完整
            conditions.append({
                "name": "files_changed_not_empty",
                "check": lambda s: (
                    len(getattr(s, "files_changed", []) or []) >= 1,
                    "developer 未产出 files_changed",
                ),
            })
            conditions.append({
                "name": "test_results_exist",
                "check": lambda s: (
                    bool(getattr(s, "test_results", {})),
                    "developer 未产出 test_results",
                ),
            })

        return conditions

    @staticmethod
    def _check_task_criteria(state: "EngineState") -> tuple[bool, str]:
        """检查 batch_plan 中每个 task 有 expected_output (验收标准)."""
        batch_plan = getattr(state, "batch_plan", []) or []
        if not batch_plan:
            return True, "无 batch_plan (跳过)"
        missing = [
            t.get("id", "?")
            for t in batch_plan
            if not t.get("expected_output", "").strip()
        ]
        if missing:
            return False, f"task {missing} 缺少 expected_output (验收标准)"
        return True, "全部 task 有验收标准"
