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
        "hooks/hooks.json",
        "hooks/pre-tool.sh",
        "hooks/stop.sh",
        "bin/ae-run",
        "scripts/ae-run",
        "scripts/ae-host-run",
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

_RETIRED_RUNTIME_PATHS = (
    "auto_engineering/host/supervisor.py",
    "auto_engineering/host/invocation.py",
    "auto_engineering/host/request_compiler.py",
    "auto_engineering/host/driver_contract.py",
    "auto_engineering/loop/action-execution-request.schema.json",
    "auto_engineering/loop/action-execution-receipt.schema.json",
)
_CURRENT_RUNTIME_FILES = (
    "auto_engineering/host/stop_report.py",
    "auto_engineering/host/process_exit.py",
    "scripts/collect_product_evidence.py",
)
_RETIRED_RUNTIME_SYMBOLS = ("HOST_SUPERVISOR_PROTOCOL_ERROR",)
_RETIRED_RUNTIME_CONTENT = {
    "from auto_engineering.host.supervisor": "已退役 Supervisor 导入",
    "import auto_engineering.host.supervisor": "已退役 Supervisor 导入",
    "from auto_engineering.host.request_compiler": "已退役 request compiler 导入",
    "import auto_engineering.host.request_compiler": "已退役 request compiler 导入",
    "from auto_engineering.host.driver_contract": "已退役 driver contract 导入",
    "import auto_engineering.host.driver_contract": "已退役 driver contract 导入",
    "from auto_engineering.host.invocation": "已退役 invocation 导入",
    "import auto_engineering.host.invocation": "已退役 invocation 导入",
    "from auto_engineering.host.backends": "已退役嵌套宿主后端导入",
    "import auto_engineering.host.backends": "已退役嵌套宿主后端导入",
    "--supervise": "已退役 Supervisor 命令入口",
}


def _runtime_content_errors(runtime_root: Path) -> list[str]:
    """拒绝旧入口通过改名以外的 import/命令文本重新进入发布树。"""
    errors: list[str] = []
    checker_path = runtime_root / "scripts" / "check_host_package.py"
    for directory in (runtime_root / "auto_engineering", runtime_root / "scripts"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path == checker_path:
                continue
            if path.suffix not in {".py", ".sh", ".json", ".toml"}:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"无法读取运行时内容 {path.relative_to(runtime_root)}: {exc}")
                continue
            for marker, description in _RETIRED_RUNTIME_CONTENT.items():
                if marker in content:
                    errors.append(
                        f"发布资产包含{description}: "
                        f"{path.relative_to(runtime_root)}"
                    )
    return errors


def _retired_runtime_errors(root: Path) -> list[str]:
    errors: list[str] = []
    runtime_roots = [root]
    nested_plugin_root = root / "plugins" / "auto-engineering"
    if nested_plugin_root.is_dir():
        runtime_roots.append(nested_plugin_root)
    for runtime_root in runtime_roots:
        display_root = (
            "plugins/auto-engineering/" if runtime_root == nested_plugin_root else ""
        )
        for relative in _RETIRED_RUNTIME_PATHS:
            if (runtime_root / relative).exists():
                errors.append(
                    f"发布资产包含已退役文件: {display_root}{relative}"
                )
        for relative in _CURRENT_RUNTIME_FILES:
            path = runtime_root / relative
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(
                    f"无法读取宿主运行时边界: {display_root}{relative}: {exc}"
                )
                continue
            for symbol in _RETIRED_RUNTIME_SYMBOLS:
                if symbol in content:
                    errors.append(f"发布资产包含退役运行时符号: {symbol}")
        errors.extend(_runtime_content_errors(runtime_root))
    return errors


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

    errors.extend(_retired_runtime_errors(root))
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
        hook_manifest = json.loads(
            (root / "hooks/hooks.json").read_text(encoding="utf-8")
        )
        stop_hooks = hook_manifest.get("hooks", {}).get("Stop", [])
        if not stop_hooks or "hooks/stop.sh" not in json.dumps(stop_hooks):
            errors.append("Claude Plugin 未注册 Host Runtime StopGuard")
        pre_tool_hooks = hook_manifest.get("hooks", {}).get("PreToolUse", [])
        if not pre_tool_hooks or "hooks/pre-tool.sh" not in json.dumps(pre_tool_hooks):
            errors.append("Claude Plugin 未注册 PreToolUse 安全防护")
        for event_name in ("SessionEnd", "StopFailure"):
            boundary_hooks = hook_manifest.get("hooks", {}).get(event_name, [])
            if not boundary_hooks or "hooks/stop.sh" not in json.dumps(boundary_hooks):
                errors.append(f"Claude Plugin 未注册 Host Runtime {event_name} 边界")
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
