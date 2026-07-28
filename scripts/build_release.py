"""构建并校验 Auto-Engineering 跨宿主 Release 压缩包。"""

from __future__ import annotations

import argparse
import io
import json
import tarfile
from pathlib import Path

REQUIRED_PATHS = (
    Path(".claude-plugin/plugin.json"),
    Path(".codex-plugin/plugin.json"),
    Path(".codex/hooks.json"),
    Path("hooks-cc.json"),
    Path("hooks-codex.json"),
    Path("hooks-codebuddy.json"),
    Path("commands"),
    Path("skills"),
    Path("hooks"),
    Path("scripts/ae-run"),
    Path("scripts/build_release.py"),
    Path("scripts/check_host_package.py"),
    Path("scripts/install_acceptance.py"),
    Path("auto_engineering"),
    Path("pyproject.toml"),
    Path("README.md"),
    Path("CLAUDE.md"),
    Path("AGENTS.md"),
    Path("LICENSE"),
)

_PLUGIN_ROOT = Path("plugins/auto-engineering")

_EXCLUDED_PARTS = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
})


def _archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """排除缓存、字节码和本地元数据。"""
    path = Path(info.name)
    if any(part in _EXCLUDED_PARTS for part in path.parts):
        return None
    if path.name.endswith((".pyc", ".pyo")) or path.name == ".DS_Store":
        return None
    return info


def _add_json(
    package: tarfile.TarFile,
    path: Path,
    payload: dict[str, object],
) -> None:
    """把确定性 JSON 资产写入 archive，不依赖本地 staging 目录。"""
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    info = tarfile.TarInfo(path.as_posix())
    info.size = len(content)
    info.mode = 0o644
    package.addfile(info, io.BytesIO(content))


def _marketplace_manifests(root: Path) -> tuple[dict[str, object], dict[str, object]]:
    """生成指向 archive 内自包含插件目录的双宿主 marketplace manifest."""
    claude = json.loads(
        (root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    claude["description"] = "Auto-Engineering 双宿主确定性工程治理内核"
    claude["plugins"][0]["source"] = f"./{_PLUGIN_ROOT.as_posix()}"

    plugin = json.loads(
        (root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    codex = {
        "name": "auto-engineering",
        "interface": {"displayName": "Auto-Engineering"},
        "plugins": [
            {
                "name": plugin["name"],
                "source": {
                    "source": "local",
                    "path": f"./{_PLUGIN_ROOT.as_posix()}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_USE",
                },
                "category": "Engineering",
            }
        ],
    }
    return claude, codex


def build_archive(root: Path, output: Path) -> Path:
    """校验必需资产后构建 tar.gz；任何缺失都 fail-fast。"""
    resolved_root = root.resolve()
    missing = [
        path.as_posix()
        for path in REQUIRED_PATHS
        if not (resolved_root / path).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Release 必需路径缺失: " + ", ".join(missing)
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as package:
        for relative in REQUIRED_PATHS:
            package.add(
                resolved_root / relative,
                arcname=relative.as_posix(),
                recursive=True,
                filter=_archive_filter,
            )
            package.add(
                resolved_root / relative,
                arcname=(_PLUGIN_ROOT / relative).as_posix(),
                recursive=True,
                filter=_archive_filter,
            )
        claude_marketplace, codex_marketplace = _marketplace_manifests(resolved_root)
        _add_json(
            package,
            Path(".claude-plugin/marketplace.json"),
            claude_marketplace,
        )
        _add_json(
            package,
            Path(".agents/plugins/marketplace.json"),
            codex_marketplace,
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    archive = build_archive(args.root, args.output)
    print(f"Release 包已生成: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
