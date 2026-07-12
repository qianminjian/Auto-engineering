"""CLI gate-check 命令 — 单次跑 Gate 集合, 输出 JSON gate_summary (v5.0 §PE.6).

支持两种模式:
    --all   跑 7 道 Gate (safety/lint/type_check/audit/contract/test/build)
    --quick 跑 3 道 Gate (safety/lint/type_check) — 不依赖项目编译/测试

输出格式 (单行 JSON):
    {
      "project_root": "/path/to/project",
      "mode": "all" | "quick",
      "passed": 5,
      "failed": 1,
      "skipped": 1,
      "gate_summary": {
        "safety":    {"status": "pass", "passed": true,  "message": "..."},
        "lint":      {"status": "fail", "passed": false, "message": "..."},
        "type_check":{"status": "pass", "passed": true,  "message": "..."},
        ...
      }
    }

每 Gate status: "pass" | "fail" | "error"(崩溃, fail-closed) | "skipped"(不适用/无此 Gate)

Exit codes:
    0 = 全部 PASS (或 skipped 不适用)
    1 = 存在 FAIL 或 ERROR (崩溃 gate 计入 failed, fail-closed)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from auto_engineering.gates.base import Gate

_logger = logging.getLogger("ae.cli.gate_check")


# ============================================================
# Gate 集合
# ============================================================

QUICK_GATES = ("safety", "lint", "type_check")


def _all_gate_names() -> tuple[str, ...]:
    """返回全量 Gate 名称 (SSOT: gates/registry.py get_default_gate_names()).

    若 registry 不可用 (import 错误等), 回退到硬编码列表.
    """
    try:
        from auto_engineering.gates.registry import get_default_gate_names

        return tuple(get_default_gate_names())
    except Exception:
        _logger.warning("_all_gate_names fallback to hardcoded list", exc_info=True)
        # 与 registry._build_default_gates 保持同步
        return ("safety", "lint", "type_check", "audit", "contract", "test", "build")


ALL_GATES = _all_gate_names()


def _instantiate_gate(name: str, project_root: Path) -> Gate | None:
    """按名称实例化单个 Gate 对象. 不支持的返回 None (skip)."""
    try:
        from auto_engineering.gates.registry import get_gate_by_name

        gate = get_gate_by_name(name)
        if gate is not None:
            return gate
    except Exception as e:
        _logger.warning("gate '%s' 实例化失败: %s", name, e, exc_info=True)
        return None
    return None


def run_gates(gate_names: tuple[str, ...], project_root: Path) -> dict:
    """跑给定名称列表的 Gate, 返回 JSON-ready dict.

    异常安全: 每个 Gate 单独 try, 不会因一个失败影响其他.
    """
    summary: dict[str, dict] = {}
    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for name in gate_names:
        gate = _instantiate_gate(name, project_root)
        if gate is None:
            summary[name] = {"status": "skipped", "passed": None, "message": "no such gate"}
            skipped_count += 1
            continue
        # 跑 Gate
        try:
            verdict = gate.run(project_root)
        except Exception as e:
            _logger.warning("gate '%s' 执行异常", name, exc_info=True)
            # fail-closed: 崩溃的质量门禁不得静默放行 (区别于"不适用" skipped)
            summary[name] = {"status": "error", "passed": False, "message": f"run error: {e}"}
            failed_count += 1
            continue
        # 解析 verdict
        ok = bool(getattr(verdict, "passed", False))
        message = str(getattr(verdict, "message", "") or "")
        gate_name = getattr(verdict, "gate_name", "") or name
        status = "pass" if ok else "fail"
        summary[name] = {
            "status": status,
            "passed": ok,
            "message": message,
            "gate_name": gate_name,
        }
        if ok:
            passed_count += 1
        else:
            failed_count += 1

    return {
        "project_root": str(project_root),
        "gate_names": list(gate_names),
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "gate_summary": summary,
    }


def register_gate_check_command(main: click.Group) -> None:
    """向 main Click Group 注册 ae gate-check 子命令."""

    @main.command("gate-check")
    @click.option("--all", "run_all", is_flag=True, default=True, help="跑 7 道 Gate (默认)")
    @click.option("--quick", is_flag=True, default=False, help="只跑 3 道 (safety/lint/type_check)")
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    def gate_check(run_all: bool, quick: bool, project_root: str) -> None:
        """跑 Gate 检查, 输出 JSON gate_summary."""
        root = Path(project_root).resolve() if project_root else Path.cwd()
        names = QUICK_GATES if quick else ALL_GATES
        mode = "quick" if quick else "all"
        result = run_gates(names, root)
        result["mode"] = mode
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        # 退出码: 0 = 全部 pass/skip, 1 = 存在 fail
        if result["failed"] > 0:
            raise SystemExit(1)
