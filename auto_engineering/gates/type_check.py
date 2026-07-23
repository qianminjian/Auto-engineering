"""v2.0 Phase 04 — Gate 2: Type Check (mypy / pyright, v5.0 §IL-AC-02 可配置).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 2.

实现方式:
    - subprocess 调用 `{type_checker} .` (默认 mypy, v5.0 §IL-AC-02 可改 pyright/tsc/go vet/cargo check/bash -n)
    - 若 type_checker 未安装 → skip (passed=True with skip message)
    - 若配置不存在 → skip (passed=True, 提示用户配置)

设计决策:
    - Phase 04 不强制要求配置存在(尊重项目现状)
    - 若超时/异常 → drop (passed=True, 不阻塞 dev-loop)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from auto_engineering.gates._tools import LANGUAGE_TOOLS, detect_project_language
from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command

__all__ = ["TypeCheckGate"]

_logger = logging.getLogger("ae.gates.type_check")

_DEFAULT_TIMEOUT = 120.0
_DEFAULT_TYPE_CHECKER = "mypy"


class TypeCheckGate(Gate):
    """Gate 2: 静态类型检查 (默认 mypy).

    Args:
        type_checker_bin: 类型检查工具名(默认 'mypy', v5.0 §IL-AC-02)
                          可选: mypy / pyright / tsc / go vet / cargo check / bash -n
        timeout: subprocess 超时(秒)
        require_config: 是否必须存在配置(默认 False — 缺失则 skip)
        strict: 是否使用 --strict 模式(默认 False, 仅 mypy 适用)

        类型检查每个 stage 都需通过
    """

    name = "type_check"
    _MANIFEST_TOOL_KEY = "type_checker"
    _TOOL_BIN_KWARG = "type_checker_bin"

    def __init__(
        self,
        type_checker_bin: str | None = None,
        timeout: float | None = None,
        require_config: bool = False,
        strict: bool = False,
    ):
        self.type_checker_bin = type_checker_bin or _DEFAULT_TYPE_CHECKER
        self.timeout = timeout if timeout is not None else Gate._resolve_timeout(_DEFAULT_TIMEOUT)
        self.require_config = require_config
        self.strict = strict

    def _has_type_config(self, project_root: Path, checker: str | None = None) -> bool:
        """检查项目是否有当前 type_checker 的配置文件.

        原仅检测 mypy 配置 (mypy.ini / pyproject.toml [tool.mypy])。
        v5.6 E3 修复: 按 type_checker_bin 检测对应配置。
        """
        checker = checker or self.type_checker_bin

        # tsc → tsconfig.json
        if checker == "tsc":
            return (project_root / "tsconfig.json").exists()

        # pyright → pyrightconfig.json / pyproject.toml [tool.pyright]
        if checker == "pyright":
            if (project_root / "pyrightconfig.json").exists():
                return True
            cfg = project_root / "pyproject.toml"
            if cfg.exists():
                try:
                    return "[tool.pyright]" in cfg.read_text()
                except OSError:
                    return False
            return False

        # go vet → go.mod
        if checker in ("go vet", "go-vet"):
            return (project_root / "go.mod").exists()

        # cargo check → Cargo.toml
        if checker == "cargo check":
            return (project_root / "Cargo.toml").exists()

        # mypy (default) → mypy.ini / setup.cfg / pyproject.toml [tool.mypy]
        candidates = [
            project_root / "mypy.ini",
            project_root / ".mypy.ini",
            project_root / "setup.cfg",
        ]
        for c in candidates:
            if c.exists():
                return True
        cfg = project_root / "pyproject.toml"
        if cfg.exists():
            try:
                if "[tool.mypy]" in cfg.read_text():
                    return True
            except OSError:
                _logger.warning("无法读取 pyproject.toml 检查 mypy 配置")
        return False

    def _resolve_type_check_cmd(self) -> list[str] | None:
        """解析 type_check 命令(若不可用返回 None).

        注意: 'bash -n' 是带参数的命令, 单独传 'bash' 然后在 cmd 中加 '-n'.
        """
        # 'bash -n' 等带 -n 标志的 type_checker 需要特殊处理
        if self.type_checker_bin == "bash -n":
            return ["bash", "-n"]
        if self.type_checker_bin:
            return [self.type_checker_bin]
        if shutil.which(self.type_checker_bin):
            return [self.type_checker_bin]
        return None  # type_checker 未安装

    def run(self, project_root: Path) -> GateVerdict:
        """执行 type check.

        Returns:
            GateVerdict: passed=True 表示无类型错误 / skip;
                     passed=False 表示有类型错误.
        """
        project_root = Path(project_root)
        if verdict := self._validate_project_root(project_root):
            return verdict

        # 自动检测项目语言：非 Python 项目用对应工具（局部变量，不修改 self）
        checker = self.type_checker_bin
        if checker == _DEFAULT_TYPE_CHECKER:
            language = detect_project_language(project_root)
            if language != "python":
                _, checker, _ = LANGUAGE_TOOLS.get(language, LANGUAGE_TOOLS["python"])

        # 检查 type_check 配置
        if not self._has_type_config(project_root, checker):
            if self.require_config:
                return GateVerdict.failed(
                    f"项目未配置 {checker}", gate_name=self.name,
                )
            return GateVerdict.ok(
                f"skip: 项目未配置 {checker},跳过类型检查",
                gate_name=self.name,
            )

        # 解析 type_check 命令
        cmd_base = self._resolve_type_check_cmd()
        if cmd_base is None:
            return GateVerdict.ok(
                f"skip: {checker} 未安装,跳过类型检查",
                gate_name=self.name,
            )

        cmd = [*cmd_base, str(project_root)]
        if self.strict and checker == "mypy":
            cmd.append("--strict")

        result = run_gate_command(cmd, project_root, self.timeout)

        if result.timed_out:
            return GateVerdict.failed(
                f"{checker} 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        if result.not_found:
            return GateVerdict.ok(
                f"skip: {checker} 命令未找到",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return GateVerdict.ok(
                f"{checker} 通过 (0 errors)",
                gate_name=self.name,
            )

        output = result.stdout or result.stderr or ""
        if "error:" in output.lower():
            snippet = output[:1500] + ("..." if len(output) > 1500 else "")
            return GateVerdict.failed(
                f"{checker} 失败 (exit={result.returncode}):\n{snippet}",
                gate_name=self.name,
            )

        return GateVerdict.ok(
            f"{checker} 退出 {result.returncode}, 无类型 error",
            gate_name=self.name,
        )


# v5.5 audit P2-15: 向后兼容别名, v6.0 移除
TypeCheckGate._register_alias("mypy_bin", "type_checker_bin")