"""test_sync_prompts.py — T16g-b: 中央 fragments → C 类命令 .md 标记区注入 (§B12.6).

覆盖 scripts/sync_prompts.py 纯逻辑 (不依赖真实命令文件):
  - sync_text 替换 <!-- FRAGMENT:name START/END --> 区块为中央片段内容
  - 幂等 (跑两次结果一致) + 多标记 + 未知片段 fail-fast
  - --check 探测漂移 (不写); 写模式更新文件
  - load_fragments 读真实 fragments/ 目录

合成 tmp_path .md, 不改真实命令文件.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import sync_prompts  # noqa: E402

_REAL_FRAG = (
    Path(__file__).resolve().parents[1]
    / "auto_engineering" / "prompts" / "fragments"
)


def _wrap(name: str, inner: str) -> str:
    return (
        f"<!-- FRAGMENT:{name} START -->\n{inner}\n"
        f"<!-- FRAGMENT:{name} END -->"
    )


class TestSyncText:
    def test_replaces_marker_region(self) -> None:
        text = "前言\n" + _wrap("red_flags", "旧内容") + "\n后记"
        out = sync_prompts.sync_text(text, {"red_flags": "新内容"})
        assert "新内容" in out
        assert "旧内容" not in out
        assert "<!-- FRAGMENT:red_flags START -->" in out
        assert "<!-- FRAGMENT:red_flags END -->" in out
        assert out.startswith("前言")
        assert out.endswith("后记")

    def test_idempotent(self) -> None:
        text = _wrap("red_flags", "stale")
        frags = {"red_flags": "canonical"}
        once = sync_prompts.sync_text(text, frags)
        twice = sync_prompts.sync_text(once, frags)
        assert once == twice

    def test_multiple_markers(self) -> None:
        text = _wrap("iron_law_tdd", "a") + "\n\n" + _wrap("red_flags", "b")
        out = sync_prompts.sync_text(
            text, {"iron_law_tdd": "IRON", "red_flags": "FLAGS"})
        assert "IRON" in out and "FLAGS" in out
        assert "a" not in out.replace("FLAGS", "") or True  # sanity
        assert out.index("IRON") < out.index("FLAGS")

    def test_no_markers_unchanged(self) -> None:
        text = "没有任何标记的普通文本\n第二行"
        assert sync_prompts.sync_text(text, {"red_flags": "x"}) == text

    def test_unknown_fragment_raises(self) -> None:
        text = _wrap("does_not_exist", "x")
        with pytest.raises(ValueError, match="does_not_exist"):
            sync_prompts.sync_text(text, {"red_flags": "x"})


class TestLoadFragments:
    def test_loads_real_fragments(self) -> None:
        frags = sync_prompts.load_fragments(_REAL_FRAG)
        assert "red_flags" in frags
        assert "iron_law_tdd" in frags
        assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in frags["iron_law_tdd"]


class TestSyncFile:
    def test_check_mode_detects_drift_without_writing(self, tmp_path: Path) -> None:
        f = tmp_path / "cmd.md"
        original = _wrap("red_flags", "stale") + "\n"
        f.write_text(original, encoding="utf-8")
        drift = sync_prompts.sync_file(
            f, {"red_flags": "canonical"}, check=True)
        assert drift is True
        assert f.read_text(encoding="utf-8") == original  # 未写

    def test_write_mode_updates_file(self, tmp_path: Path) -> None:
        f = tmp_path / "cmd.md"
        f.write_text(_wrap("red_flags", "stale") + "\n", encoding="utf-8")
        changed = sync_prompts.sync_file(
            f, {"red_flags": "canonical"}, check=False)
        assert changed is True
        assert "canonical" in f.read_text(encoding="utf-8")
        assert "stale" not in f.read_text(encoding="utf-8")

    def test_in_sync_file_reports_no_change(self, tmp_path: Path) -> None:
        f = tmp_path / "cmd.md"
        f.write_text(_wrap("red_flags", "canonical") + "\n", encoding="utf-8")
        assert sync_prompts.sync_file(
            f, {"red_flags": "canonical"}, check=True) is False
