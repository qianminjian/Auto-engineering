"""从自包含 Release 安装 Codex 插件，禁止运行态依赖开发目录。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scripts.build_release import _release_content_digest, build_archive
from scripts.install_acceptance import _safe_extract_archive

PLUGIN_ID = "auto-engineering@auto-engineering"
MARKETPLACE_NAME = "auto-engineering"


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


def _read_build_info(root: Path) -> StagedRelease:
    payload = json.loads((root / "build-info.json").read_text(encoding="utf-8"))
    required = ("version", "build_id", "content_sha256")
    if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
        raise RuntimeError("Release build-info.json 不完整")
    return StagedRelease(
        root=root.resolve(),
        version=payload["version"],
        build_id=payload["build_id"],
        content_sha256=payload["content_sha256"],
    )


def _verify_staged_release(root: Path) -> StagedRelease:
    release = _read_build_info(root)
    release_paths = (
        path
        for path in root.rglob("*")
        if ".ae-runtime" not in path.relative_to(root).parts
    )
    if any(path.is_symlink() for path in release_paths):
        raise RuntimeError("Release 暂存目录不得包含符号链接")
    actual_digest = _release_content_digest(root)
    if actual_digest != release.content_sha256:
        raise RuntimeError("Release 内容摘要与 build-info.json 不一致")
    return release


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
        release = _verify_staged_release(extracted)
        final_root = destination_parent / release.build_id
        if final_root.exists():
            existing = _verify_staged_release(final_root)
            if existing.content_sha256 != release.content_sha256:
                raise RuntimeError("同 build_id 的已暂存 Release 内容不一致")
            return existing
        os.replace(extracted, final_root)
    return _verify_staged_release(final_root)


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


def verify_runtime_paths(
    *,
    development_root: Path,
    marketplace_root: Path,
    plugin_root: Path,
    module_origin: Path,
    launcher_shebang: str,
) -> None:
    """验证 Marketplace、插件、Python 模块与入口均不引用开发目录。"""
    source = development_root.resolve()
    candidates = {
        "Marketplace": marketplace_root,
        "插件": plugin_root,
        "Python 模块": module_origin,
    }
    leaked = [name for name, path in candidates.items() if _is_within(path, source)]
    if str(source) in launcher_shebang:
        leaked.append("启动器 shebang")
    if leaked:
        raise RuntimeError("运行态仍访问开发目录: " + ", ".join(leaked))
    if not _is_within(module_origin, plugin_root):
        raise RuntimeError("Python 模块来源不属于已安装插件")
    runtime_root = (plugin_root / ".ae-runtime").resolve()
    if f"{runtime_root}/bin/python" not in launcher_shebang:
        raise RuntimeError("启动器未绑定插件独立运行时")


def verify_codex_install(release: StagedRelease, development_root: Path) -> None:
    """运行真实 Codex 枚举和插件内 Python，形成安装后来源证明。"""
    source = development_root.resolve()
    marketplace = _default_runner(["codex", "plugin", "marketplace", "list"])
    plugins = _default_runner(["codex", "plugin", "list"])
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
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    environment["CODEX_THREAD_ID"] = "local-install-verification"
    environment["AE_SKIP_CONFIG_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="ae-install-verify-") as project:
        (Path(project) / ".ae-state").mkdir()
        doctor = subprocess.run(
            [str(plugin_root / "bin/ae-run"), "doctor", "--project-root", project],
            cwd=project,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if doctor.returncode != 0:
            detail = doctor.stderr.strip() or doctor.stdout.strip()
            raise RuntimeError(f"独立运行时 doctor 失败: {detail}")

    runtime_python = plugin_root / ".ae-runtime/bin/python"
    origin = subprocess.run(
        [
            str(runtime_python),
            "-c",
            "import auto_engineering; print(auto_engineering.__file__)",
        ],
        cwd=plugin_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if origin.returncode != 0:
        raise RuntimeError("无法读取插件 Python 模块来源")
    module_origin = Path(origin.stdout.strip())
    launcher = (plugin_root / ".ae-runtime/bin/ae").read_text(encoding="utf-8")
    verify_runtime_paths(
        development_root=source,
        marketplace_root=release.root,
        plugin_root=plugin_root,
        module_origin=module_origin,
        launcher_shebang=launcher,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=Path.home() / ".local/share/auto-engineering/releases",
    )
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()

    release = stage_release(args.root, args.staging_root)
    if not args.stage_only:
        install_codex_release(release.root, development_root=args.root)
        verify_codex_install(release, args.root)
    print(
        json.dumps(
            {
                "status": "staged" if args.stage_only else "installed",
                "version": release.version,
                "build_id": release.build_id,
                "release_root": str(release.root),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
