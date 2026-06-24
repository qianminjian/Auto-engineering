"""ProjectDetector — 项目类型自动检测（SST 模式）.

来源：SST 框架扫描 — 通过已知配置文件签名推断项目类型。
"""

import json
from collections.abc import Callable
from pathlib import Path

# 签名顺序很重要：更具体的签名应排在前面（monorepo > app-service）
FRAMEWORK_SIGNATURES: list[tuple[str, list[str]]] = [
    ("monorepo",    ["pnpm-workspace.yaml", "lerna.json", "turbo.json", "nx.json"]),
    ("skill",       [".claude/skills/"]),
    ("hook",        [".claude/hooks/"]),
    # A6: spec-doc 支持 design/*.md glob (任意 design 文档)
    ("spec-doc",    ["design/BEACON.md", "design/*.md"]),
    ("mcp-server",  ["package.json"]),
    ("cli-tool",    ["package.json"]),
    ("library",     ["pyproject.toml", "setup.py", "Cargo.toml", "go.mod"]),
    ("app-service", ["package.json"]),
]


def _check_package_json(target_dir: Path, check_fn: Callable[[dict], bool]) -> bool:
    pkg = target_dir / "package.json"
    if not pkg.exists():
        return False
    try:
        data = json.loads(pkg.read_text())
        return check_fn(data)
    except (json.JSONDecodeError, KeyError):
        return False


ADVANCED_CHECKS: dict[str, Callable[[Path], bool]] = {
    "mcp-server": lambda d: _check_package_json(
        d, lambda p: "@modelcontextprotocol/sdk" in str(p.get("dependencies", {}))
    ),
    "cli-tool": lambda d: _check_package_json(d, lambda p: "bin" in p),
}


class ProjectDetector:
    """扫描目标目录，推断项目类型。"""

    def __init__(self, target_dir: Path):
        self.target_dir = target_dir

    def detect(self) -> str | None:
        """返回唯一匹配的项目类型，0 或多于 1 个匹配返回 None。"""
        candidates = self.list_candidates()
        if len(candidates) == 1:
            return candidates[0]
        return None

    def list_candidates(self) -> list[str]:
        """返回所有匹配的项目类型列表。"""
        matches = []
        for ptype, signatures in FRAMEWORK_SIGNATURES:
            if any(_signature_matches(self.target_dir, sig) for sig in signatures):
                advanced = ADVANCED_CHECKS.get(ptype)
                if advanced and not advanced(self.target_dir):
                    continue
                matches.append(ptype)
        return matches


def _signature_matches(target_dir: Path, sig: str) -> bool:
    """A6: 检查签名是否匹配 — 支持 glob 通配符 (*.md 等)."""
    # 目录签名以 / 结尾: 直接 exists()
    if sig.endswith("/"):
        return (target_dir / sig).exists()
    # glob 通配符: 用 fnmatch 判断文件名部分
    if "*" in sig or "?" in sig or "[" in sig:
        import fnmatch
        rel_dir = sig.rsplit("/", 1)[0] if "/" in sig else ""
        pattern = sig.rsplit("/", 1)[-1]
        base = target_dir / rel_dir if rel_dir else target_dir
        if not base.exists():
            return False
        for entry in base.iterdir():
            if entry.is_file() and fnmatch.fnmatch(entry.name, pattern):
                return True
        return False
    # 普通文件签名
    return (target_dir / sig).exists()
