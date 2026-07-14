"""工具基类."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from auto_engineering.errors import ErrorCode

__all__ = ["BaseTool", "ToolResult"]

_logger = logging.getLogger("ae.tools.base")


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

    def __init__(self, project_root: Path | None = None, **kwargs: Any) -> None:
        self.project_root = project_root

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Must be implemented by subclasses."""
        ...

    def _is_path_safe(self, file_path: str) -> tuple[bool, str]:
        """检查 file_path 是否在 project_root 内 (fail-CLOSED).

        2026-07-04 修复 (v5.0 深度审计 P1-S-01): 改为 fail-CLOSED 默认行为.
        旧实现 project_root=None 时返回 True (fail-OPEN), 调用方忘传时
        沙箱彻底失效. 现在: project_root=None 时拒绝所有路径, 仅当
        环境变量 ALLOW_NO_SANDBOX=true 设置时旁路 (仅测试场景使用).

        Symlink 防御 (per engineering-practices §10): macOS 下 /var → /private/var
        /tmp → /private/tmp, 攻击者控制的 file_path 若经 symlink 可绕过 lexical
        解析. 用 os.path.realpath 双侧归一化; 不存在的中间目录回退到 lexical.
        """
        import os

        if self.project_root is None:
            if os.environ.get("ALLOW_NO_SANDBOX", "").lower() == "true":
                import warnings
                warnings.warn(
                    f"{type(self).__name__}._is_path_safe called with project_root=None. "
                    "ALLOW_NO_SANDBOX=true bypass active (tests only).",
                    stacklevel=2,
                )
                return True, ""
            return False, (
                f"{type(self).__name__}._is_path_safe called with project_root=None. "
                "Sandbox disabled — call site should pass project_root explicitly. "
                "Set ALLOW_NO_SANDBOX=true to bypass (tests only)."
            )

        try:
            root_real = os.path.realpath(self.project_root)
            # 文件存在 → realpath 双侧 (展 symlink); 不存在 → lexical resolve
            target_real = (
                os.path.realpath(file_path)
                if os.path.exists(file_path)
                else str(Path(file_path).resolve())
            )

            # 防御: realpath 后不在 root_real + sep 内
            root_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
            if not (target_real == root_real or target_real.startswith(root_prefix)):
                return False, f"path outside project_root: {file_path}"
            return True, ""
        except Exception as e:
            _logger.debug("路径安全检查异常: %s (%s)", file_path, e, exc_info=True)
            return False, f"invalid path: {file_path} ({e})"

    def _validate_path(self, file_path: str) -> ToolResult | None:
        """路径白名单校验 + 标准化 (v5.4 审计 P2-9 提取).

        4 个文件工具 (ReadFile/WriteFile/EditFile/SearchCode) 都重复:
            safe, err = self._is_path_safe(file_path)
            if not safe:
                return ToolResult(success=False, content="", error=err)

        Returns:
            ToolResult — 校验失败时 (直接返回给调用方), None — 校验通过.
        """
        if not file_path:
            return ToolResult(success=False, content="", error="empty path rejected")
        safe, err = self._is_path_safe(file_path)
        if not safe:
            return ToolResult(success=False, content="", error=err)
        return None

    @staticmethod
    def _fsync(path: Path) -> None:
        """v5.5 P2-3: fsync 文件确保写入持久化 (防崩溃丢数据)."""
        import os

        fd = -1
        try:
            fd = os.open(str(path), os.O_RDONLY)
            os.fsync(fd)
        except OSError:
            logging.getLogger("ae.tools.base").debug("fsync failed for %s", path, exc_info=True)
        finally:
            if fd >= 0:
                os.close(fd)

    def to_schema(self) -> dict:
        # Strip internal "required" marker from properties — it's non-standard
        # JSON Schema and breaks strict endpoints (DeepSeek Anthropic-compatible).
        clean_props = {
            k: {kk: vv for kk, vv in v.items() if kk != "required"}
            for k, v in self.parameters.items()
        }
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": clean_props,
                "required": [k for k, v in self.parameters.items() if v.get("required", False)],
            },
        }
