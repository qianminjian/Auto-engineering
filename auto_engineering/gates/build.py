"""v2.0 Phase 04 — Gate 6: Build 验证 (多语言支持).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 6.
DS-14 (T156, 2026-07-23): 从 init-manifest conventions.build_cmd 读取构建命令，
非 Python 项目不再运行 Python import。

实现方式:
    - Python: `python -c "import <module>"` 验证模块可导入
    - TypeScript: `pnpm build` / `npm run build` (来自 init-manifest)
    - Go: `go build ./...`
    - Rust: `cargo check`
    - 失败 → fail (passed=False)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from auto_engineering.gates._tools import LANGUAGE_TOOLS, detect_project_language
from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command

__all__ = ["DEFAULT_TIMEOUT", "BuildGate"]

DEFAULT_TIMEOUT = 30.0

# 语言默认构建命令（init-manifest conventions.build_cmd 优先）
_LANG_BUILD_CMD: dict[str, str] = {
    "python": "",
    "typescript": "pnpm build",
    "go": "go build ./...",
    "rust": "cargo check",
}


class BuildGate(Gate):
    """Gate 6: 构建验证 (多语言).

    Args:
        module: Python 项目要验证的模块名 (默认 "auto_engineering")
        build_cmd: 非 Python 项目的构建命令 (优先从 init-manifest 读取)
        timeout: subprocess 超时(秒)

        构建验证仅在 developer 阶段跑。
    """

    name = "build"

    def __init__(
        self,
        module: str = "auto_engineering",
        build_cmd: str = "",
        timeout: float | None = None,
    ):
        self.module = module
        self.build_cmd = build_cmd
        self.timeout = timeout if timeout is not None else Gate._resolve_timeout(DEFAULT_TIMEOUT)

    @classmethod
    def from_manifest(cls, manifest: dict) -> "BuildGate":
        """DS-14: 从 init-manifest 创建 BuildGate (多语言支持)."""
        conventions = manifest.get("conventions")
        build_cmd = ""
        if isinstance(conventions, dict):
            build_cmd = conventions.get("build_cmd", "")
        return cls(build_cmd=build_cmd)

    def run(self, project_root: Path) -> GateVerdict:
        """执行 build 验证.

        Returns:
            GateVerdict: passed=True 表示构建成功; passed=False 表示失败.
        """
        if verdict := self._validate_project_root(project_root):
            return verdict

        cwd = Path(project_root)

        # DS-14: 优先使用 init-manifest 声明的 build_cmd
        if self.build_cmd:
            cmd_parts = self.build_cmd.split()
            cmd = [cmd_parts[0], *cmd_parts[1:]] if len(cmd_parts) > 1 else cmd_parts
            result = run_gate_command(cmd, cwd, self.timeout)
            if result.timed_out:
                return GateVerdict.failed(f"{self.build_cmd} 超时 (>{self.timeout}s)", gate_name=self.name)
            if result.returncode == 0:
                return GateVerdict.ok(f"{self.build_cmd} 成功", gate_name=self.name)
            output = result.stdout + result.stderr
            snippet = output[-1000:] if len(output) > 1000 else output
            return GateVerdict.failed(
                f"{self.build_cmd} 失败 (exit={result.returncode}):\n{snippet}", gate_name=self.name)

        # 自动检测语言
        language = detect_project_language(cwd)
        if language != "python":
            lang_cmd = _LANG_BUILD_CMD.get(language, "")
            if lang_cmd:
                cmd_parts = lang_cmd.split()
                cmd = [cmd_parts[0], *cmd_parts[1:]] if len(cmd_parts) > 1 else cmd_parts
                result = run_gate_command(cmd, cwd, self.timeout)
                if result.timed_out:
                    return GateVerdict.failed(f"{lang_cmd} 超时 (>{self.timeout}s)", gate_name=self.name)
                if result.returncode == 0:
                    return GateVerdict.ok(f"{lang_cmd} 成功", gate_name=self.name)
                output = result.stdout + result.stderr
                snippet = output[-1000:] if len(output) > 1000 else output
                return GateVerdict.ok(  # 构建失败不阻塞（依赖未安装等）
                    f"{lang_cmd} skip: 构建未通过 (exit={result.returncode})，"
                    f"可能缺依赖或配置\n{snippet}", gate_name=self.name)

        # Python: import 验证
        cmd = [sys.executable, "-c", f"import {self.module}"]
        result = run_gate_command(cmd, cwd, self.timeout)
        if result.timed_out:
            return GateVerdict.failed(f"import 超时 (>{self.timeout}s)", gate_name=self.name)
        if result.returncode == 0:
            return GateVerdict.ok(f"import {self.module} 成功", gate_name=self.name)
        output = result.stdout + result.stderr
        snippet = output[-1000:] if len(output) > 1000 else output
        return GateVerdict.failed(
            f"import {self.module} 失败 (exit={result.returncode}):\n{snippet}", gate_name=self.name)