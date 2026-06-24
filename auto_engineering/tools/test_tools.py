"""测试工具 — Phase 0.2 真接.

1 个工具: RunTestsTool — 按测试 runner 跑测试.
支持: pytest / npm test / (可扩展)
"""

from __future__ import annotations

import subprocess
import sys

from .base import BaseTool, ToolResult

_RUNNER_CMDS = {
    # 用 sys.executable -m pytest 避免 PATH 找不到 pytest
    "pytest": [sys.executable, "-m", "pytest", "-x", "--tb=short"],
    "npm": ["npm", "test"],
    "pnpm": ["pnpm", "test"],
    "yarn": ["yarn", "test"],
    "uv": [sys.executable, "-m", "pytest", "-x", "--tb=short"],
}


class RunTestsTool(BaseTool):
    """Run project tests with appropriate test runner."""

    name = "run_tests"
    description = (
        "Run project tests. Detects runner (pytest/npm/pnpm/yarn/uv) or uses runner parameter."
    )
    parameters = {
        "scope": {"type": "string", "description": "Test scope: all/unit/integration/coverage"},
        "runner": {"type": "string", "description": "Force runner (pytest/npm/pnpm/yarn/uv)"},
        "cwd": {"type": "string", "description": "Working directory (optional)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        runner = kwargs.get("runner")
        timeout = int(kwargs.get("timeout", 300))
        try:
            if not runner:
                runner = self._detect_runner(cwd)
            cmd = _RUNNER_CMDS.get(runner)
            if not cmd:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Unknown runner '{runner}'. Supported: {list(_RUNNER_CMDS)}",
                )
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (result.stdout or "") + (result.stderr or "")
            tail = "\n".join(output.splitlines()[-30:])  # 只显示最后 30 行
            return ToolResult(
                success=(result.returncode == 0),
                content=f"=== {runner} ===\n{tail}",
                error=None if result.returncode == 0 else f"exit code {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                content="",
                error=f"Tests timed out after {timeout}s",
            )
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))

    @staticmethod
    def _detect_runner(cwd: str | None) -> str:
        """Detect test runner from project files."""
        from pathlib import Path

        root = Path(cwd) if cwd else Path(".")
        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
            return "pytest"
        if (root / "uv.lock").exists():
            return "uv"
        if (root / "package.json").exists():
            return "npm"
        return "pytest"  # fallback
