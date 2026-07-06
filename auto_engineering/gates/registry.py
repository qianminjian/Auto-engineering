"""v5.0 §B6.1+§B6.2 — Gate 注册表 + DEFAULT_GATES 默认实例列表.

从 base.py 提取 (v5.4 审计), 消除 gates/base.py ↔ gates/build.py 导入循环.

单向依赖: registry → 各具体 Gate 模块 → base.py (Gate ABC).
base.py 不再引用任何子类, 循环消除.

v5.4 审计 r3 P1-1: LANGUAGE_TOOLS + get_gate_tools_from_manifest 从
loop/init_contract.py 迁移至此, 消除 gates → loop 反向依赖.
"""

from __future__ import annotations

from typing import Any

from auto_engineering.gates.audit import AuditGate
from auto_engineering.gates.base import Gate
from auto_engineering.gates.build import BuildGate
from auto_engineering.gates.contract import ContractGate
from auto_engineering.gates.lint import LintGate
from auto_engineering.gates.safety import SafetyGate
from auto_engineering.gates.test_gate import TestGate
from auto_engineering.gates.type_check import TypeCheckGate

# v5.4 Q1 + P1-6: TDDGate + StageTransitionGate 已删除.
# 它们实现 check(stage, state, project_root) 而非 run(project_root),
# 本质上是有状态 Guardrail 检查而非无状态 Gate.
# 如需 Guardrail 集成参考, 见 git 历史 _stage_checks.py + quality_gate.py.

# ============================================================
# 5 语言默认 Gate 工具映射 (v5.0 §IL.2)
# v5.4 审计 r3 P1-1: 从 loop/init_contract.py 迁移至此
# ============================================================

LANGUAGE_TOOLS: dict[str, tuple[str, str, str]] = {
    "python": ("ruff", "pyright", "pytest"),
    "typescript": ("eslint", "tsc", "vitest"),
    "go": ("golangci-lint", "go vet", "go test"),
    "rust": ("clippy", "cargo check", "cargo test"),
    "bash": ("shellcheck", "bash -n", "bats"),
}


def _default_tools_for(language: str) -> tuple[str, str, str]:
    """查 LANGUAGE_TOOLS, 不支持则回退 python."""
    return LANGUAGE_TOOLS.get(language, LANGUAGE_TOOLS["python"])


def get_gate_tools_from_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    """从 init-manifest conventions 提取 Gate 工具配置 (v5.0 §IL-AC-02).

    Args:
        manifest: load_init_manifest 返回的 dict.

    Returns:
        {"linter": str, "type_checker": str, "test_runner": str}
        - 若 conventions 缺失, 回退到 language 默认工具 (LANGUAGE_TOOLS)
        - 若 language 也不支持, 用 python 默认 (向后兼容)
    """
    conventions = manifest.get("conventions")
    language = manifest.get("language", "python")
    if not isinstance(conventions, dict):
        return dict(zip(("linter", "type_checker", "test_runner"), _default_tools_for(language)))
    linter = conventions.get("linter")
    type_checker = conventions.get("type_checker")
    test_runner = conventions.get("test_runner")
    default = _default_tools_for(language)
    return {
        "linter": linter or default[0],
        "type_checker": type_checker or default[1],
        "test_runner": test_runner or default[2],
    }


def _build_default_gates(manifest: dict | None = None) -> list[Gate]:
    """构造 6 道 Gate 的默认实例列表.

    v5.4 Q1: TDDGate + StageTransitionGate 从 DEFAULT_GATES 移除.
    它们实现 check(stage, state, project_root) 而非 run(project_root),
    本质是 Guardrail 检查不是 Gate 质量检查.

    v5.0 §IL-AC-02 扩展:
        - manifest 不为 None 时, 从 init-manifest.json 读 conventions 替换默认
          linter / type_checker / test_runner
        - manifest 为 None 时, 用 python 默认 (ruff/mypy/pytest)
    """
    if manifest is not None:
        lint_gate = LintGate.from_manifest(manifest)
        type_check_gate = TypeCheckGate.from_manifest(manifest)
        test_gate = TestGate.from_manifest(manifest)
    else:
        lint_gate = LintGate()
        type_check_gate = TypeCheckGate()
        test_gate = TestGate()

    return [
        SafetyGate(use_gitleaks=False),
        lint_gate,
        type_check_gate,
        AuditGate(),
        ContractGate(),
        test_gate,
        BuildGate(),
    ]


def build_gates_from_manifest(manifest: dict) -> list[Gate]:
    """v5.0 §IL-AC-02: 从 init-manifest.json 构造完整 Gate 列表.

    外部 API — 由 init_contract flow 调用, 将 init-manifest.json 中的
    conventions 映射为具体 Gate 实例 (linter/type_checker/test_runner).
    """
    return _build_default_gates(manifest=manifest)


_default_gates_cache: list[Gate] | None = None


def reset_default_gates_cache() -> None:
    """v5.4 审计 P1-10: 重置 DEFAULT_GATES 全局缓存, 供测试使用."""
    global _default_gates_cache
    _default_gates_cache = None


def get_default_gates() -> list[Gate]:
    """惰性构造 6 道默认 Gate（避免 import 时副作用）."""
    global _default_gates_cache
    if _default_gates_cache is None:
        _default_gates_cache = _build_default_gates()
    return _default_gates_cache


# v5.4 审计 P1-11: 惰性构造 DEFAULT_GATES 避免 import 时副作用.
# 模块 __getattr__ 在首次访问时触发 get_default_gates().
def __getattr__(name: str):
    if name == "DEFAULT_GATES":
        return get_default_gates()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
