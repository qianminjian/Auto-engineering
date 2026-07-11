"""sync_prompts.py — 中央 fragments/*.md → C 类命令 .md 标记区注入 (v5.6 §B12.6).

C 类命令/技能 .md 必须留在 `.claude-plugin/commands/` 与 `skills/`（Claude Code
发现机制的结构约束，见 §B12.2），其与 Agent system prompt 共享的行为塑形片段
（Red Flags / Iron Law）不手抄，由本脚本从 `prompts/fragments/` 注入标记区，
保证单一源、不漂移：

    <!-- FRAGMENT:red_flags START -->
    （由 sync_prompts.py 从 prompts/fragments/red_flags.md 注入，勿手改）
    <!-- FRAGMENT:red_flags END -->

用法::

    python scripts/sync_prompts.py            # 写入：注入/更新所有标记区
    python scripts/sync_prompts.py --check     # 仅校验：有漂移则 exit 1（CI/pre-commit）

注：pre-commit / CI 接线（`.pre-commit-config.yaml` / `.github/workflows`）属 CI/CD
配置变更，需用户显式授权后再加，本脚本只提供 `--check` 供接线消费。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 项目根 = 本文件上一级的上一级 (scripts/ 的父).
_ROOT = Path(__file__).resolve().parents[1]
_FRAG_DIR = _ROOT / "auto_engineering" / "prompts" / "fragments"

# C 类文件候选位置 (只处理含 FRAGMENT 标记的文件).
_TARGET_GLOBS = (
    ".claude-plugin/commands/*.md",
    "commands/*.md",
    "skills/**/*.md",
)

# <!-- FRAGMENT:name START --> ... <!-- FRAGMENT:name END --> (跨行, 回引组名闭合).
_MARKER = re.compile(
    r"<!-- FRAGMENT:([\w-]+) START -->.*?<!-- FRAGMENT:\1 END -->",
    re.DOTALL,
)


def load_fragments(frag_dir: Path = _FRAG_DIR) -> dict[str, str]:
    """读 fragments/*.md → {stem: 内容(strip)}."""
    return {
        p.stem: p.read_text(encoding="utf-8").strip()
        for p in frag_dir.glob("*.md")
    }


def sync_text(text: str, fragments: dict[str, str]) -> str:
    """把 text 中每个 FRAGMENT 标记区替换为中央片段内容 (幂等).

    标记引用未知片段 → ValueError (fail-fast, 避免静默漏注入).
    """

    def _repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in fragments:
            raise ValueError(
                f"标记引用未知 fragment '{name}' (fragments/ 无 {name}.md; "
                f"可用: {sorted(fragments)})")
        return (
            f"<!-- FRAGMENT:{name} START -->\n{fragments[name]}\n"
            f"<!-- FRAGMENT:{name} END -->"
        )

    return _MARKER.sub(_repl, text)


def sync_file(path: Path, fragments: dict[str, str], *, check: bool) -> bool:
    """同步单文件. check=True 只探测漂移 (不写).

    Returns:
        写模式: True=文件被更新; 校验模式: True=存在漂移 (需重新 sync).
    """
    original = path.read_text(encoding="utf-8")
    updated = sync_text(original, fragments)
    if updated == original:
        return False
    if not check:
        path.write_text(updated, encoding="utf-8")
    return True


def discover_targets(root: Path = _ROOT) -> list[Path]:
    """扫描候选位置, 只返回真正含 FRAGMENT 标记的 .md."""
    found: list[Path] = []
    for pattern in _TARGET_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and "<!-- FRAGMENT:" in p.read_text(encoding="utf-8"):
                found.append(p)
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="仅校验标记区是否与中央片段一致 (有漂移则 exit 1)")
    args = parser.parse_args(argv)

    fragments = load_fragments()
    targets = discover_targets()
    if not targets:
        print("无含 FRAGMENT 标记的 C 类文件 (标记由 W2.5 T16d 加入)")
        return 0

    drifted: list[Path] = []
    for path in targets:
        changed = sync_file(path, fragments, check=args.check)
        rel = path.relative_to(_ROOT)
        if changed:
            drifted.append(path)
            print(f"{'DRIFT' if args.check else '更新'}: {rel}")
        else:
            print(f"OK: {rel}")

    if args.check and drifted:
        print(f"\n{len(drifted)} 个文件标记区与中央片段漂移, 运行 "
              f"`python scripts/sync_prompts.py` 修复", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
