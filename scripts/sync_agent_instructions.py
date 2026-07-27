"""从单一模板生成 CLAUDE.md 与 AGENTS.md。

写模式会修复生成文件；``--check`` 只报告漂移，供 CI 使用。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_RELATIVE = Path("agent-rules/instructions.md.tmpl")
_GENERATED_HEADER = """<!--
此文件由 agent-rules/ 公共模板与平台适配模板自动生成，请勿直接修改。
修改模板后运行：python3 scripts/sync_agent_instructions.py
-->

"""
_PLATFORM_VALUES = {
    "CLAUDE.md": {
        "INSTRUCTION_FILE": "CLAUDE.md",
        "AGENT_NAME": "Claude Code",
        "AGENT_SITE": "claude.ai/code",
        "PLUGIN_DIR": ".claude-plugin/",
        "RULES_DIR": ".claude/rules/",
        "ADAPTER_TEMPLATE": "agent-rules/claude.md.tmpl",
    },
    "AGENTS.md": {
        "INSTRUCTION_FILE": "AGENTS.md",
        "AGENT_NAME": "Codex",
        "AGENT_SITE": "Codex.ai/code",
        "PLUGIN_DIR": ".codex-plugin/",
        # Codex 通过 AGENTS.md 显式读取项目已有的共享规则目录。
        "RULES_DIR": ".claude/rules/",
        "ADAPTER_TEMPLATE": "agent-rules/codex.md.tmpl",
    },
}
_PLACEHOLDER = re.compile(r"{{\s*([A-Z][A-Z0-9_]*)\s*}}")


def render_template(template: str, variables: dict[str, str]) -> str:
    """替换平台变量；未知变量立即失败，防止生成半成品。"""

    unknown = sorted(set(_PLACEHOLDER.findall(template)) - variables.keys())
    if unknown:
        raise ValueError(f"未知模板变量: {', '.join(unknown)}")

    rendered = template
    for name, value in variables.items():
        rendered = rendered.replace(f"{{{{{name}}}}}", value)

    unresolved = sorted(set(_PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise ValueError(f"未解析模板变量: {', '.join(unresolved)}")
    return _GENERATED_HEADER + rendered


def sync_instructions(root: Path, *, check: bool = False) -> list[Path]:
    """同步两个生成文件，返回发生漂移的目标路径。"""

    root = root.resolve()
    template = (root / _TEMPLATE_RELATIVE).read_text(encoding="utf-8")
    changed: list[Path] = []
    for filename, variables in _PLATFORM_VALUES.items():
        target = root / filename
        adapter_path = root / variables["ADAPTER_TEMPLATE"]
        adapter = adapter_path.read_text(encoding="utf-8")
        content = render_template(
            template.rstrip() + "\n\n" + adapter.lstrip(),
            variables,
        )
        if write_generated_file(
            root=root,
            target=target,
            content=content,
            check=check,
        ):
            changed.append(target)
    return changed


def write_generated_file(
    *, root: Path, target: Path, content: str, check: bool
) -> bool:
    """只允许原子写项目根目录的两个生成目标。"""

    root = root.resolve()
    target = target.absolute()
    allowed_names = set(_PLATFORM_VALUES)
    if (
        target.name not in allowed_names
        or target.parent.resolve() != root
        or target.is_symlink()
    ):
        raise ValueError(f"不允许的生成目标: {target}")

    current = target.read_text(encoding="utf-8") if target.exists() else None
    if current == content:
        return False
    if check:
        return True

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=root,
        prefix=f".{target.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查生成文件是否漂移，不写文件",
    )
    args = parser.parse_args(argv)
    project_root = (root or _ROOT).resolve()

    try:
        changed = sync_instructions(project_root, check=args.check)
    except (OSError, ValueError) as error:
        print(f"同步失败: {error}", file=sys.stderr)
        return 2

    changed_set = set(changed)
    for filename in _PLATFORM_VALUES:
        target = project_root / filename
        if target in changed_set:
            print(f"{'DRIFT' if args.check else '更新'}: {filename}")
        else:
            print(f"OK: {filename}")

    if args.check and changed:
        print(
            "生成文件与模板不一致，请运行 "
            "`python3 scripts/sync_agent_instructions.py` 修复",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
