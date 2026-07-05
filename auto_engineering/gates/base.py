"""v2.0 Phase 04 — Gate 基类 + Verdict dataclass.

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 + §4.8 关键数据结构.

核心要点:
    - Gate 基类: 实现 run() 接口, 入参 project_root, 返回 Verdict
    - Verdict: 数据类, 携带 passed / message / gate_name
    - 7 道 Gate: safety / lint / type_check / contract / test / coverage / build
    - 单 Gate 失败不抛异常, 返回 passed=False + message (上层决定 block / drop / retry)

向后兼容:
    - 旧版 Gate.check(stage, context) 接口保留(由 Phase 1 Guardrail 体系使用)
    - 新增 Gate.run(project_root) 接口(由 Phase 04 v2.0 7 道 Gate 使用)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ============================================================
# v2.0 向后兼容: GateResult(Phase 1 Gate 体系的 2 态结果)
# ============================================================


@dataclass
class GateResult:
    """v2.0 Gate 检查结果(2 态: passed / failed).

    保留供 Phase 1 代码使用. v2.0 新代码应使用 Verdict.
    """

    passed: bool
    message: str = ""

    @classmethod
    def pass_(cls, msg: str = "") -> GateResult:
        return cls(passed=True, message=msg)

    @classmethod
    def fail(cls, msg: str) -> GateResult:
        return cls(passed=False, message=msg)


# ============================================================
# v2.0 新接口: GateVerdict (v5.0 §B6.1 — Verdict → GateVerdict 重命名)
# ============================================================


@dataclass
class GateVerdict:
    """Gate 检查结果 (v5.0 §B6.1 重命名自 Verdict).

    Attributes:
        gate_name: Gate 名称(由 Gate 实例填入, 调用方无需传)
        passed: True = 通过, False = 失败
        message: 失败/通过的详细信息(便于排查)
    """

    gate_name: str = ""
    passed: bool = False
    message: str = ""

    # 注: passed 字段与 GateVerdict.passed() 类方法同名是 dataclass 不可避免的副作用,
    # 通过 @classmethod 访问避免歧义. 字段访问走 v.passed, 方法访问走 GateVerdict.passed().
    @classmethod
    def passed(cls, msg: str = "", gate_name: str = "") -> GateVerdict:  # noqa: F811
        """构造一个通过的 GateVerdict."""
        return cls(gate_name=gate_name, passed=True, message=msg)

    @classmethod
    def failed(cls, msg: str, gate_name: str = "") -> GateVerdict:
        """构造一个失败的 GateVerdict."""
        return cls(gate_name=gate_name, passed=False, message=msg)


# v5.0 §B6.1 向后兼容: 保留 Verdict 作为 GateVerdict 的别名 (1 版本过渡期)
# 所有引用 Verdict 的代码继续工作, 等下次大版本可彻底移除
Verdict = GateVerdict
__all__ = ["GateVerdict", "Verdict"]  # noqa: F822 (Verdict 通过 module __all__ 暴露)


class Gate:
    """Gate 基类(v2.0 Phase 04 新接口).

    子类必须实现 run(project_root) 方法, 返回 Verdict.
    默认实现: 检查项目根存在 → 委托子类.

    旧接口 Gate.check(stage, context) 保留供 v2.0 Guardrail 体系使用.

    v5.0 §B2.9 扩展:
        - 类属性 applies_to_stages: tuple[str, ...] — 标识该 Gate 在哪些
          Stage 阶段运行 (architect/developer/critic). 默认 = 三阶段全跑.
        - run() 新增 contracts: dict | None = None 参数 — 供 ContractGate
          等需要契约数据的 Gate 使用 (向后兼容: 默认 None).
    """

    name: str = "base"
    # v5.0 §B2.9: 默认覆盖三阶段, 子类按需覆盖 (如 CoverageGate 仅 developer)
    applies_to_stages: tuple[str, ...] = ("architect", "developer", "critic")

    def run(
        self,
        project_root: Path,
        contracts: dict | None = None,
    ) -> Verdict:
        """执行 Gate 检查.

        Args:
            project_root: 项目根目录路径
            contracts: v5.0 §B2.9 — 可选契约字典 (供 ContractGate 等使用)

        Returns:
            Verdict (passed + message)

        Raises:
            NotImplementedError: 子类未实现时
        """
        raise NotImplementedError(
            f"{type(self).__name__}.run() must be implemented by subclass"
        )

    # 旧接口(向后兼容, 由 v2.0 Guardrail 链调用)
    def check(self, stage: Any, context: Any) -> Verdict:
        """v2.0 兼容接口. 返回 pass 占位(实际 v2.0 用 GuardrailResult)."""
        return Verdict.passed("legacy v2.0 path", gate_name=self.name)


# v5.0 §B6.1+§B6.2 — DEFAULT_GATES 入口
# 7 道 Gate 的默认实例列表 (供 Orchestrator/run_gates 直接 import)
# 顺序: safety → lint → type_check → contract → test → coverage → build
#
# 在 base.py 末尾惰性构造 (避免循环 import):
#   - 直接实例化依赖子模块 (lint/type_check/...), 须放在所有 Gate 类已 import 后
#   - 测试也直接 from auto_engineering.gates.base import DEFAULT_GATES
DEFAULT_GATES: list["Gate"] = []


def _build_default_gates(manifest: dict | None = None) -> list["Gate"]:
    """v5.0 §B6.1+§B6.2 — 构造 7 道 Gate 的默认实例列表.

    惰性加载: 在 base.py 末尾调用, 此时子模块 (lint/type_check/...) 已被 import.
    顺序: safety → lint → type_check → contract → test → coverage → build

    v5.0 §IL-AC-02 扩展:
        - manifest 不为 None 时, 从 init-manifest.json 读 conventions 替换默认
          linter / type_checker / test_runner
        - manifest 为 None 时, 用 python 默认 (ruff/mypy/pytest)
    """
    # 局部 import 避免模块加载顺序问题
    from auto_engineering.gates.build import BuildGate
    from auto_engineering.gates.contract import ContractGate
    from auto_engineering.gates.coverage import CoverageGate
    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate
    from auto_engineering.gates.test import TestGate
    from auto_engineering.gates.type_check import TypeCheckGate
    from auto_engineering.gates.quality_gate import TDDGate, StageTransitionGate

    if manifest is not None:
        # v5.0 §IL-AC-02: 用 manifest 构造 lint/type_check/test
        lint_gate = LintGate.from_manifest(manifest)
        type_check_gate = TypeCheckGate.from_manifest(manifest)
        test_gate = TestGate.from_manifest(manifest)
    else:
        # 默认: python 生态
        lint_gate = LintGate()
        type_check_gate = TypeCheckGate()
        test_gate = TestGate()

    return [
        SafetyGate(use_gitleaks=False),
        StageTransitionGate(),
        lint_gate,
        type_check_gate,
        ContractGate(),
        test_gate,
        TDDGate(),
        CoverageGate(),
        BuildGate(),
    ]


def build_gates_from_manifest(manifest: dict) -> list["Gate"]:
    """v5.0 §IL-AC-02: 从 init-manifest.json 构造完整 7 道 Gate 列表."""
    return _build_default_gates(manifest=manifest)


# 模块加载时立即构建 (确保 from .base import DEFAULT_GATES 可用)
DEFAULT_GATES = _build_default_gates()