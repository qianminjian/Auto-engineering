"""工具基类."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolResult:
    """工具执行结果."""

    success: bool
    content: str
    error: str | None = None


class BaseTool(ABC):
    """工具基类. execute() 是 async — BaseAgent 通过 await 调用.

    Attributes:
        project_root — 限制文件操作在此目录内(可选)
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}
    project_root: Path | None = None

    # 子类可覆盖黑名单(命令)或白名单(path)
    DANGEROUS_PATTERNS: list[str] = []

    def _is_path_safe(self, file_path: str) -> tuple[bool, str]:
        """检查 file_path 是否在 project_root 内.

        Returns:
            (safe, error_message)
        """
        if self.project_root is None:
            return True, ""

        try:
            target = Path(file_path).resolve()
            root = self.project_root.resolve()
            # path traversal 检测:realpath 后不在 root 内
            if not target.is_relative_to(root):
                return False, f"path outside project_root: {file_path}"
            return True, ""
        except Exception as e:
            return False, f"invalid path: {file_path} ({e})"

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.parameters.keys()),
            },
        }
