"""init 默认 exclude 回调 + spec 解析工具.

来源：Copier _main.py:753 match_exclude(self) -> Callable[[Path], bool].

设计：
- default_match_exclude: 默认排除 .git/ / __pycache__/ / .venv/ / node_modules/
  以及 .DS_Store / .env / *.pyc.
  注意: 保留 .gitignore / .editorconfig 等 dotfile 配置 (与 Copier 一致).
- parse_exclude_callback: 解析 "module:function" 格式 spec, 返回可调用对象.
  解析失败时分别抛 ImportError / AttributeError / ValueError, 调用方可分别处理.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

# 默认排除目录名（来源: Copier _template.py:DEFAULT_EXCLUDE 增强版）
_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
    }
)

# 默认排除文件名（精确匹配, 适用于根级或任何位置）
# 注意: 故意不包含 .gitignore / .editorconfig 等配置 dotfile
_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {
        ".DS_Store",
        ".env",
    }
)

# 默认排除后缀
_EXCLUDED_SUFFIXES: tuple[str, ...] = (".pyc",)


def default_match_exclude(path: Path) -> bool:
    """默认 exclude 回调 — 排除常见构建/版本控制/缓存产物.

    规则（按顺序短路求值）:
    1. 路径中任一段在 _EXCLUDED_DIRS (.git, __pycache__, .venv, node_modules) → True
    2. 路径中任一段在 _EXCLUDED_NAMES (.DS_Store, .env) → True
    3. 文件名后缀在 _EXCLUDED_SUFFIXES (.pyc) → True
    4. 其他 → False (包括 .gitignore / .editorconfig 等 dotfile)

    Args:
        path: 模板中的相对路径 (Jinja2 渲染后)

    Returns:
        True 表示应排除该路径.
    """
    parts = path.parts
    if any(p in _EXCLUDED_DIRS for p in parts):
        return True
    if any(p in _EXCLUDED_NAMES for p in parts):
        return True
    if path.suffix in _EXCLUDED_SUFFIXES:
        return True
    return False


def parse_exclude_callback(spec: str) -> Callable[[Path], bool]:
    """解析 "module:function" 格式 spec, 返回可调用对象.

    Examples:
        'auto_engineering.init._shared.exclude:default_match_exclude'
        'my_project.custom_exclude:my_match'

    Args:
        spec: "module.path:function_name" 格式字符串

    Returns:
        已解析的回调函数 (Callable[[Path], bool]).

    Raises:
        ValueError: spec 不含 ":" 分隔符
        ImportError: module_path 无法导入
        AttributeError: module 中无 func_name
    """
    if ":" not in spec:
        raise ValueError(
            f"无效 exclude_callback spec: {spec!r} (需 'module:function' 格式)"
        )
    module_path, func_name = spec.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)
