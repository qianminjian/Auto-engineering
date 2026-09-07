"""通过 Claude Code 原生 Marketplace 安装 Auto-Engineering 插件。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from .install_codex_local import (
        DEFAULT_MARKETPLACE_SOURCE,
        PLUGIN_ID,
        StagedRelease,
        _is_within,
        _seal_release_tree,
        stage_archive,
        stage_release,
        verify_runtime_paths,
    )
else:
    from install_codex_local import (
        DEFAULT_MARKETPLACE_SOURCE,
        PLUGIN_ID,
        StagedRelease,
        _is_within,
        _seal_release_tree,
        stage_archive,
        stage_release,
        verify_runtime_paths,
    )

MARKETPLACE_NAME = "auto-engineering"


@dataclass(frozen=True)
class CommandRunner:
    run: Callable[[list[str]], subprocess.CompletedProcess[str]]

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.run(command)


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _run_required(
    runner: CommandRunner,
    command: list[str],
    *,
    allow_missing: bool = False,
) -> None:
    result = runner(command)
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip()
    if allow_missing and any(
        marker in detail.lower()
        for marker in ("not installed", "not configured", "not found", "does not exist")
    ):
        return
    raise RuntimeError(
        f"命令失败 ({result.returncode}): {' '.join(command)}\n{detail}"
    )


def install_claude_release(
    staged_root: Path,
    *,
    development_root: Path,
    runner: CommandRunner | None = None,
) -> None:
    """只允许 Claude Code 从开发目录之外的 Release Marketplace 安装。"""

    release_root = staged_root.expanduser().resolve()
    if _is_within(release_root, development_root.resolve()):
        raise ValueError("Claude Marketplace 必须位于开发目录之外")
    if not (release_root / ".claude-plugin/marketplace.json").is_file():
        raise RuntimeError("Release 缺少 Claude Marketplace manifest")

    execute = runner or CommandRunner(_default_runner)
    # Claude 的官方缓存由安装器以只读方式封存；替换前必须先枚举并只解封
    # 明确属于本插件受控边界的旧版本，不能对整个缓存目录递归 chmod。
    installed_plugins = _json_command(
        ["claude", "plugin", "list", "--json"], runner=execute,
    )
    prepare_existing_install_for_removal(installed_plugins)
    release_version = release_root.name.split("+sha256.", 1)[0]
    prepare_orphaned_version_cache_for_removal(version=release_version)
    commands = [
        ["claude", "plugin", "uninstall", PLUGIN_ID, "--scope", "user", "--yes"],
        [
            "claude", "plugin", "marketplace", "remove", MARKETPLACE_NAME,
            "--scope", "user",
        ],
        [
            "claude", "plugin", "marketplace", "add", str(release_root),
            "--scope", "user",
        ],
        ["claude", "plugin", "install", PLUGIN_ID, "--scope", "user"],
    ]
    for index, command in enumerate(commands):
        _run_required(execute, command, allow_missing=index < 2)


def install_claude_marketplace(
    *,
    source: str = DEFAULT_MARKETPLACE_SOURCE,
    runner: CommandRunner | None = None,
) -> None:
    """通过 Claude Code 原生 Marketplace 安装 GitHub 插件。"""
    if not source.strip():
        raise ValueError("Marketplace 来源不能为空")
    execute = runner or CommandRunner(_default_runner)
    commands = [
        [
            "claude", "plugin", "uninstall", PLUGIN_ID,
            "--scope", "user", "--yes",
        ],
        [
            "claude", "plugin", "marketplace", "remove", MARKETPLACE_NAME,
            "--scope", "user",
        ],
        [
            "claude", "plugin", "marketplace", "add", source,
            "--scope", "user",
        ],
        ["claude", "plugin", "install", PLUGIN_ID, "--scope", "user"],
    ]
    for index, command in enumerate(commands):
        _run_required(execute, command, allow_missing=index < 2)


def _json_command(
    command: list[str], *, runner: CommandRunner | None = None,
) -> object:
    result = (runner or CommandRunner(_default_runner))(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"命令失败 ({result.returncode}): {' '.join(command)}\n{detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claude Code 插件枚举未返回 JSON") from exc


def _make_tree_removable(root: Path) -> None:
    """Temporarily unseal one verified prior install for official uninstall."""

    paths = list(root.rglob("*"))
    for path in paths:
        if path.is_symlink():
            continue
        if path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            path.chmod(0o755 if executable else 0o644)
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink() and path.is_dir():
            path.chmod(0o755)
    root.chmod(0o755)


def prepare_existing_install_for_removal(
    plugins: object,
    *,
    cache_root: Path | None = None,
) -> None:
    """Unseal only the enumerated user plugin inside Claude's owned cache."""

    if not isinstance(plugins, list):
        raise RuntimeError("Claude Code 插件枚举结构无效")
    boundary = (
        cache_root
        or Path.home() / ".claude/plugins/cache/auto-engineering/auto-engineering"
    ).expanduser().resolve()
    for item in plugins:
        if not (
            isinstance(item, dict)
            and item.get("id") == PLUGIN_ID
            and item.get("scope") == "user"
        ):
            continue
        raw_path = item.get("installPath")
        if not isinstance(raw_path, str) or not raw_path:
            raise RuntimeError("Claude 旧插件缺少 installPath")
        plugin_root = Path(raw_path).expanduser().resolve()
        if not _is_within(plugin_root, boundary) or not plugin_root.is_dir():
            raise RuntimeError("Claude 旧插件路径越出受控缓存边界")
        _make_tree_removable(plugin_root)


def prepare_orphaned_version_cache_for_removal(
    *,
    version: str,
    cache_root: Path | None = None,
) -> None:
    """Unseal the exact same-version orphan left after registration removal."""

    boundary = (
        cache_root
        or Path.home() / ".claude/plugins/cache/auto-engineering/auto-engineering"
    ).expanduser().resolve()
    orphan = (boundary / version).resolve()
    if not orphan.exists():
        return
    if not _is_within(orphan, boundary) or not orphan.is_dir():
        raise RuntimeError("Claude 孤儿缓存路径越出受控边界")
    try:
        build_info = json.loads(
            (orphan / "build-info.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Claude 孤儿缓存缺少有效 build-info.json") from exc
    build_id = build_info.get("build_id") if isinstance(build_info, dict) else None
    if (
        not isinstance(build_info, dict)
        or build_info.get("version") != version
        or not isinstance(build_id, str)
        or not build_id.startswith(f"{version}+sha256.")
    ):
        raise RuntimeError("Claude 孤儿缓存 Build Identity 无效")
    _make_tree_removable(orphan)


def verify_claude_install(release: StagedRelease, development_root: Path) -> None:
    """验证 Claude Code 注册、安装来源、Build 与独立 Python Runtime。"""

    source = development_root.resolve()
    marketplaces = _json_command(["claude", "plugin", "marketplace", "list", "--json"])
    plugins = _json_command(["claude", "plugin", "list", "--json"])
    if not isinstance(marketplaces, list) or not isinstance(plugins, list):
        raise RuntimeError("Claude Code 插件枚举结构无效")
    marketplace = next(
        (
            item for item in marketplaces
            if isinstance(item, dict) and item.get("name") == MARKETPLACE_NAME
        ),
        None,
    )
    if not isinstance(marketplace, dict):
        raise RuntimeError("Claude Code 未注册本次 Release Marketplace")
    install_location = marketplace.get("installLocation")
    if not isinstance(install_location, str) or not install_location:
        raise RuntimeError("Claude Marketplace 缺少 installLocation")

    installed = next(
        (
            item for item in plugins
            if isinstance(item, dict) and item.get("id") == PLUGIN_ID
            and item.get("scope") == "user" and item.get("enabled") is True
        ),
        None,
    )
    if not isinstance(installed, dict):
        raise RuntimeError("Claude Code 未启用本次用户级插件")
    plugin_path = installed.get("installPath")
    if not isinstance(plugin_path, str) or not plugin_path:
        raise RuntimeError("Claude 插件缺少 installPath")
    plugin_root = Path(plugin_path).resolve()
    if _is_within(Path(install_location), source) or _is_within(plugin_root, source):
        raise RuntimeError("Claude Code 运行态仍访问开发目录")

    build_info_path = plugin_root / "build-info.json"
    try:
        build_info = json.loads(build_info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Claude 插件缺少有效 build-info.json") from exc
    if build_info.get("build_id") != release.build_id:
        raise RuntimeError("Claude 插件 Build Identity 与本次 Release 不一致")

    environment = os.environ.copy()
    for name in (
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "CODEX_THREAD_ID",
        "CODEX_SANDBOX",
        "CODEX_CI",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_SESSION_ID",
    ):
        environment.pop(name, None)
    environment["CLAUDE_CODE_ENTRYPOINT"] = "cli"
    runtime_python: Path
    with tempfile.TemporaryDirectory(prefix="ae-claude-install-verify-") as project:
        project_root = Path(project)
        (project_root / ".ae-state").mkdir()
        doctor = subprocess.run(
            [str(plugin_root / "bin/ae-run"), "doctor", "--project-root", project],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if doctor.returncode != 0:
            detail = doctor.stderr.strip() or doctor.stdout.strip()
            raise RuntimeError(f"Claude 独立运行时 doctor 失败: {detail}")
        runtime_root = project_root / ".ae-state/.ae-runtime"
        runtime_python = runtime_root / "bin/python"
        origin = subprocess.run(
            [
                str(runtime_python),
                "-c",
                "import auto_engineering; print(auto_engineering.__file__)",
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if origin.returncode != 0:
            raise RuntimeError("无法读取 Claude 插件 Python 模块来源")
        verify_runtime_paths(
            development_root=source,
            marketplace_root=Path(install_location),
            plugin_root=plugin_root,
            runtime_root=runtime_root,
            module_origin=Path(origin.stdout.strip()),
        )
    _seal_release_tree(plugin_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=Path.home() / ".local/share/auto-engineering/releases",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_MARKETPLACE_SOURCE,
        help="GitHub Marketplace 来源（默认 qianminjian/Auto-engineering）",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="指定已构建 Release archive；安装后校验同一 Build Identity",
    )
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()

    if args.stage_only:
        release = (
            stage_archive(
                args.archive,
                args.staging_root,
                development_root=args.root,
            )
            if args.archive is not None
            else stage_release(args.root, args.staging_root)
        )
        payload = {
            "status": "staged",
            "version": release.version,
            "build_id": release.build_id,
            "release_root": str(release.root),
        }
    elif args.archive is not None:
        release = stage_archive(
            args.archive,
            args.staging_root,
            development_root=args.root,
        )
        install_claude_release(release.root, development_root=args.root)
        verify_claude_install(release, args.root)
        payload = {
            "status": "installed",
            "source": str(args.archive.expanduser().resolve()),
            "build_id": release.build_id,
            "release_root": str(release.root),
            "plugin": PLUGIN_ID,
        }
    else:
        install_claude_marketplace(source=args.source)
        payload = {
            "status": "installed",
            "source": args.source,
            "plugin": PLUGIN_ID,
        }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
