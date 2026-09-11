"""Python PEP 517 包装前置校验。

该模块只做确定性静态检查。实际 ``uv build`` 仍由 ProjectProfile 的
Setup Gate 执行，避免把运行时副作用塞进 Provider。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

PYTHON_PACKAGING_GAP = "python_packaging"
HATCHLING_SDIST_EXCLUDE_EXAMPLE = (
    'exclude = ["/.ae-state", "/.ae-runtime", "/.venv", "/dist", '
    '"/build", "/_scratch", "/**/__pycache__"]'
)
_REQUIRED_SDIST_EXCLUDES = frozenset({
    "/.ae-state",
    "/.ae-runtime",
    "/.venv",
    "/dist",
    "/build",
    "/_scratch",
    "/**/__pycache__",
})


def _is_python_package(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(candidate.is_file() for candidate in path.rglob("__init__.py"))
    except OSError:
        return False


def _has_packaged_source(project_root: Path, source_roots: Sequence[str]) -> bool:
    project_root = project_root.resolve()
    for root in source_roots:
        candidate = project_root / root
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(project_root):
                continue
        except OSError:
            continue
        if _is_python_package(resolved):
            return True
    return False


def has_packaged_python_source(project_root: Path, source_roots: Sequence[str]) -> bool:
    """判断源码根下是否存在可发布的 regular package。"""

    return _has_packaged_source(project_root, source_roots)


def _safe_existing_package(project_root: Path, value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip().replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or normalized in {"", "."}
        or any(part in {"", ".."} for part in relative.parts)
    ):
        return False
    candidate = project_root / relative.as_posix()
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(project_root.resolve()):
            return False
    except OSError:
        return False
    return resolved.is_dir() and _is_python_package(resolved)


def _hatch_wheel_packages(pyproject: Mapping[str, object]) -> object:
    tool = pyproject.get("tool")
    if not isinstance(tool, Mapping):
        return None
    hatch = tool.get("hatch")
    if not isinstance(hatch, Mapping):
        return None
    build = hatch.get("build")
    if not isinstance(build, Mapping):
        return None
    targets = build.get("targets")
    if not isinstance(targets, Mapping):
        return None
    wheel = targets.get("wheel")
    if not isinstance(wheel, Mapping):
        return None
    return wheel.get("packages")


def _hatch_sdist_excludes(pyproject: Mapping[str, object]) -> object:
    tool = pyproject.get("tool")
    if not isinstance(tool, Mapping):
        return None
    hatch = tool.get("hatch")
    if not isinstance(hatch, Mapping):
        return None
    build = hatch.get("build")
    if not isinstance(build, Mapping):
        return None
    targets = build.get("targets")
    if not isinstance(targets, Mapping):
        return None
    sdist = targets.get("sdist")
    if not isinstance(sdist, Mapping):
        return None
    return sdist.get("exclude")


def python_packaging_gaps(
    project_root: Path,
    pyproject: Mapping[str, object],
    source_roots: Sequence[str],
) -> tuple[str, ...]:
    """返回需要在 Setup 阶段修复的 Python 包装能力缺口。

    只有确定存在 ``__init__.py`` 包源码时才要求可发布包装；纯脚本项目
    仍使用 compileall。Hatchling 的 src layout 必须显式绑定 wheel package，
    防止 ``uv sync`` 通过但 ``uv build`` 在业务阶段才崩溃。
    """

    if not _has_packaged_source(project_root, source_roots):
        return ()
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, Mapping):
        return (PYTHON_PACKAGING_GAP,)
    backend = build_system.get("build-backend")
    if not isinstance(backend, str) or not backend.strip():
        return (PYTHON_PACKAGING_GAP,)
    requires = build_system.get("requires")
    if (
        isinstance(requires, (str, bytes))
        or not isinstance(requires, Sequence)
        or not requires
        or any(not isinstance(item, str) or not item.strip() for item in requires)
    ):
        return (PYTHON_PACKAGING_GAP,)
    if backend.strip() != "hatchling.build":
        return ()
    excludes = _hatch_sdist_excludes(pyproject)
    if (
        isinstance(excludes, (str, bytes))
        or not isinstance(excludes, Sequence)
        or not _REQUIRED_SDIST_EXCLUDES.issubset(
            item for item in excludes if isinstance(item, str)
        )
    ):
        return (PYTHON_PACKAGING_GAP,)
    if "src" not in source_roots:
        return ()
    packages = _hatch_wheel_packages(pyproject)
    if (
        isinstance(packages, (str, bytes))
        or not isinstance(packages, Sequence)
        or not packages
        or not all(_safe_existing_package(project_root, value) for value in packages)
    ):
        return (PYTHON_PACKAGING_GAP,)
    return ()


def python_build_command(
    source_roots: Sequence[str],
    packaging_gaps: Sequence[str],
    *,
    packaged_source: bool = False,
) -> tuple[str, ...]:
    """为 Python Profile 选择真实构建门禁；不满足包装前置时保守编译。"""

    if packaged_source and PYTHON_PACKAGING_GAP not in packaging_gaps:
        return ("uv", "build")
    return ("uv", "run", "python", "-m", "compileall", "-q", *source_roots)


__all__ = [
    "HATCHLING_SDIST_EXCLUDE_EXAMPLE",
    "PYTHON_PACKAGING_GAP",
    "has_packaged_python_source",
    "python_build_command",
    "python_packaging_gaps",
]
