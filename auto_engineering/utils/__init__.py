"""Auto-Engineering utilities.

跨模块共享工具函数 (plugin mode 检测, env helpers, etc.).

2026-07-04 新增: plugin_mode 检测共用模块 (Bug 4 修复).
2026-07-07 新增: parse_version 共用函数 (审计 P1-11 _parse_version 重复).
"""


__all__ = ["parse_version"]


def parse_version(version_str: str) -> tuple[int, ...]:
    """解析 'X.Y.Z' 形式版本号 → tuple[int, ...]. 解析失败返回 (0,)."""
    parts: list[int] = []
    for chunk in str(version_str).strip().split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts) if parts else (0,)