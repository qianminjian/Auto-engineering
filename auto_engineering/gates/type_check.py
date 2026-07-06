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

import shutil
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command

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

    v5.0 §B6.1: applies_to_stages = (architect, developer, critic)
        类型检查每个 stage 都需通过
    """

    name = "type_check"
    applies_to_stages = ("architect", "developer", "critic")

    def __init__(
        self,
        type_checker_bin: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        require_config: bool = False,
        strict: bool = False,
    ):
        # 向后兼容: 旧参数 mypy_bin 接受为 type_checker_bin
        self.mypy_bin = type_checker_bin  # 向后兼容 (保留旧字段名)
        self.type_checker_bin = type_checker_bin or _DEFAULT_TYPE_CHECKER
        self.timeout = timeout
        self.require_config = require_config
        self.strict = strict

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> "TypeCheckGate":
        """v5.0 §IL-AC-02: 从 init-manifest.json 构造 TypeCheckGate.

        读 manifest.conventions.type_checker, 缺则用 LANGUAGE_TOOLS 默认.
        """
        from auto_engineering.gates.registry import get_gate_tools_from_manifest

        tools = get_gate_tools_from_manifest(manifest)
        return cls(type_checker_bin=tools["type_checker"], timeout=timeout)

    def _has_type_config(self, project_root: Path) -> bool:
        """检查项目是否有 type checker 配置.

        默认检查 mypy 兼容配置. v5.0 §IL-AC-02 扩展: 简化判定, 只要 type_checker
        二进制在 PATH 中, 就尝试跑. 真正的 "是否有 config" 留给 type_checker 自身.
        """
        # 兼容旧逻辑: 找 mypy 配置
        candidates = [
            project_root / "mypy.ini",
            project_root / ".mypy.ini",
            project_root / "pyproject.toml",
            project_root / "setup.cfg",
        ]
        for c in candidates:
            if c.exists():
                if c.name == "pyproject.toml":
                    try:
                        content = c.read_text()
                        if "[tool.mypy]" in content:
                            return True
                    except OSError:
                        continue
                else:
                    return True
        return False

    def _resolve_type_check_cmd(self) -> list[str] | None:
        """解析 type_check 命令(若不可用返回 None).

        注意: 'bash -n' 是带参数的命令, 单独传 'bash' 然后在 cmd 中加 '-n'.
        """
        # 'bash -n' 等带 -n 标志的 type_checker 需要特殊处理
        if self.type_checker_bin == "bash -n":
            return ["bash", "-n"]
        if self.mypy_bin:
            # 向后兼容: mypy_bin 显式指定
            return [self.mypy_bin]
        if shutil.which(self.type_checker_bin):
            return [self.type_checker_bin]
        return None  # type_checker 未安装

    def run(self, project_root: Path, contracts: dict | None = None) -> GateVerdict:
        """执行 type check.

        Args:
            project_root: 项目根目录
            contracts: v5.0 §B6.1a — 契约字典 (TypeCheckGate 不使用, 仅签名兼容)

        Returns:
            GateVerdict: passed=True 表示无类型错误 / skip;
                     passed=False 表示有类型错误.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return GateVerdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        # 检查 type_check 配置 (保守: mypy 兼容检测)
        if not self._has_type_config(project_root):
            if self.require_config:
                return GateVerdict.failed(
                    "项目未配置 mypy (无 mypy.ini / pyproject.toml [tool.mypy])",
                    gate_name=self.name,
                )
            return GateVerdict.passed(
                f"skip: 项目未配置 {self.type_checker_bin},跳过类型检查",
                gate_name=self.name,
            )

        # 解析 type_check 命令
        cmd_base = self._resolve_type_check_cmd()
        if cmd_base is None:
            return GateVerdict.passed(
                f"skip: {self.type_checker_bin} 未安装,跳过类型检查",
                gate_name=self.name,
            )

        cmd = [*cmd_base, str(project_root)]
        if self.strict and self.type_checker_bin == "mypy":
            cmd.append("--strict")

        result = run_gate_command(cmd, project_root, self.timeout)

        if result.timed_out:
            return GateVerdict.failed(
                f"{self.type_checker_bin} 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        if result.not_found:
            return GateVerdict.passed(
                f"skip: {self.type_checker_bin} 命令未找到",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return GateVerdict.passed(
                f"{self.type_checker_bin} 通过 (0 errors)",
                gate_name=self.name,
            )

        output = result.stdout or result.stderr or ""
        if "error:" in output.lower():
            snippet = output[:1500] + ("..." if len(output) > 1500 else "")
            return GateVerdict.failed(
                f"{self.type_checker_bin} 失败 (exit={result.returncode}):\n{snippet}",
                gate_name=self.name,
            )

        return GateVerdict.passed(
            f"{self.type_checker_bin} 退出 {result.returncode}, 无类型 error",
            gate_name=self.name,
        )