"""Project Setup 阶段的 capability-only 范围与文件快照策略。

本模块只做确定性文件分类和边界校验，不推进 Tick、不写 EventStore，也不
调用宿主。状态更新由 :mod:`project_setup_service` 负责，避免把 setup 规则
再次混入主状态机。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

from auto_engineering.engine.state import EngineState
from auto_engineering.project_profile.models import ProjectProfile


class ProjectSetupScopeOwner(Protocol):
    project_root: Path
    _state: EngineState | None


def _state(owner: ProjectSetupScopeOwner) -> EngineState:
    state = owner._state
    if state is None:
        raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
    return state


def path_is_under_any(path: Path, roots: tuple[str, ...]) -> bool:
    """判断项目相对路径是否位于某个配置的 source/test root 下。"""
    for root in roots:
        root_path = Path(root)
        if root_path == Path("."):
            return True
        root_parts = root_path.parts
        if path.parts[: len(root_parts)] == root_parts:
            return True
    return False


def project_setup_scope_violations(
    owner: ProjectSetupScopeOwner,
    profile: ProjectProfile | None,
) -> dict[str, list[str]]:
    """识别 setup 后新增的业务实现与业务测试文件。"""
    if profile is None:
        return {}
    state = _state(owner)
    baseline = set(state.project_setup_baseline_files)
    added = sorted(set(project_setup_files(owner)) - baseline)
    source_roots = tuple(Path(root).as_posix().rstrip("/") for root in profile.source_roots)
    test_roots = tuple(Path(root).as_posix().rstrip("/") for root in profile.test_roots)
    violations: dict[str, list[str]] = {
        "business_implementation": [],
        "business_tests": [],
    }
    for relative_name in added:
        relative = Path(relative_name)
        nested_test_root = (
            path_is_under_any(relative, source_roots)
            and any(
                part.lower() in {"__tests__", "tests", "test"}
                for part in relative.parts[:-1]
            )
        )
        conventional_test_file = (
            relative.stem.lower().endswith((".test", ".spec"))
            or relative.name.lower() in {
                "setuptests.js", "setuptests.jsx", "setuptests.ts", "setuptests.tsx",
                "vitest.setup.js", "vitest.setup.ts",
                "jest.setup.js", "jest.setup.ts",
            }
        )
        is_test = (
            path_is_under_any(relative, test_roots)
            or nested_test_root
            or (path_is_under_any(relative, source_roots) and conventional_test_file)
        )
        if is_test:
            if not (
                relative.name in {"__init__.py", "conftest.py"}
                or is_minimal_setup_test(owner, relative)
                or is_minimal_setup_source(owner, relative)
            ):
                violations["business_tests"].append(relative_name)
        elif path_is_under_any(relative, source_roots) and not (
            is_minimal_setup_source(owner, relative)
            or is_minimal_setup_test(owner, relative)
        ):
            violations["business_implementation"].append(relative_name)
    return {kind: paths[:20] for kind, paths in violations.items() if paths}


def is_minimal_setup_test(owner: ProjectSetupScopeOwner, relative: Path) -> bool:
    """判断测试根未声明时，源码根内的最小工具链测试是否安全。"""
    stem = relative.stem.lower()
    is_named_setup = relative.name.lower() in {
        "setuptests.js", "setuptests.jsx", "setuptests.ts", "setuptests.tsx",
        "vitest.setup.js", "vitest.setup.ts", "jest.setup.js", "jest.setup.ts",
    }
    is_smoke_test = relative.name.lower() in {
        "test_smoke.js", "test_smoke.jsx", "test_smoke.ts", "test_smoke.tsx",
    } or stem in {"smoke", "setup.smoke", "toolchain.smoke"} or (
        any("smoke" in part.lower() for part in relative.parts)
        and (
            stem.endswith(".test")
            or stem.endswith(".spec")
            or relative.suffix.lower() == ".py"
        )
    )
    if not (is_named_setup or is_smoke_test):
        return False
    candidate = owner.project_root / relative
    try:
        if candidate.stat().st_size > 16 * 1024:
            return False
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    imports = re.findall(
        r"\bfrom\s+['\"]([^'\"]+)['\"]|\bimport\s+['\"]([^'\"]+)['\"]",
        content,
    )
    imported = {item for pair in imports for item in pair if item}
    imported.update(re.findall(r"(?m)^\s*(?:from|import)\s+([.A-Za-z_][\w.]*)", content))
    allowed_external = {
        "@testing-library/jest-dom", "@testing-library/jest-dom/vitest",
        "@testing-library/react", "jsdom", "pytest", "react", "react-dom",
        "react-dom/client", "subprocess", "sys", "typing", "unittest", "vitest",
    }
    if any(item.startswith((".", "/")) for item in imported):
        return all(
            is_setup_safe_local_import(owner, relative, item)
            if item.startswith((".", "/"))
            else item in allowed_external
            for item in imported
        )
    return imported.issubset(allowed_external)


def is_setup_safe_local_import(
    owner: ProjectSetupScopeOwner,
    relative: Path,
    imported: str,
) -> bool:
    """只放行解析到另一个 setup-safe 占位文件的相对导入。"""
    root = owner.project_root.resolve()
    try:
        base = (owner.project_root / relative.parent / imported).resolve()
        if not base.is_relative_to(root):
            return False
    except OSError:
        return False
    candidates = [base]
    candidates.extend(
        base.with_suffix(base.suffix + suffix)
        for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts")
    )
    candidates.extend(
        base / f"index{suffix}"
        for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts")
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            target = candidate.relative_to(root)
        except ValueError:
            return False
        return is_minimal_setup_source(owner, target)
    return False


def is_minimal_setup_source(owner: ProjectSetupScopeOwner, relative: Path) -> bool:
    """判断新增源码是否是受限的工程 smoke 入口。"""
    if relative.name in {"__init__.py", "py.typed"} or relative.name == "vite-env.d.ts":
        return True
    candidate = owner.project_root / relative
    try:
        if candidate.stat().st_size > 16 * 1024:
            return False
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    has_canonical_marker = re.search(
        r"(?i)\bAE_SETUP_SMOKE\b", content[:16 * 1024]
    ) is not None
    has_smoke_marker = re.search(
        r"(?i)(?:\bAE_SETUP_SMOKE\b|"
        r"\b(?:minimal|setup)\s+(?:non[- ]business\s+)?smoke\b|"
        r"\bnon[- ]business\b.{0,80}\b(?:smoke|placeholder|toolchain)\b)",
        content[:16 * 1024],
    ) is not None
    if has_canonical_marker or (
        has_smoke_marker
        and relative.stem.lower()
        in {"bootstrap", "index", "main", "placeholder", "setup", "toolchain"}
    ):
        return True
    if relative.stem.lower() == "app" and relative.suffix.lower() in {".jsx", ".tsx"}:
        match = re.fullmatch(
            r"\s*(?:/\*.*?\*/\s*|//[^\n]*\n\s*)*"
            r"(?:(?:export\s+default|export)\s+)?function\s+App\s*\(\s*\)\s*\{\s*"
            r"return\s+<div(?P<attrs>(?:\s+[A-Za-z_:][\w:.-]*"
            r"(?:\s*=\s*(?:\"[^\"<>]{0,120}\"|'[^'<>]{0,120}'))?)*)>"
            r"[^<>]{0,120}</div>\s*\}\s*"
            r"(?:export\s+default\s+App\s*;?\s*)?",
            content,
            flags=re.DOTALL,
        )
        return match is not None and re.search(
            r"(?i)(?:^|\s)on[a-z][\w:-]*\s*=|javascript:|[{}]",
            match.group("attrs") if match else "",
        ) is None
    if (
        relative.stem.lower() == "setup"
        and "test" in {part.lower() for part in relative.parts}
        and relative.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}
    ):
        imports = re.findall(
            r"\bfrom\s+['\"]([^'\"]+)['\"]|\bimport\s+['\"]([^'\"]+)['\"]",
            content,
        )
        imported = {item for pair in imports for item in pair if item}
        return imported.issubset({
            "@testing-library/jest-dom", "@testing-library/jest-dom/vitest", "vitest",
        }) and re.fullmatch(
            r"\s*(?:/\*.*?\*/\s*|//[^\n]*\n\s*|"
            r"import\s+(?:[^;\n]+?\s+from\s+)?['\"][^'\"]+['\"]\s*;?\s*)*",
            content,
            flags=re.DOTALL,
        ) is not None
    if relative.stem not in {"main", "index"} or relative.suffix.lower() not in {
        ".cjs", ".cts", ".go", ".js", ".jsx", ".mjs", ".mts", ".py", ".rs", ".ts", ".tsx",
    }:
        return False
    imports = re.findall(
        r"\bfrom\s+['\"]([^'\"]+)['\"]|\bimport\s+['\"]([^'\"]+)['\"]",
        content,
    )
    imported = {item for pair in imports for item in pair if item}
    return (
        relative.suffix.lower() in {".jsx", ".tsx"}
        and "createRoot" in content
        and ".render" in content
        and imported.issubset({
            "react", "react-dom/client", "./App", "./App.jsx", "./App.tsx",
            "../App", "../App.jsx", "../App.tsx", "../container/App",
            "../container/App.jsx", "../container/App.tsx",
        })
        and not re.search(
            r"(?i)(fetch|xmlhttprequest|localstorage|sessionstorage|\bminimax\b|\baudio\b)",
            content,
        )
    )


def project_setup_files(owner: ProjectSetupScopeOwner) -> list[str]:
    """返回不含 Core 临时目录和目录占位元数据的项目文件集合。

    ``.gitkeep`` 只用于让空的 source/test root 在文件系统中可见，不是
    工程实现、测试或运行时输入；若把它纳入业务文件扫描，Setup 为了
    建立合法的空目录反而会触发自己的 scope violation。
    """
    excluded = {
        ".git", ".ae-state", ".venv", "node_modules", "dist", "build", "_scratch", "__pycache__",
    }
    root = owner.project_root.resolve()
    selected: list[str] = []
    for candidate in owner.project_root.rglob("*"):
        relative = candidate.relative_to(owner.project_root)
        if excluded.intersection(relative.parts) or any(
            part.endswith((".egg-info", ".dist-info")) for part in relative.parts
        ):
            continue
        if candidate.name == ".gitkeep":
            continue
        if not (candidate.is_file() or candidate.is_symlink()):
            continue
        try:
            if not candidate.resolve().is_relative_to(root):
                continue
        except OSError:
            continue
        selected.append(relative.as_posix())
        if len(selected) > 10_000:
            raise ValueError("PROJECT_SETUP_BASELINE_TOO_LARGE: 超过 10000 个文件")
    return sorted(selected)


def project_setup_fingerprint(owner: ProjectSetupScopeOwner) -> str:
    """计算 Setup 输入指纹，证明资源恢复确实改变了项目。"""
    digest = hashlib.sha256()
    for relative_name in project_setup_files(owner):
        candidate = owner.project_root / relative_name
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        if candidate.is_symlink():
            try:
                digest.update(b"symlink:")
                digest.update(str(candidate.readlink()).encode("utf-8"))
            except OSError as exc:
                digest.update(f"symlink-error:{type(exc).__name__}".encode())
        else:
            try:
                with candidate.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as exc:
                digest.update(f"read-error:{type(exc).__name__}".encode())
        digest.update(b"\0")
    return digest.hexdigest()


def project_setup_snapshot_files(
    owner: ProjectSetupScopeOwner,
    profile: ProjectProfile,
) -> list[str]:
    """为 setup Gate 构造有界、项目内的确定性文件快照。"""
    excluded = {".git", ".ae-state", "_scratch", "node_modules"}
    root = owner.project_root.resolve()
    selected: set[str] = set()
    for evidence in profile.evidence:
        candidate = owner.project_root / evidence.source
        if (
            candidate.is_file()
            and not excluded.intersection(Path(evidence.source).parts)
            and candidate.resolve().is_relative_to(root)
        ):
            selected.add(candidate.relative_to(owner.project_root).as_posix())
    for root_name in (*profile.source_roots, *profile.test_roots):
        source_root = owner.project_root / root_name
        if not source_root.is_dir() or not source_root.resolve().is_relative_to(root):
            continue
        for candidate in source_root.rglob("*"):
            if candidate.is_file() and not candidate.is_symlink():
                selected.add(candidate.relative_to(owner.project_root).as_posix())
                if len(selected) > 10_000:
                    raise ValueError("PROJECT_SETUP_SNAPSHOT_TOO_LARGE: 超过 10000 个文件")
    if not selected:
        raise ValueError("PROJECT_SETUP_SNAPSHOT_EMPTY: 无可验证项目文件")
    return sorted(selected)


__all__ = [
    "ProjectSetupScopeOwner",
    "is_minimal_setup_source",
    "is_minimal_setup_test",
    "is_setup_safe_local_import",
    "path_is_under_any",
    "project_setup_files",
    "project_setup_fingerprint",
    "project_setup_scope_violations",
    "project_setup_snapshot_files",
]
