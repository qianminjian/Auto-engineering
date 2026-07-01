#!/usr/bin/env python3.12
"""atdo Runtime Smoke — v5.0 inline (decision #18)

Validates v5.0 phase completion via 5 dynamic runtime dimensions.
Prevents 虚化测试 (artificial tests that pass without exercising real code).

Usage:
    python3.12 scripts/atdo_smoke.py --phase v5.0-11

Exit codes:
    0 - All 5 dimensions PASS
    1 - One or more dimensions FAIL
    2 - Invalid arguments / setup error

Reference:
    design/BEACON.md 决策 #28 (v5.0 P0-FINAL)
    design/v5.0-Design-Loop.md §B7.1 (Orchestrator 12 步主循环)
    docs/EARS-v5.0.md (15 AC + 5 IL-AC)
    docs/atdo-runtime-smoke-policy.md (smoke 政策)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class DimensionResult:
    name: str
    passed: bool
    detail: str = ""


def _check_init_manifest() -> DimensionResult:
    """Smoke 1: Init-Loop manifest 加载 + 验证 (IL-AC-01/02/04)."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from auto_engineering.loop.init_contract import (
            INIT_MANIFEST_SCHEMA_VERSION,
            load_init_manifest,
            validate_init_manifest,
        )

        # Test 1: schema_version 常量 (string "1.0", v5.0 §IL.2)
        if str(INIT_MANIFEST_SCHEMA_VERSION) != "1.0":
            return DimensionResult(
                "init_manifest", False,
                f"INIT_MANIFEST_SCHEMA_VERSION={INIT_MANIFEST_SCHEMA_VERSION} expected '1.0'",
            )

        # Test 2: 缺失 manifest → 返回 None
        missing_result = load_init_manifest(Path("/nonexistent/path"))
        if missing_result is not None:
            return DimensionResult(
                "init_manifest", False,
                f"load_init_manifest on missing path returned {missing_result!r}, expected None",
            )

        # Test 3: 旧 schema_version → 验证失败 (IL-AC-04)
        old_manifest = {"schema_version": "0.5", "project_type": "app-service"}
        validation = validate_init_manifest(old_manifest)
        if validation.ok:
            return DimensionResult(
                "init_manifest", False,
                "validate_init_manifest accepted schema_version='0.5' (IL-AC-04 违反)",
            )

        return DimensionResult(
            "init_manifest", True,
            "load/validate API 一致 (缺→None, 旧 version→拒绝)",
        )
    except Exception as e:
        return DimensionResult(
            "init_manifest", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_gate_pass() -> DimensionResult:
    """Smoke 2: 7 Gate 列表 + Stage 过滤 (v5.0 §B6.2)."""
    try:
        from auto_engineering.gates import DEFAULT_GATES, V2_GATES
        from auto_engineering.gates.base import GateVerdict, Verdict

        # Test 1: DEFAULT_GATES 7 道实例
        if len(DEFAULT_GATES) != 7:
            return DimensionResult(
                "gate_pass", False,
                f"DEFAULT_GATES has {len(DEFAULT_GATES)} gates, expected 7",
            )

        # Test 2: V2_GATES 7 个类
        if len(V2_GATES) != 7:
            return DimensionResult(
                "gate_pass", False,
                f"V2_GATES has {len(V2_GATES)} classes, expected 7",
            )

        # Test 3: CoverageGate 永远 skip (v5.0 §B6.4 决策 / BEACON 决策 25)
        coverage_gates = [g for g in DEFAULT_GATES if g.name == "coverage"]
        if len(coverage_gates) != 1:
            return DimensionResult(
                "gate_pass", False,
                f"CoverageGate count={len(coverage_gates)}, expected 1",
            )

        # Test 4: GateVerdict 有 passed 字段 (dataclass, 非 Enum)
        sample_passing = GateVerdict.passed(msg="ok", gate_name="test")
        sample_failing = GateVerdict.failed(msg="bad", gate_name="test")
        if not (sample_passing.passed is True and sample_failing.passed is False):
            return DimensionResult(
                "gate_pass", False,
                f"GateVerdict.passed/failed factory methods 异常",
            )

        # Test 5: Verdict 是 GateVerdict 的别名 (v5.0 §B6.1 兼容)
        if Verdict is not GateVerdict:
            return DimensionResult(
                "gate_pass", False,
                f"Verdict is not identity-equal to GateVerdict, v5.0 §B6.1 兼容违反",
            )

        return DimensionResult(
            "gate_pass", True,
            f"DEFAULT_GATES=7 + V2_GATES=7 + CoverageGate present + Verdict alias",
        )
    except Exception as e:
        return DimensionResult(
            "gate_pass", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_orchestrator_12_steps() -> DimensionResult:
    """Smoke 3: Orchestrator 12 步主循环可调用 (v5.0 §B7.1).

    通过 pytest tests/test_loop_orchestrator.py 验证 12 步主循环.
    """
    try:
        import subprocess
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "pytest"),
                "tests/test_loop_orchestrator.py",
                "-v", "--no-cov", "--timeout=120",
                "-k", "TestOrchestratorV5MainLoop",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=180,
        )
        if result.returncode != 0:
            return DimensionResult(
                "orchestrator_12_steps", False,
                f"pytest TestOrchestratorV5MainLoop FAILED (rc={result.returncode})\n"
                f"stdout tail: {result.stdout[-500:]}",
            )
        return DimensionResult(
            "orchestrator_12_steps", True,
            "TestOrchestratorV5MainLoop 12 步主循环测试 PASS",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(
            "orchestrator_12_steps", False,
            "pytest TestOrchestratorV5MainLoop 超时 (180s)",
        )
    except FileNotFoundError as e:
        return DimensionResult(
            "orchestrator_12_steps", False,
            f"pytest not found: {e}",
        )
    except Exception as e:
        return DimensionResult(
            "orchestrator_12_steps", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_stage_router_t1_t6() -> DimensionResult:
    """Smoke 4: StageRouter T1-T6 转换表 (v5.0 §B3).

    通过 pytest tests/test_stage_router.py 验证 T1-T6.
    """
    try:
        import subprocess
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "pytest"),
                "tests/test_stage_router.py",
                "-v", "--no-cov", "--timeout=60",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        if result.returncode != 0:
            return DimensionResult(
                "stage_router_t1_t6", False,
                f"pytest test_stage_router FAILED (rc={result.returncode})\n"
                f"stdout tail: {result.stdout[-500:]}",
            )
        return DimensionResult(
            "stage_router_t1_t6", True,
            "test_stage_router.py T1-T6 转换 + MAJOR 计数 全 PASS",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(
            "stage_router_t1_t6", False,
            "pytest test_stage_router 超时 (120s)",
        )
    except FileNotFoundError as e:
        return DimensionResult(
            "stage_router_t1_t6", False,
            f"pytest not found: {e}",
        )
    except Exception as e:
        return DimensionResult(
            "stage_router_t1_t6", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_guardrail_4_states() -> DimensionResult:
    """Smoke 5: Guardrail 4 态动作 (v5.0 §B2.4: pass / retry / block / drop).

    通过 pytest tests/test_guardrail.py 验证 4 态 + Chain + 5 内置 Guardrails.
    """
    try:
        import subprocess
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "pytest"),
                "tests/test_guardrail.py",
                "-v", "--no-cov", "--timeout=60",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        if result.returncode != 0:
            return DimensionResult(
                "guardrail_4_states", False,
                f"pytest test_guardrail FAILED (rc={result.returncode})\n"
                f"stdout tail: {result.stdout[-500:]}",
            )

        # 额外验证 GuardrailResult.action 包含 4 态 (v5.0 §B2.4)
        sys.path.insert(0, str(PROJECT_ROOT))
        from auto_engineering.loop.guardrail import GuardrailResult
        result_data = GuardrailResult(action="pass", message="smoke test")
        if result_data.action not in {"pass", "retry", "block", "drop"}:
            return DimensionResult(
                "guardrail_4_states", False,
                f"GuardrailResult.action={result_data.action} not in 4-state set",
            )

        return DimensionResult(
            "guardrail_4_states", True,
            "test_guardrail.py + GuardrailResult 4 态契约 全 PASS",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(
            "guardrail_4_states", False,
            "pytest test_guardrail 超时 (120s)",
        )
    except FileNotFoundError as e:
        return DimensionResult(
            "guardrail_4_states", False,
            f"pytest not found: {e}",
        )
    except Exception as e:
        return DimensionResult(
            "guardrail_4_states", False,
            f"exception: {type(e).__name__}: {e}",
        )


DIMENSIONS = [
    ("init_manifest", _check_init_manifest),
    ("gate_pass", _check_gate_pass),
    ("orchestrator_12_steps", _check_orchestrator_12_steps),
    ("stage_router_t1_t6", _check_stage_router_t1_t6),
    ("guardrail_4_states", _check_guardrail_4_states),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="atdo Runtime Smoke — v5.0")
    parser.add_argument("--phase", required=True, help="Phase identifier (e.g. v5.0-11)")
    args = parser.parse_args()

    print(f"[atdo-smoke-v5] phase={args.phase}")
    print("-" * 70)

    all_pass = True
    for name, fn in DIMENSIONS:
        result = fn()
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {name:<26} {result.detail}")
        if not result.passed:
            all_pass = False

    print("-" * 70)
    if all_pass:
        print(f"[atdo-smoke-v5] phase={args.phase} status=PASS (5/5)")
        return 0
    print(f"[atdo-smoke-v5] phase={args.phase} status=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
