"""CLI doctor 命令 — 环境预检 (v5.0 §PE.6).

检查项 (多行 ✓/✗ 输出, IL-AC-01 init-manifest 集成):
    1. Python ≥ 3.12
    2. uv ≥ 0.5 (包管理工具)
    3. git ≥ 2.40
    4. sqlite3 ≥ 3.42 (用于 SQLiteCheckpointStore)
    5. N/A (SDK 自动从 env 读 key, Plugin 模式无需设置)
    6. .ae-state/ 可读写 (项目状态目录)
    7. init-manifest.json 存在 (IL-AC-01)

Exit codes:
    0 = 全部 ✓
    1 = 存在 ✗
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import click

from auto_engineering.utils import parse_version as _parse_version

# 最低版本要求
PYTHON_MIN = (3, 12)
UV_MIN = (0, 5, 0)
GIT_MIN = (2, 40, 0)
SQLITE_MIN = (3, 42, 0)


def _check_python() -> tuple[bool, str]:
    """检查 Python 版本 ≥ 3.12."""
    v = sys.version_info
    current = (v.major, v.minor)
    ok = current >= PYTHON_MIN
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if ok:
        return True, f"Python {version_str}     (required: >={PYTHON_MIN[0]}.{PYTHON_MIN[1]})"
    return False, f"Python {version_str}     (required: >={PYTHON_MIN[0]}.{PYTHON_MIN[1]}) — 当前版本过低"


def _check_uv() -> tuple[bool, str]:
    """检查 uv ≥ 0.5 (包管理工具)."""
    uv_path = shutil.which("uv")
    if not uv_path:
        return False, "uv 未安装 (required: >=0.5.0) — 请运行 `brew install uv` 或 `pip install uv`"
    try:
        import subprocess

        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
        # 输出形如: "uv 0.11.12 (Homebrew ...)"
        line = result.stdout.strip()
        # 提取版本号
        parts = line.split()
        ver_str = parts[1] if len(parts) >= 2 else "0.0.0"
        current = _parse_version(ver_str)
        if current >= UV_MIN:
            return True, f"uv {ver_str}          (required: >={UV_MIN[0]}.{UV_MIN[1]})"
        return False, f"uv {ver_str}          (required: >={UV_MIN[0]}.{UV_MIN[1]}) — 版本过低"
    except Exception as e:
        return False, f"uv 检查失败: {e}"


def _check_git() -> tuple[bool, str]:
    """检查 git ≥ 2.40."""
    git_path = shutil.which("git")
    if not git_path:
        return False, "git 未安装 (required: >=2.40)"
    try:
        import subprocess

        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        # "git version 2.50.1 (Apple Git-155)"
        line = result.stdout.strip()
        # 找第一个看起来像版本号的 token
        ver_str = "0.0.0"
        for token in line.split():
            if token and token[0].isdigit():
                ver_str = token
                break
        current = _parse_version(ver_str)
        if current >= GIT_MIN:
            return True, f"git {ver_str}        (required: >={GIT_MIN[0]}.{GIT_MIN[1]})"
        return False, f"git {ver_str}        (required: >={GIT_MIN[0]}.{GIT_MIN[1]}) — 版本过低"
    except Exception as e:
        return False, f"git 检查失败: {e}"


def _check_sqlite3() -> tuple[bool, str]:
    """检查 sqlite3 ≥ 3.42 (Python 内置)."""
    ver_str = sqlite3.sqlite_version
    current = _parse_version(ver_str)
    if current >= SQLITE_MIN:
        return True, f"sqlite3 {ver_str}    (required: >={SQLITE_MIN[0]}.{SQLITE_MIN[1]})"
    return False, f"sqlite3 {ver_str}    (required: >={SQLITE_MIN[0]}.{SQLITE_MIN[1]}) — 版本过低"


def _check_api_key() -> tuple[bool, str]:
    """检查 LLM 凭据 (ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN).

    2026-07-04 修复 (prismscan 真实 bug): 用 4 级 fallback detect_plugin_mode
    而非 2 级, 支持 CLAUDE_CODE_ENTRYPOINT + ANTHROPIC_AUTH_TOKEN (prismscan 实际 env).
    Plugin mode 用户零配置, 由 Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN.
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode, has_llm_credentials
    if detect_plugin_mode():
        return True, "LLM 凭据 (Plugin mode 零配置, Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN)"
    if has_llm_credentials():
        return True, "LLM 凭据已设置 (ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN)"
    return False, "LLM 凭据未设置 — 请 export ANTHROPIC_API_KEY=sk-... 或在 .env 中设置"


def _check_ae_state(project_root: Path) -> tuple[bool, str]:
    """检查 .ae-state/ 可读写 (诊断命令, 不自动创建目录)."""
    ae_state = project_root / ".ae-state"
    if not ae_state.exists():
        return False, ".ae-state/ 目录不存在 — 运行 ae dev-loop 初始化项目"
    # 测读写
    test_file = ae_state / ".doctor_write_test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
        return True, ".ae-state/         可读写"
    except (PermissionError, OSError) as e:
        return False, f".ae-state/ 不可写: {e}"


def _check_plugin_mode() -> tuple[bool, str]:
    """检查 Plugin mode 是否启用 (Bug 4 修复, 2026-07-04).

    2026-07-04 深度设计 (用户洞察): Plugin mode 用户**零配置**原则.
    Plugin 在 Claude Code agent 内运行时, ANTHROPIC_AUTH_TOKEN 由 Claude Code
    通过 OAuth 自动注入, 用户不需要自己 export ANTHROPIC_API_KEY.
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

    in_plugin, signal = detect_plugin_mode_detail()
    if in_plugin:
        # Plugin mode: 用户零配置, ANTHROPIC_AUTH_TOKEN 由 Claude Code OAuth 注入
        return True, (
            f"Plugin mode 已启用 (via {signal}) — 用户零配置, "
            f"ANTHROPIC_AUTH_TOKEN 由 Claude Code OAuth 自动注入"
        )
    # CLI 调试模式: 需要用户手动 export (独立跑 ae 才需要)
    return True, (
        "CLI 调试模式 (独立跑 ae) — 需手动 export ANTHROPIC_API_KEY. "
        "建议在 Claude Code agent 内运行 (Plugin 模式, 零配置)"
    )


def _check_init_manifest(project_root: Path) -> tuple[bool, str]:
    """检查 init-manifest.json (IL-AC-01~05, v5.0 §IL.4).

    校验流程:
        1. 文件不存在 → ✗ + 提示运行 Init (IL-AC-01)
        2. 调 init_contract.load_init_manifest 读取
        3. 调 init_contract.validate_init_manifest 校验
            - schema_version < 1.0 → ✗ (IL-AC-04)
            - schema_version > 9.9 → WARN (forward-compat)
            - 必需字段缺失 → ✗ (列字段名)
            - language/project_type 不在 enum → ✗ (列支持值)
            - 未知字段 → WARN (IL-AC-03, 静默忽略)
        4. 任一 ✗ → 整体 ✗, 拼接 messages
    """
    # 惰性 import 避免循环 (init_contract → 不依赖 cli, 但保险起见)
    from auto_engineering.loop.init_contract import (
        load_init_manifest,
        validate_init_manifest,
    )

    manifest = project_root / ".ae-state" / "init-manifest.json"
    # IL-AC-01: 文件缺失
    if not manifest.exists():
        return False, (
            "init-manifest.json 不存在 — 未找到 .ae-state/init-manifest.json, "
            "请先运行 Init Engineering 项目初始化"
        )
    # 调 init_contract 读取 (load 失败 → ✗)
    data = load_init_manifest(project_root)
    if data is None:
        return False, f"init-manifest.json 读取/解析失败: {manifest}"
    # 调 init_contract 校验
    result = validate_init_manifest(data)
    if not result.ok:
        # 拼接 errors
        joined = "; ".join(result.errors)
        return False, f"init-manifest.json 校验失败: {joined}"
    # 通过, 拼接 schema_version + warnings
    schema_version = data.get("schema_version", "?")
    warn_str = " [WARN: " + "; ".join(result.warnings) + "]" if result.warnings else ""
    return True, f"init-manifest.json 存在 (schema_version {schema_version}){warn_str}"


def _check_pr_backend() -> tuple[bool, str]:
    """检查 PR 后端可用性 (B13.9 #8, 非致命).

    PR 创建仅在 loop `done` 时需要, 故此项恒 ok=True (advisory):
    有 gh/glab → 列出; 都无 → 提示 done 时手动创建 PR (不阻断预检).
    """
    from auto_engineering.tools.pr_backend import available_backends

    backends = available_backends()
    if backends:
        return True, f"PR 后端可用: {', '.join(backends)} (gh/glab, B13.9)"
    return True, (
        "PR 后端: 无 (gh/glab 均未安装) — loop done 时将提示手动创建 PR"
    )


def run_doctor_checks(project_root: Path) -> tuple[int, list[tuple[bool, str]]]:
    """执行全部 doctor 检查, 返回 (exit_code, [(ok, line), ...])."""
    results: list[tuple[bool, str]] = []
    results.append(_check_python())
    results.append(_check_uv())
    results.append(_check_git())
    results.append(_check_sqlite3())
    results.append(_check_plugin_mode())
    results.append(_check_api_key())
    results.append(_check_ae_state(project_root))
    results.append(_check_init_manifest(project_root))
    results.append(_check_pr_backend())
    failed = sum(1 for ok, _ in results if not ok)
    return (1 if failed > 0 else 0), results


def register_doctor_command(main: click.Group) -> None:
    """向 main Click Group 注册 ae doctor 子命令."""

    @main.command()
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    def doctor(project_root: str) -> None:
        """环境预检 — Python/uv/git/sqlite3/.ae-state + init-manifest (IL-AC-01)."""
        root = Path(project_root).resolve() if project_root else Path.cwd()
        exit_code, results = run_doctor_checks(root)
        for ok, line in results:
            mark = "✓" if ok else "✗"
            click.echo(f"{mark} {line}")
        if exit_code != 0:
            raise SystemExit(exit_code)
