"""工具基类."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from auto_engineering.errors import ErrorCode


@dataclass
class ToolResult:
    """工具执行结果.

    Attributes:
        success   — 工具是否成功执行
        content   — 工具输出内容
        error     — 错误描述(success=False 时)
        error_code — 错误分类码(P1.4),BaseAgent 据此抛 AEError
    """

    success: bool
    content: str
    error: str | None = None
    error_code: ErrorCode | None = None


class BaseTool(ABC):
    """工具基类. execute() 是 async — BaseAgent 通过 await 调用.

    Attributes:
        project_root — 限制文件操作在此目录内(可选)
    """

    name: str = ""
    description: str = ""
    parameters: ClassVar[dict] = {}
    project_root: Path | None = None

    # 子类可覆盖黑名单(命令)或白名单(path)
    DANGEROUS_PATTERNS: ClassVar[list[str]] = []

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Must be implemented by subclasses."""
        ...

    def _is_path_safe(self, file_path: str) -> tuple[bool, str]:
        """检查 file_path 是否在 project_root 内.

        Symlink 防御 (per engineering-practices §10): macOS 下 /var → /private/var
        /tmp → /private/tmp, 攻击者控制的 file_path 若经 symlink 可绕过 lexical
        解析. 用 os.path.realpath 双侧归一化; 不存在的中间目录回退到 lexical.

        Returns:
            (safe, error_message)
        """
        if self.project_root is None:
            return True, ""

        import os

        try:
            root_real = os.path.realpath(self.project_root)
            # 文件存在 → realpath 双侧 (展 symlink); 不存在 → lexical
            if os.path.exists(file_path):
                target_real = os.path.realpath(file_path)
            else:
                # Path.resolve() 在中间目录不存在时, 仍尽量解析已存在部分
                target_real = str(Path(file_path).resolve())

            # 防御: realpath 后不在 root_real + sep 内
            root_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
            if not (target_real == root_real or target_real.startswith(root_prefix)):
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
