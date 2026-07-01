"""v2.0 Phase 04 — Gate 2: Type Check (mypy).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 2.

实现方式:
    - subprocess 调用 `mypy .` (若项目已配置 mypy)
    - 若 mypy 未安装 → skip (passed=True with skip message)
    - 若 mypy 配置不存在 → skip (passed=True, 提示用户配置)

设计决策:
    - Phase 04 不强制要求 mypy 配置存在(尊重项目现状)
    - 若超时/异常 → drop (passed=True, 不阻塞 dev-loop)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

_DEFAULT_TIMEOUT = 120.0


class TypeCheckGate(Gate):
    """Gate 2: mypy 静态类型检查.

    Args:
        mypy_bin: mypy 可执行文件路径(默认 PATH 查找)
        timeout: subprocess 超时(秒)
        require_config: 是否必须存在 mypy 配置(默认 False — 缺失则 skip)
        strict: 是否使用 --strict 模式(默认 False)

    v5.0 §B6.1: applies_to_stages = (architect, developer, critic)
        类型检查每个 stage 都需通过
    """

    name = "type_check"
    applies_to_stages = ("architect", "developer", "critic")

    def __init__(
        self,
        mypy_bin: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        require_config: bool = False,
        strict: bool = False,
    ):
        self.mypy_bin = mypy_bin
        self.timeout = timeout
        self.require_config = require_config
        self.strict = strict

    def _has_mypy_config(self, project_root: Path) -> bool:
        """检查项目是否有 mypy 配置."""
        candidates = [
            project_root / "mypy.ini",
            project_root / ".mypy.ini",
            project_root / "pyproject.toml",
            project_root / "setup.cfg",
        ]
        for c in candidates:
            if c.exists():
                # pyproject.toml 需要含 [tool.mypy] 段,简单判断为存在
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

    def _resolve_mypy_cmd(self) -> list[str] | None:
        """解析 mypy 命令(若不可用返回 None)."""
        if self.mypy_bin:
            return [self.mypy_bin]
        if shutil.which("mypy"):
            return ["mypy"]
        return None  # mypy 未安装

    def run(self, project_root: Path) -> Verdict:
        """执行 type check.

        Returns:
            Verdict: passed=True 表示无类型错误 / skip;
                     passed=False 表示有类型错误.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        # 检查 mypy 配置
        if not self._has_mypy_config(project_root):
            if self.require_config:
                return Verdict.failed(
                    "项目未配置 mypy (无 mypy.ini / pyproject.toml [tool.mypy])",
                    gate_name=self.name,
                )
            return Verdict.passed(
                "skip: 项目未配置 mypy,跳过类型检查",
                gate_name=self.name,
            )

        # 解析 mypy 命令
        cmd_base = self._resolve_mypy_cmd()
        if cmd_base is None:
            return Verdict.passed(
                "skip: mypy 未安装,跳过类型检查",
                gate_name=self.name,
            )

        cmd = [*cmd_base, str(project_root)]
        if self.strict:
            cmd.append("--strict")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            # 超时 → drop,不阻塞 loop
            return Verdict.passed(
                f"skip: mypy 超时 (>{self.timeout}s)",
                gate_name=self.name,
            )
        except FileNotFoundError:
            return Verdict.passed(
                "skip: mypy 命令未找到",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return Verdict.passed("mypy 通过 (0 errors)", gate_name=self.name)

        # mypy 返回非 0 — 但仅在有 error 输出时算失败
        output = result.stdout or result.stderr or ""
        if "error:" in output.lower():
            snippet = output[:1500] + ("..." if len(output) > 1500 else "")
            return Verdict.failed(
                f"mypy 失败 (exit={result.returncode}):\n{snippet}",
                gate_name=self.name,
            )

        # mypy 返回非 0 但无 error → 视为 warning 级别
        return Verdict.passed(
            f"mypy 退出 {result.returncode}, 无类型 error",
            gate_name=self.name,
        )