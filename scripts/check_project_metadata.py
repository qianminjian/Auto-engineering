"""检查版本与测试基线是否和 pyproject.toml 唯一事实源一致。"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def check_metadata(root: Path) -> list[str]:
    """返回所有元数据漂移；空列表表示一致。"""

    root = root.resolve()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(project["project"]["version"])
    baseline = project["tool"]["auto-engineering"]["baseline"]
    project_metadata = project["project"]
    passed = int(baseline["passed"])
    skipped = int(baseline["skipped"])
    errors: list[str] = []

    dependencies = project_metadata.get("dependencies", [])
    optional_dependencies = project_metadata.get("optional-dependencies", {})
    if any(str(item).startswith("anthropic") for item in dependencies):
        errors.append("pyproject.toml 依赖漂移: anthropic 必须是可选 Provider")
    if not any(
        str(item).startswith("anthropic")
        for item in optional_dependencies.get("anthropic", [])
    ):
        errors.append("pyproject.toml 依赖漂移: 缺少 anthropic 可选 Provider")

    plugin_paths = (
        Path(".claude-plugin/plugin.json"),
        Path(".codex-plugin/plugin.json"),
    )
    for relative in plugin_paths:
        data = _load_json(root / relative)
        actual = data.get("version") if isinstance(data, dict) else None
        if actual != version:
            errors.append(
                f"{relative} 版本漂移: 期望 {version}，实际 {actual!r}"
            )
        if not isinstance(data, dict):
            continue
        if "anthropic" in json.dumps(data).lower():
            errors.append(f"{relative} metadata 不得绑定 Anthropic 品牌")
        metadata = data.get("metadata")
        if (
            relative == Path(".claude-plugin/plugin.json")
            and isinstance(metadata, dict)
            and metadata.get("env")
        ):
            errors.append(
                ".claude-plugin/plugin.json metadata.env 已废弃；"
                "运行配置必须来自 FeatureManifest"
            )
        if (
            relative == Path(".codex-plugin/plugin.json")
            and data.get("commands")
        ):
            errors.append(
                ".codex-plugin/plugin.json 不得声明 Codex 不支持的 commands"
            )

    marketplace_path = root / ".claude-plugin/marketplace.json"
    marketplace = _load_json(marketplace_path)
    if not isinstance(marketplace, dict):
        errors.append(".claude-plugin/marketplace.json 格式错误")
    else:
        marketplace_versions = [
            marketplace.get("metadata", {}).get("version"),
            *[
                plugin.get("version")
                for plugin in marketplace.get("plugins", [])
                if isinstance(plugin, dict)
            ],
        ]
        if any(item != version for item in marketplace_versions):
            errors.append(
                ".claude-plugin/marketplace.json 版本漂移: "
                f"期望所有版本为 {version}"
            )

    readme = (root / "README.md").read_text(encoding="utf-8")
    if not re.search(
        rf"^# Auto-Engineering v{re.escape(version)}$", readme, re.MULTILINE
    ):
        errors.append(f"README.md 版本漂移: 期望标题 v{version}")
    baseline_marker = f"<!-- test-baseline --> {passed} passed / {skipped} skipped"
    if baseline_marker not in readme:
        errors.append(
            f"README.md 测试基线漂移: 期望 {passed} passed / {skipped} skipped"
        )
    return errors


def main(*, root: Path | None = None) -> int:
    errors = check_metadata(root or _ROOT)
    if errors:
        for error in errors:
            print(f"DRIFT: {error}", file=sys.stderr)
        return 1
    print("OK: 项目版本与测试基线一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
