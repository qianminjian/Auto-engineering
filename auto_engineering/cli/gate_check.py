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

from auto_engineering.gates.runner import run_gates  # P1-5: moved from this module

if TYPE_CHECKING:
    pass  # reserved for future type-only imports

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
    except (ImportError, ModuleNotFoundError):
        _logger.warning("_all_gate_names fallback to hardcoded list", exc_info=True)
        # 与 registry._build_default_gates 保持同步
        return ("safety", "lint", "type_check", "audit", "contract", "test", "build")


ALL_GATES = _all_gate_names()


def register_gate_check_command(main: click.Group) -> None:
    """向 main Click Group 注册 ae gate-check 子命令."""

    @main.command("gate-check")
    @click.option("--all", "run_all", is_flag=True, default=True, help="跑 7 道 Gate (默认)")
    @click.option("--quick", is_flag=True, default=False, help="只跑 3 道 (safety/lint/type_check)")
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认当前目录)",
    )
    def gate_check(run_all: bool, quick: bool, project_root: str) -> None:
        """跑 Gate 检查, 输出 JSON gate_summary."""
        project_root_path = Path(project_root).resolve() if project_root else Path.cwd()
        names = QUICK_GATES if quick else ALL_GATES
        mode = "quick" if quick else "all"
        result = run_gates(names, project_root_path)
        result["mode"] = mode
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        # 退出码: 0 = 全部 pass/skip, 1 = 存在 fail
        if result["failed"] > 0:
            click.echo(
                f"Gate check ({mode}): {result['failed']} failed, "
                f"{result.get('passed', 0)} passed",
                err=True,
            )
            raise SystemExit(1)
