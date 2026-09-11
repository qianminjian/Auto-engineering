"""Python 项目质量工具声明的有限解析。"""

from __future__ import annotations

import re
from collections.abc import Mapping


def has_python_dev_tool(pyproject: Mapping[str, object], name: str) -> bool:
    """仅把 PEP 735 ``dev`` 组中的工具当作质量命令声明证据。"""

    dependency_groups = pyproject.get("dependency-groups")
    if not isinstance(dependency_groups, Mapping):
        return False
    dev_group = dependency_groups.get("dev")
    if not isinstance(dev_group, list):
        return False
    normalized_name = name.lower()
    for requirement in dev_group:
        if not isinstance(requirement, str):
            continue
        package_name = re.split(
            r"[\s<>=!~\[;]", requirement.strip(), maxsplit=1
        )[0]
        if package_name.lower() == normalized_name:
            return True
    return False


__all__ = ["has_python_dev_tool"]
