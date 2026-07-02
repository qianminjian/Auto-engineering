#!/usr/bin/env -S .venv/bin/python
"""atdo Runtime Smoke — v5.0 inline (decision #18)

Validates v5.0 phase completion via 7 dynamic runtime dimensions.
Prevents 虚化测试 (artificial tests that pass without exercising real code).

Usage:
    .venv/bin/python scripts/atdo_smoke.py --phase v5.0-11

Exit codes:
    0 - All 7 dimensions PASS
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


def _check_guardrail_3_states() -> DimensionResult:
    """Smoke 5: Guardrail 3 态动作 (v5.0 P0-1: pass / block / retry, drop deprecated).

    通过 pytest tests/test_guardrail.py 验证 3 态 + Chain + 5 内置 Guardrails.
    P0-1 (2026-07-01): 删 drop 态 (YAGNI, CrewAI 仅 2 态), handler 中 drop-as-retry 兼容.
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
                "guardrail_3_states", False,
                f"pytest test_guardrail FAILED (rc={result.returncode})\n"
                f"stdout tail: {result.stdout[-500:]}",
            )

        return DimensionResult(
            "guardrail_3_states", True,
            "test_guardrail.py 3 态契约 全 PASS (P0-1: drop deprecated)",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(
            "guardrail_3_states", False,
            "pytest test_guardrail 超时 (120s)",
        )
    except FileNotFoundError as e:
        return DimensionResult(
            "guardrail_3_states", False,
            f"pytest not found: {e}",
        )
    except Exception as e:
        return DimensionResult(
            "guardrail_3_states", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_cli_doctor() -> DimensionResult:
    """Smoke 6: CLI doctor 7 项检查 (P2-1)."""
    try:
        import json
        import os
        import subprocess

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = env.get("ANTHROPIC_API_KEY", "sk-smoke-test")

        result = subprocess.run(
            [
                "uv", "run", "ae", "doctor",
            ],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
            env=env,
        )
        if result.returncode != 0:
            return DimensionResult(
                "cli_doctor", False,
                f"ae doctor exit code={result.returncode}, expected 0\n"
                f"stdout: {result.stdout[-300:]}",
            )

        check_marks = result.stdout.count("✓")
        if check_marks != 7:
            return DimensionResult(
                "cli_doctor", False,
                f"ae doctor 输出 {check_marks} ✓, expected 7\n"
                f"stdout tail: {result.stdout[-300:]}",
            )

        return DimensionResult(
            "cli_doctor", True,
            f"ae doctor 7/7 ✓ ({check_marks} checks PASS)",
        )
    except subprocess.TimeoutExpired:
        return DimensionResult(
            "cli_doctor", False,
            "ae doctor 超时 (30s)",
        )
    except FileNotFoundError as e:
        return DimensionResult(
            "cli_doctor", False,
            f"uv not found: {e}",
        )
    except Exception as e:
        return DimensionResult(
            "cli_doctor", False,
            f"exception: {type(e).__name__}: {e}",
        )


def _check_plugin_load() -> DimensionResult:
    """Smoke 7: Plugin 加载 — plugin.json + hooks chmod +x (P2-1)."""
    try:
        plugin_json = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        hooks_dir = PROJECT_ROOT / ".claude-plugin" / "hooks"

        if not plugin_json.exists():
            return DimensionResult(
                "plugin_load", False,
                f"plugin.json 不存在: {plugin_json}",
            )
        if not plugin_json.is_file():
            return DimensionResult(
                "plugin_load", False,
                f"plugin.json 不是文件: {plugin_json}",
            )
        try:
            import json
            with open(plugin_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "name" not in data:
                return DimensionResult(
                    "plugin_load", False,
                    f"plugin.json 无效: 缺少 'name' 字段",
                )
        except json.JSONDecodeError as e:
            return DimensionResult(
                "plugin_load", False,
                f"plugin.json JSON 解析失败: {e}",
            )
        except OSError as e:
            return DimensionResult(
                "plugin_load", False,
                f"plugin.json 不可读: {e}",
            )

        if not hooks_dir.exists() or not hooks_dir.is_dir():
            return DimensionResult(
                "plugin_load", False,
                f"hooks 目录不存在: {hooks_dir}",
            )

        import stat
        hook_files = sorted(hooks_dir.glob("*.sh"))
        if not hook_files:
            return DimensionResult(
                "plugin_load", False,
                f"hooks 目录无 .sh 文件: {hooks_dir}",
            )

        non_exec = []
        for hf in hook_files:
            mode = hf.stat().st_mode
            if not (mode & stat.S_IXUSR):
                non_exec.append(hf.name)

        if non_exec:
            return DimensionResult(
                "plugin_load", False,
                f"hooks 缺 +x: {', '.join(non_exec)}",
            )

        return DimensionResult(
            "plugin_load", True,
            f"plugin.json valid + {len(hook_files)} hooks all +x ({', '.join(h.name for h in hook_files)})",
        )
    except Exception as e:
        return DimensionResult(
            "plugin_load", False,
            f"exception: {type(e).__name__}: {e}",
        )


DIMENSIONS = [
    ("init_manifest", _check_init_manifest),
    ("gate_pass", _check_gate_pass),
    ("orchestrator_12_steps", _check_orchestrator_12_steps),
    ("stage_router_t1_t6", _check_stage_router_t1_t6),
    ("guardrail_3_states", _check_guardrail_3_states),
    ("cli_doctor", _check_cli_doctor),
    ("plugin_load", _check_plugin_load),
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
        print(f"[atdo-smoke-v5] phase={args.phase} status=PASS (7/7)")
        return 0
    print(f"[atdo-smoke-v5] phase={args.phase} status=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
