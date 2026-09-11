"""通过 Codex 原生 Marketplace 安装 Auto-Engineering 插件。"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# When this installer is invoked as ``python scripts/install_codex_local.py``
# from a project outside the repository, Python puts only ``scripts/`` on
# ``sys.path``.  Resolve the repository root explicitly so the documented
# standalone entrypoint does not depend on an editable install or PYTHONPATH.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from auto_engineering.build_identity import validate_build_info  # noqa: E402

# 统一为一次动态模块加载，兼容包入口和 ``python scripts/install_codex_local.py``
# 直接入口，同时避免静态检查把两个分支视为重复导入。
_SUPPORT_PACKAGE = __package__ or ""
_BUILD_RELEASE = importlib.import_module(
    f"{_SUPPORT_PACKAGE}.build_release" if _SUPPORT_PACKAGE else "build_release"
)
_INSTALL_ACCEPTANCE = importlib.import_module(
    f"{_SUPPORT_PACKAGE}.install_acceptance"
    if _SUPPORT_PACKAGE
    else "install_acceptance"
)
_release_content_digest = cast(
    Callable[[Path], str], vars(_BUILD_RELEASE)["_release_content_digest"]
)
build_archive = cast(
    Callable[[Path, Path], Path], vars(_BUILD_RELEASE)["build_archive"]
)
_safe_extract_archive = cast(
    Callable[[tarfile.TarFile, Path], None],
    vars(_INSTALL_ACCEPTANCE)["_safe_extract_archive"],
)

PLUGIN_ID = "auto-engineering@auto-engineering"
MARKETPLACE_NAME = "auto-engineering"
DEFAULT_MARKETPLACE_SOURCE = "qianminjian/Auto-engineering"


@dataclass(frozen=True)
class StagedRelease:
    root: Path
    version: str
    build_id: str
    content_sha256: str


@dataclass(frozen=True)
class CommandRunner:
    run: Callable[[list[str]], subprocess.CompletedProcess[str]]

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.run(command)


def _is_within(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def _seal_release_tree(root: Path) -> None:
    """Seal installed product bytes; runtime is created in the target project."""

    root = root.resolve()
    paths = list(root.rglob("*"))
    for path in paths:
        if path.is_symlink():
            raise RuntimeError("安装制品不得包含符号链接")
        if path.is_file():
            executable = bool(path.stat().st_mode & 0o111)
            path.chmod(0o555 if executable else 0o444)
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
    root.chmod(0o555)


def _read_build_info(root: Path) -> StagedRelease:
    payload = json.loads((root / "build-info.json").read_text(encoding="utf-8"))
    try:
        identity = validate_build_info(payload)
    except ValueError as exc:
        raise RuntimeError("Release build-info.json 身份无效") from exc
    return StagedRelease(
        root=root.resolve(),
        version=identity["version"],
        build_id=identity["build_id"],
        content_sha256=identity["content_sha256"],
    )


def _verify_staged_release(root: Path) -> StagedRelease:
    release = _read_build_info(root)
    release_paths = root.rglob("*")
    if any(path.is_symlink() for path in release_paths):
        raise RuntimeError("Release 暂存目录不得包含符号链接")
    actual_digest = _release_content_digest(root)
    if actual_digest != release.content_sha256:
        raise RuntimeError("Release 内容摘要与 build-info.json 不一致")
    return release


def _store_staged_release(extracted: Path, staging_root: Path) -> StagedRelease:
    """校验解压结果并原子移动到 content-addressed staging 目录。"""
    destination_parent = staging_root.expanduser().resolve()
    destination_parent.mkdir(parents=True, exist_ok=True)
    release = _verify_staged_release(extracted)
    final_root = destination_parent / release.build_id
    if final_root.exists():
        existing = _verify_staged_release(final_root)
        if existing.content_sha256 != release.content_sha256:
            raise RuntimeError("同 build_id 的已暂存 Release 内容不一致")
        return existing
    try:
        os.replace(extracted, final_root)
    except OSError as exc:
        # 两个宿主可能同时暂存同一内容寻址 Build。若竞争方已经完成移动，
        # 只复用并重新校验其不可变目录；其他错误仍然原样失败。
        if not final_root.exists():
            raise
        existing = _verify_staged_release(final_root)
        if existing.content_sha256 != release.content_sha256:
            raise RuntimeError("同 build_id 的已暂存 Release 内容不一致") from exc
        return existing
    return _verify_staged_release(final_root)


def stage_release(development_root: Path, staging_root: Path) -> StagedRelease:
    """构建并原子暂存到源码树之外的 content-addressed 目录。"""
    source = development_root.resolve()
    destination_parent = staging_root.expanduser().resolve()
    if _is_within(destination_parent, source):
        raise ValueError("Release 暂存目录必须位于开发目录之外")
    destination_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".auto-engineering-stage-", dir=destination_parent) as temporary:
        workspace = Path(temporary)
        archive = build_archive(source, workspace / "release.tar.gz")
        extracted = workspace / "release"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            _safe_extract_archive(package, extracted)
        return _store_staged_release(extracted, destination_parent)


def stage_archive(
    archive: Path,
    staging_root: Path,
    *,
    development_root: Path | None = None,
) -> StagedRelease:
    """把指定 Release archive 安全解压并暂存，不重新从开发树构建。"""
    source_archive = archive.expanduser().resolve()
    if not source_archive.is_file():
        raise FileNotFoundError(f"Release archive 不存在: {source_archive}")
    destination_parent = staging_root.expanduser().resolve()
    if development_root is not None and _is_within(
        destination_parent, development_root.resolve()
    ):
        raise ValueError("Release 暂存目录必须位于开发目录之外")
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".auto-engineering-archive-stage-", dir=destination_parent
    ) as temporary:
        extracted = Path(temporary) / "release"
        extracted.mkdir()
        with tarfile.open(source_archive, "r:gz") as package:
            _safe_extract_archive(package, extracted)
        return _store_staged_release(extracted, destination_parent)


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _run_required(
    runner: CommandRunner, command: list[str], *, allow_missing: bool = False
) -> None:
    result = runner(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        normalized = detail.lower()
        if allow_missing and any(
            marker in normalized
            for marker in ("not installed", "not configured", "not found")
        ):
            return
        raise RuntimeError(f"命令失败 ({result.returncode}): {' '.join(command)}\n{detail}")


def install_codex_release(
    staged_root: Path,
    *,
    development_root: Path,
    runner: CommandRunner | None = None,
) -> None:
    """只允许 Codex 从开发目录之外的已暂存 Marketplace 安装。"""
    release_root = staged_root.expanduser().resolve()
    source = development_root.resolve()
    if _is_within(release_root, source):
        raise ValueError("Codex Marketplace 必须位于开发目录之外")
    if not (release_root / ".agents/plugins/marketplace.json").is_file():
        raise RuntimeError("Release 缺少 Codex Marketplace manifest")

    execute = runner or CommandRunner(_default_runner)
    commands = [
        ["codex", "plugin", "remove", PLUGIN_ID, "--json"],
        ["codex", "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
        ["codex", "plugin", "marketplace", "add", str(release_root), "--json"],
        ["codex", "plugin", "add", PLUGIN_ID, "--json"],
    ]
    for index, command in enumerate(commands):
        _run_required(execute, command, allow_missing=index < 2)


def _validate_codex_plugin_build(
    plugins_output: str,
    release: StagedRelease,
) -> None:
    """校验 Codex 原生清单指向的插件内容，而不只比对路径字符串。"""
    try:
        payload = json.loads(plugins_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Codex 插件清单不是有效 JSON") from exc
    installed = payload.get("installed") if isinstance(payload, dict) else None
    if not isinstance(installed, list):
        raise RuntimeError("Codex 插件清单缺少 installed 数组")
    item = next(
        (
            candidate
            for candidate in installed
            if isinstance(candidate, dict)
            and candidate.get("pluginId") == PLUGIN_ID
        ),
        None,
    )
    if not isinstance(item, dict):
        raise RuntimeError(f"Codex 未列出已安装插件 {PLUGIN_ID}")
    source = item.get("source")
    source_path = source.get("path") if isinstance(source, dict) else None
    if not isinstance(source_path, str) or not source_path.strip():
        raise RuntimeError("Codex 插件清单缺少 source.path")
    plugin_root = Path(source_path).expanduser().resolve()
    try:
        installed_release = _read_build_info(plugin_root)
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError("Codex 已加载插件缺少有效 build-info.json") from exc
    if (
        installed_release.build_id != release.build_id
        or installed_release.content_sha256 != release.content_sha256
    ):
        raise RuntimeError(
            "Codex 已加载插件 Build Identity 与候选 Release 不一致: "
            f"expected={release.build_id}, actual={installed_release.build_id}"
        )


def install_codex_marketplace(
    *,
    source: str = DEFAULT_MARKETPLACE_SOURCE,
    ref: str | None = None,
    runner: CommandRunner | None = None,
) -> None:
    """通过 Codex 原生 Marketplace 安装 GitHub 插件。"""
    if not source.strip():
        raise ValueError("Marketplace 来源不能为空")
    execute = runner or CommandRunner(_default_runner)
    add_marketplace = [
        "codex", "plugin", "marketplace", "add", source,
    ]
    if ref:
        add_marketplace.extend(["--ref", ref])
    add_marketplace.append("--json")
    commands = [
        ["codex", "plugin", "remove", PLUGIN_ID, "--json"],
        ["codex", "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
        add_marketplace,
        ["codex", "plugin", "add", PLUGIN_ID, "--json"],
    ]
    for index, command in enumerate(commands):
        _run_required(execute, command, allow_missing=index < 2)


def verify_runtime_paths(
    *,
    development_root: Path,
    marketplace_root: Path,
    plugin_root: Path,
    runtime_root: Path,
    module_origin: Path,
) -> None:
    """验证制品来源，且运行时位于目标项目而非只读插件树。"""
    source = development_root.resolve()
    candidates = {
        "Marketplace": marketplace_root,
        "插件": plugin_root,
        "Python 模块": module_origin,
        "运行时": runtime_root,
    }
    leaked = [name for name, path in candidates.items() if _is_within(path, source)]
    if _is_within(runtime_root, plugin_root) or _is_within(runtime_root, marketplace_root):
        leaked.append("运行时")
    if leaked:
        raise RuntimeError("运行态仍访问开发目录: " + ", ".join(leaked))
    if not _is_within(module_origin, plugin_root):
        raise RuntimeError("Python 模块来源不属于已安装插件")
    if not runtime_root.is_dir():
        raise RuntimeError("项目独立运行时不存在")


def verify_codex_hook_wire_contract(
    *,
    plugin_root: Path,
    project_root: Path,
    environment: dict[str, str],
) -> None:
    """验证已安装 Codex Hook 的阻断响应符合宿主严格 Wire Schema。"""

    handler = plugin_root / "hooks" / "codex-hook.sh"
    if not handler.is_file():
        raise RuntimeError("Codex 安装制品缺少 Hook 执行入口")
    payload = {
        "hook_event_name": "PreToolUse",
        "cwd": str(project_root),
        "session_id": "local-install-hook-verification",
        "tool_name": "Bash",
        "tool_input": {"command": "printf blocked > .ae-state/events.db"},
    }
    hook_environment = dict(environment)
    hook_environment["PLUGIN_ROOT"] = str(plugin_root)
    try:
        result = subprocess.run(
            [str(handler)],
            cwd=project_root,
            env=hook_environment,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Codex Hook Wire Contract 执行失败") from exc
    if result.returncode != 0:
        raise RuntimeError(
            "Codex Hook Wire Contract 执行失败: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Codex Hook 未返回 JSON Wire 响应") from exc
    if not isinstance(response, dict) or set(response) != {
        "systemMessage", "hookSpecificOutput",
    }:
        raise RuntimeError(
            "Codex Hook 返回了宿主不允许的顶层字段；"
            "拒绝继续安装"
        )
    specific = response.get("hookSpecificOutput")
    if not isinstance(specific, dict) or set(specific) != {
        "hookEventName", "permissionDecision", "permissionDecisionReason",
    } or specific.get("hookEventName") != "PreToolUse" or specific.get(
        "permissionDecision"
    ) != "deny":
        raise RuntimeError("Codex Hook 未返回有效的 PreToolUse deny Wire 响应")


def verify_codex_install(release: StagedRelease, development_root: Path) -> None:
    """运行真实 Codex 枚举和插件内 Python，形成安装后来源证明。"""
    source = development_root.resolve()
    marketplace = _default_runner(["codex", "plugin", "marketplace", "list"])
    plugins = _default_runner(["codex", "plugin", "list", "--json"])
    for result, label in ((marketplace, "Marketplace"), (plugins, "Plugin")):
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"{label} 枚举失败: {detail}")
        if str(source) in result.stdout:
            raise RuntimeError(f"{label} 配置仍访问开发目录")
    if str(release.root) not in marketplace.stdout:
        raise RuntimeError("Codex 未注册本次独立 Release Marketplace")

    plugin_root = release.root / "plugins/auto-engineering"
    if str(plugin_root) not in plugins.stdout:
        raise RuntimeError("Codex 插件来源不是本次独立 Release")
    _validate_codex_plugin_build(plugins.stdout, release)
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    environment["CODEX_THREAD_ID"] = "local-install-verification"
    with tempfile.TemporaryDirectory(prefix="ae-install-verify-") as project:
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
            raise RuntimeError(f"独立运行时 doctor 失败: {detail}")
        verify_codex_hook_wire_contract(
            plugin_root=plugin_root,
            project_root=project_root,
            environment=environment,
        )
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
            raise RuntimeError("无法读取插件 Python 模块来源")
        verify_runtime_paths(
            development_root=source,
            marketplace_root=release.root,
            plugin_root=plugin_root,
            runtime_root=runtime_root,
            module_origin=Path(origin.stdout.strip()),
        )
    _seal_release_tree(release.root)


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
        "--ref",
        default=None,
        help="Codex Git Marketplace 的 Git ref；不指定则使用远端默认分支",
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
        if args.ref is not None:
            parser.error("--archive 不能与 --ref 同时使用")
        release = stage_archive(
            args.archive,
            args.staging_root,
            development_root=args.root,
        )
        install_codex_release(release.root, development_root=args.root)
        verify_codex_install(release, args.root)
        payload = {
            "status": "installed",
            "source": str(args.archive.expanduser().resolve()),
            "build_id": release.build_id,
            "release_root": str(release.root),
            "plugin": PLUGIN_ID,
        }
    else:
        install_codex_marketplace(source=args.source, ref=args.ref)
        payload = {
            "status": "installed",
            "source": args.source,
            "ref": args.ref,
            "plugin": PLUGIN_ID,
        }
    print(
        json.dumps(payload, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
