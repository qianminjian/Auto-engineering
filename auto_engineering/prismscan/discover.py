"""PrismScan V5.1 — Discover: 项目目录扫描 + 语言/构建系统/模块边界识别.

纯 Python 确定性计算, 不涉及 LLM.
输入: project_root (str)
输出: ProjectShape (dataclass, 定义在 schemas.py)
"""

from __future__ import annotations

import os
from pathlib import Path

from auto_engineering.prismscan.schemas import ModuleInfo, ProjectShape

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "c++",
    ".hpp": "c++",
    ".cc": "c++",
    ".rb": "ruby",
    ".php": "php",
    ".vue": "vue",
    ".svelte": "svelte",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
}

_BUILD_SYSTEM_FILES: dict[str, str] = {
    "pyproject.toml": "uv",
    "setup.py": "setuptools",
    "setup.cfg": "setuptools",
    "requirements.txt": "pip",
    "Pipfile": "pipenv",
    "package.json": "npm",
    "tsconfig.json": "typescript",
    "go.mod": "gomod",
    "Cargo.toml": "cargo",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
}

_IGNORE_DIRS: set[str] = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", ".venv", "venv", "env",
    ".env", "dist", "build", ".next", ".nuxt", ".output",
    "target", ".tox", ".eggs", ".coverage", "coverage",
    "htmlcov", ".cache", ".idea", ".vscode", ".vs", ".DS_Store",
}

_ENTRY_PATTERNS: list[str] = [
    "main.py", "app.py", "index.py", "cli.py", "manage.py",
    "main.rs", "main.go", "index.ts", "index.js", "App.tsx",
    "server.js", "server.ts",
]


def _should_ignore(name: str) -> bool:
    if name in _IGNORE_DIRS:
        return True
    return bool(name.startswith(".") and name != ".github")


def walk_directory(project_root: str) -> list[Path]:
    root = Path(project_root).resolve()
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_ignore(d)]
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir.parts and _should_ignore(rel_dir.parts[0]):
            dirnames[:] = []
            continue
        for fname in filenames:
            if not _should_ignore(fname):
                files.append(Path(dirpath) / fname)
    return files


def detect_languages(files: list[Path]) -> list[str]:
    """根据文件扩展名检测使用的编程语言, 返回小写名称按文件数降序."""
    lang_counts: dict[str, int] = {}
    for f in files:
        suffix = f.suffix.lower()
        if not suffix:
            name_lower = f.name.lower()
            if name_lower == "dockerfile":
                lang_counts["docker"] = lang_counts.get("docker", 0) + 1
            elif name_lower == "makefile":
                lang_counts["make"] = lang_counts.get("make", 0) + 1
            continue
        lang = _EXT_TO_LANG.get(suffix)
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    return sorted(lang_counts, key=lang_counts.get, reverse=True)  # type: ignore[arg-type]


def detect_build_system(files: list[Path]) -> str:
    file_names = {f.name for f in files}
    for indicator, system in sorted(_BUILD_SYSTEM_FILES.items()):
        if indicator in file_names:
            return system
    return "unknown"


def identify_modules(project_root: str | Path, extension_filter: str = ".py") -> list[ModuleInfo]:
    """识别项目模块结构.

    Args:
        project_root: 项目根目录.
        extension_filter: 按扩展名过滤 (如 ".py" 只识别 Python 模块).
    """
    root = Path(project_root).resolve()
    modules: list[ModuleInfo] = []

    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or _should_ignore(entry.name):
            continue
        src_files = [f for f in entry.rglob(f"*{extension_filter}") if f.is_file()]
        if not src_files:
            continue
        file_count = len(src_files)
        languages: set[str] = set()
        ext_set = {f.suffix.lower() for f in entry.rglob("*") if f.is_file()}
        for ext in ext_set:
            lang = _EXT_TO_LANG.get(ext)
            if lang:
                languages.add(lang)

        entry_point = ""
        for ep in _ENTRY_PATTERNS:
            ep_path = entry / ep
            if ep_path.exists():
                entry_point = str(ep_path.relative_to(root))
                break

        modules.append(ModuleInfo(
            name=entry.name,
            path=str(entry.relative_to(root)),
            file_count=file_count,
            language=", ".join(sorted(languages)),
            entry_point=entry_point,
        ))
    return modules


def find_entry_points(project_root: str | Path, extension_filter: str = ".py") -> list[str]:
    """识别项目入口文件.

    Args:
        project_root: 项目根目录.
        extension_filter: 按扩展名过滤入口文件.
    """
    root = Path(project_root).resolve()
    entries: list[str] = []
    for pattern in _ENTRY_PATTERNS:
        if not pattern.endswith(extension_filter):
            continue
        for candidate in root.rglob(pattern):
            if not any(_should_ignore(p) for p in candidate.relative_to(root).parts):
                entries.append(str(candidate.relative_to(root)))
    return sorted(entries)


def generate_tree_summary(project_root: str | Path, max_depth: int = 3) -> str:
    root = Path(project_root).resolve()
    lines: list[str] = [f"{root.name}/"]
    try:
        entries = sorted(root.iterdir())
    except PermissionError:
        return f"{root.name}/ [permission denied]"

    for entry in entries:
        if _should_ignore(entry.name):
            continue
        if entry.is_dir():
            lines.append(f"├── {entry.name}/")
            if max_depth > 1:
                try:
                    sub_entries = sorted(entry.iterdir())
                except PermissionError:
                    continue
                count = 0
                for sub in sub_entries:
                    if _should_ignore(sub.name):
                        continue
                    if count >= 10:
                        lines.append(f"│   └── ... ({len(sub_entries) - count} more)")
                        break
                    prefix = "│   ├──" if count < min(10, len(sub_entries)) - 1 else "│   └──"
                    suffix = "/" if sub.is_dir() else ""
                    lines.append(f"{prefix} {sub.name}{suffix}")
                    count += 1
        else:
            lines.append(f"├── {entry.name}")
    return "\n".join(lines)


def discover(project_root: str) -> ProjectShape:
    """扫描项目目录，识别语言、构建系统、模块边界、入口文件."""
    root = Path(project_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"项目目录不存在: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"路径不是目录: {root}")

    files = walk_directory(str(root))

    return ProjectShape(
        project_name=root.name,
        languages=detect_languages(files),
        build_system=detect_build_system(files),
        modules=identify_modules(root),
        entry_points=find_entry_points(root),
        has_docker=(root / "Dockerfile").exists() or (root / "docker-compose.yml").exists(),
        total_files=len(files),
        directory_tree_summary=generate_tree_summary(root),
    )
