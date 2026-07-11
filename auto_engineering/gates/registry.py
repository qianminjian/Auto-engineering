"""v5.0 §B6.1+§B6.2 — Gate 注册表 + DEFAULT_GATES 默认实例列表.

从 base.py 提取 (v5.4 审计), 消除 gates/base.py ↔ gates/build.py 导入循环.

单向依赖: registry → 各具体 Gate 模块 → base.py (Gate ABC).
base.py 不再引用任何子类, 循环消除.

v5.5 P1-1: LANGUAGE_TOOLS + get_gate_tools_from_manifest 提取到 _tools.py,
消除 registry → lint/test_gate/type_check → registry 懒加载循环.
现在所有模块从 _tools 顶层导入, 无循环.
"""

from __future__ import annotations

from functools import lru_cache

from auto_engineering.gates._tools import LANGUAGE_TOOLS, get_gate_tools_from_manifest
from auto_engineering.gates.audit import AuditGate
from auto_engineering.gates.base import Gate
from auto_engineering.gates.build import BuildGate
from auto_engineering.gates.contract import ContractGate
from auto_engineering.gates.deep_audit import DeepAuditGate
from auto_engineering.gates.lint import LintGate
from auto_engineering.gates.safety import SafetyGate
from auto_engineering.gates.test_gate import TestGate
from auto_engineering.gates.type_check import TypeCheckGate

__all__ = [
    "LANGUAGE_TOOLS",
    "build_gates_from_manifest",
    "get_default_gate_names",
    "get_default_gates",
    "get_gate_by_name",
    "get_gate_tools_from_manifest",
    "reset_default_gates_cache",
]

def _build_default_gates(manifest: dict | None = None) -> list[Gate]:
    """构造 7 道 Gate 的默认实例列表 (safety/lint/type_check/audit/contract/test/build).

    v5.4 Q1: TDDGate + StageTransitionGate 从 DEFAULT_GATES 移除.
    它们实现 check(stage, state, project_root) 而非 run(project_root),
    本质是 Guardrail 检查不是 Gate 质量检查.

    v5.0 IL-AC-02 扩展:
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


def get_gate_by_name(name: str) -> Gate | None:
    """按名称返回 Gate 实例 (SSOT 工厂, 供 CLI gate_check 使用)."""
    mapping: dict[str, type[Gate]] = {
        "safety": SafetyGate,
        "lint": LintGate,
        "type_check": TypeCheckGate,
        "audit": AuditGate,
        "contract": ContractGate,
        "test": TestGate,
        "build": BuildGate,
        "deep_audit": DeepAuditGate,
    }
    gate_cls = mapping.get(name)
    if gate_cls is None:
        return None
    if gate_cls is SafetyGate:
        return SafetyGate(use_gitleaks=False)
    return gate_cls()


def build_gates_from_manifest(manifest: dict) -> list[Gate]:
    """v5.0 §IL-AC-02: 从 init-manifest.json 构造完整 Gate 列表.

    外部 API — 由 init_contract flow 调用, 将 init-manifest.json 中的
    conventions 映射为具体 Gate 实例 (linter/type_checker/test_runner).
    """
    return _build_default_gates(manifest=manifest)


def reset_default_gates_cache() -> None:
    """重置 DEFAULT_GATES 缓存, 供测试使用 (兼容包装, 委托 lru_cache)."""
    get_default_gates.cache_clear()


@lru_cache(maxsize=1)
def get_default_gates() -> list[Gate]:
    """惰性构造默认 Gate 列表 (lru_cache 避免 import 时副作用)."""
    return _build_default_gates()


def get_default_gate_names() -> list[str]:
    """返回默认 Gate 名称列表 (SSOT, 从 Gate.name 推导)."""
    return [g.name for g in get_default_gates()]


# v5.4 审计 P1-11: 惰性构造 DEFAULT_GATES 避免 import 时副作用.
# 模块 __getattr__ 在首次访问时触发 get_default_gates().
def __getattr__(name: str):
    if name == "DEFAULT_GATES":
        return get_default_gates()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
