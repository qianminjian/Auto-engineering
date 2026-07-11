"""test_prompt_registry.py — T16e: B12 中央提示词 PromptRegistry (v5.6 §B12.4/B12.5).

覆盖:
  - 加载 roles/*.md 全部 9 role, 解析 frontmatter (role/model/fragments)
  - 组合: fragments 按声明顺序追加到正文顶部 (Iron Law/合理化表前置)
  - frontmatter 从 get() 输出剥离
  - sha256 版本锁: hash(role) == sha256(get(role)), 确定性可复现
  - model(role) 从 frontmatter 取值 (Haiku/Sonnet 分层)
  - 未知 role → KeyError; fragment 引用缺失/无 frontmatter → ValueError (fail-fast)

真实 prompts 目录 + 合成 tmp_path 边界目录, 不调 LLM/网络.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from auto_engineering.prompts.registry import PromptRegistry

_REAL_DIR = Path(__file__).resolve().parents[1] / "auto_engineering" / "prompts"

_ALL_ROLES = {
    "architect", "developer", "critic",
    "component_verifier", "plate_deep_audit",
    "system_verifier", "system_deep_audit",
    "gap_scan", "research",
}


@pytest.fixture
def registry() -> PromptRegistry:
    return PromptRegistry(_REAL_DIR)


class TestLoad:
    def test_loads_all_nine_roles(self, registry: PromptRegistry) -> None:
        assert set(registry.role_names) == _ALL_ROLES

    def test_default_dir_is_package_dir(self) -> None:
        # 无参数 → 默认包内 prompts 目录, 同样加载 9 role
        reg = PromptRegistry()
        assert set(reg.role_names) == _ALL_ROLES


class TestCompose:
    def test_developer_includes_fragments_and_body(self, registry: PromptRegistry) -> None:
        p = registry.get("developer")
        # iron_law_tdd
        assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" in p
        # rationalization_developer
        assert "RED 只花 30 秒" in p
        # letter_vs_spirit
        assert "违反规则的字面就是违反规则的精神" in p
        # body
        assert "你是 Auto-Engineering 的开发者" in p

    def test_fragments_prepended_in_declared_order(self, registry: PromptRegistry) -> None:
        p = registry.get("developer")
        # frontmatter: [iron_law_tdd, rationalization_developer, letter_vs_spirit]
        i_iron = p.index("NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST")
        i_rat = p.index("RED 只花 30 秒")
        i_letter = p.index("违反规则的字面就是违反规则的精神")
        i_body = p.index("你是 Auto-Engineering 的开发者")
        assert i_iron < i_rat < i_letter < i_body

    def test_frontmatter_stripped_from_output(self, registry: PromptRegistry) -> None:
        p = registry.get("developer")
        assert "role: developer" not in p
        assert "fragments:" not in p
        assert not p.lstrip().startswith("---")

    def test_single_fragment_role(self, registry: PromptRegistry) -> None:
        # gap_scan 只声明 letter_vs_spirit, 不含 TDD iron law
        p = registry.get("gap_scan")
        assert "违反规则的字面就是违反规则的精神" in p
        assert "设计模糊性扫描者" in p
        assert "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST" not in p


class TestHash:
    def test_hash_is_sha256_hex(self, registry: PromptRegistry) -> None:
        h = registry.hash("developer")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_matches_get_content(self, registry: PromptRegistry) -> None:
        expected = hashlib.sha256(
            registry.get("developer").encode("utf-8")).hexdigest()
        assert registry.hash("developer") == expected

    def test_hash_deterministic_across_instances(self) -> None:
        h1 = PromptRegistry(_REAL_DIR).hash("critic")
        h2 = PromptRegistry(_REAL_DIR).hash("critic")
        assert h1 == h2


class TestModel:
    def test_haiku_for_component_verifier(self, registry: PromptRegistry) -> None:
        assert registry.model("component_verifier") == "claude-haiku-4-5-20251001"

    def test_haiku_for_system_verifier(self, registry: PromptRegistry) -> None:
        assert registry.model("system_verifier") == "claude-haiku-4-5-20251001"

    def test_sonnet_for_developer(self, registry: PromptRegistry) -> None:
        assert registry.model("developer") == "claude-sonnet-4-6"


class TestErrors:
    def test_unknown_role_get_raises_keyerror(self, registry: PromptRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_unknown_role_hash_raises_keyerror(self, registry: PromptRegistry) -> None:
        with pytest.raises(KeyError):
            registry.hash("nonexistent")

    def test_missing_fragment_ref_raises_valueerror(self, tmp_path: Path) -> None:
        _make_min_dir(tmp_path, role_fm="fragments: [does_not_exist]")
        with pytest.raises(ValueError, match="fragment"):
            PromptRegistry(tmp_path)

    def test_role_without_frontmatter_raises_valueerror(self, tmp_path: Path) -> None:
        (tmp_path / "fragments").mkdir()
        roles = tmp_path / "roles"
        roles.mkdir()
        (roles / "bad.md").write_text("no frontmatter here", encoding="utf-8")
        with pytest.raises(ValueError, match="frontmatter"):
            PromptRegistry(tmp_path)


def _make_min_dir(base: Path, *, role_fm: str) -> None:
    """构造最小 prompts 目录: 1 role (带给定 frontmatter) + 空 fragments."""
    (base / "fragments").mkdir()
    roles = base / "roles"
    roles.mkdir()
    (roles / "x.md").write_text(
        f"---\nrole: x\nmodel: m\n{role_fm}\n---\nbody text\n",
        encoding="utf-8",
    )
