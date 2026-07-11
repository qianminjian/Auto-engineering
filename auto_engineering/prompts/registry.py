"""registry.py — B12 中央提示词加载 + 组合 + 版本锁 (v5.6 §B12.4/B12.5).

PromptRegistry 在 Engine `init` 一次性加载 `roles/*.md`, 按 frontmatter 声明
的 `fragments` 顺序把 `fragments/*.md` 追加到正文顶部 (Iron Law/Red Flags/合理化表
前置以最大化遵守), 每个组合后 prompt 算 sha256 写入 checkpoint 供 resume 校验.

设计边界 (§B12.7): 无模板引擎 (简单字符串组合), 无热重载 (仅 init 加载, 保持
Python 门控确定性). frontmatter 用 PyYAML 解析 (已是项目依赖).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

__all__ = ["PromptRegistry", "default_registry"]

# 默认: 本包目录 (auto_engineering/prompts/), 含 roles/ + fragments/ + schema/.
DEFAULT_PROMPTS_DIR = Path(__file__).parent

_DEFAULT_REGISTRY: PromptRegistry | None = None


def default_registry() -> PromptRegistry:
    """进程级单例 (懒加载). Engine A/B 类 prompt 消费者共享一份 (§B12.5 init 加载)."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = PromptRegistry()
    return _DEFAULT_REGISTRY


class PromptRegistry:
    """启动时一次性加载全部 prompt, 组合 fragments, 锁 content hash."""

    def __init__(self, prompts_dir: Path | str | None = None) -> None:
        self._dir = Path(prompts_dir) if prompts_dir else DEFAULT_PROMPTS_DIR
        self._roles: dict[str, str] = {}       # role → 完整 system prompt
        self._hashes: dict[str, str] = {}      # role → sha256(content)
        self._models: dict[str, str] = {}      # role → model id (frontmatter)
        self._schema_template: str = ""        # schema/output_schema_injection.md
        self._load_all(self._dir)

    @property
    def role_names(self) -> list[str]:
        """已加载的 role 名 (排序, 供预检/遍历)."""
        return sorted(self._roles)

    def get(self, role: str) -> str:
        """返回组合后的完整 system prompt (fragments + 正文, frontmatter 已剥离)."""
        self._require(role)
        return self._roles[role]

    def hash(self, role: str) -> str:
        """返回组合后 prompt 的 sha256 (写入 EngineState + checkpoint)."""
        self._require(role)
        return self._hashes[role]

    def registry_hash(self) -> str:
        """全 registry 内容的聚合 sha256 (§B12.5 版本锁).

        对全部 role 按名排序拼接其组合 prompt 再算 sha256 —— 任一 prompt 文件
        变更即改变聚合 hash。Engine init 盖此 hash 入 EngineState, resume 时校验:
        运行中 prompt 被改 → hash 不符 → 警告 (同一 loop 不应换 prompt)。
        """
        joined = "\n".join(f"{r}\x00{self._roles[r]}" for r in sorted(self._roles))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def model(self, role: str) -> str:
        """返回该 role 的 model id (frontmatter 声明, 驱动 Haiku/Sonnet 分层)."""
        self._require(role)
        return self._models[role]

    def schema_injection_template(self) -> str:
        """返回 output_schema 注入模板 (含 `{schema_json}` 占位, base.py 消费).

        B 类片段 (§B12.1): 从 base.py 硬编码抽出到 schema/output_schema_injection.md.
        """
        return self._schema_template

    # ── 内部 ──

    def _require(self, role: str) -> None:
        if role not in self._roles:
            raise KeyError(
                f"未知 role: '{role}' (可用: {self.role_names})")

    def _load_all(self, d: Path) -> None:
        """读 roles/*.md → 解析 frontmatter.fragments → 拼接 fragments/*.md → 存 + hash."""
        fragments = self._load_fragments(d / "fragments")
        schema_file = d / "schema" / "output_schema_injection.md"
        if schema_file.exists():
            self._schema_template = schema_file.read_text(encoding="utf-8").strip()
        roles_dir = d / "roles"
        for role_file in sorted(roles_dir.glob("*.md")):
            meta, body = self._split_frontmatter(role_file)
            role = str(meta.get("role") or role_file.stem)
            frag_names = meta.get("fragments") or []

            parts: list[str] = []
            for fn in frag_names:
                if fn not in fragments:
                    raise ValueError(
                        f"{role_file.name} 声明的 fragment '{fn}' 不存在于 "
                        f"{d / 'fragments'} (可用: {sorted(fragments)})")
                parts.append(fragments[fn])
            parts.append(body)

            # 组合规则: fragments 按声明顺序追加到正文顶部, 段间双换行.
            composed = "\n\n".join(p for p in parts if p).strip() + "\n"
            self._roles[role] = composed
            self._hashes[role] = hashlib.sha256(
                composed.encode("utf-8")).hexdigest()
            self._models[role] = str(meta.get("model", ""))

    @staticmethod
    def _load_fragments(frag_dir: Path) -> dict[str, str]:
        return {
            p.stem: p.read_text(encoding="utf-8").strip()
            for p in frag_dir.glob("*.md")
        }

    @staticmethod
    def _split_frontmatter(path: Path) -> tuple[dict, str]:
        """拆 YAML frontmatter 与正文. 无 frontmatter / 未闭合 → ValueError (fail-fast)."""
        text = path.read_text(encoding="utf-8")
        if not text.lstrip().startswith("---"):
            raise ValueError(f"{path.name} 缺少 YAML frontmatter (--- 开头)")
        # 结构: '---\n<frontmatter>\n---\n<body>' → split 出 3 段.
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"{path.name} frontmatter 未正确闭合 (缺第二个 ---)")
        meta = yaml.safe_load(parts[1]) or {}
        if not isinstance(meta, dict):
            raise ValueError(f"{path.name} frontmatter 不是 YAML 映射")
        return meta, parts[2].strip()
