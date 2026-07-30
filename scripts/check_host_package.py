"""校验 Release 解压目录中的宿主适配资产。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HOST_PATHS = {
    "claude-code": (
        ".claude-plugin/plugin.json",
        "CLAUDE.md",
        "commands/dev-loop.md",
        "hooks-cc.json",
        "bin/ae-run",
        "scripts/ae-run",
    ),
    "codex": (
        ".codex-plugin/plugin.json",
        "AGENTS.md",
        "skills/auto-engineering/SKILL.md",
        "hooks-codex.json",
        "bin/ae-run",
        "scripts/ae-run",
    ),
}


def check_host_package(root: Path, host: str) -> list[str]:
    """返回指定宿主发布资产的所有缺口。"""

    if host not in _HOST_PATHS:
        return [f"未知宿主: {host}"]
    root = root.resolve()
    errors = [
        f"缺少 {relative}"
        for relative in _HOST_PATHS[host]
        if not (root / relative).is_file()
    ]
    if errors:
        return errors

    plugin_dir = ".claude-plugin" if host == "claude-code" else ".codex-plugin"
    plugin = json.loads(
        (root / plugin_dir / "plugin.json").read_text(encoding="utf-8")
    )
    if plugin.get("name") != "auto-engineering":
        errors.append(f"{plugin_dir}/plugin.json name 无效")

    if host == "claude-code":
        command = (root / "commands/dev-loop.md").read_text(encoding="utf-8")
        if "ae-run" not in command or "scripts/ae-run" in command:
            errors.append("Claude Command 未使用共享 CLI resolver")
    else:
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        skill = (
            root / "skills/auto-engineering/SKILL.md"
        ).read_text(encoding="utf-8")
        if "@.claude/rules/" in agents:
            errors.append("Codex AGENTS.md 仍依赖 Claude include")
        if (
            "$auto-engineering" not in skill
            or "ae-run" not in skill
            or "scripts/ae-run" in skill
        ):
            errors.append("Codex Skill 缺少入口或共享 CLI resolver")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", choices=sorted(_HOST_PATHS), required=True)
    args = parser.parse_args()

    errors = check_host_package(args.root, args.host)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: {args.host} 发布资产")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
