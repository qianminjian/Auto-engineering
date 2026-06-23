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
    ("spec-doc",    ["design/BEACON.md"]),
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
            if any((self.target_dir / sig).exists() for sig in signatures):
                advanced = ADVANCED_CHECKS.get(ptype)
                if advanced and not advanced(self.target_dir):
                    continue
                matches.append(ptype)
        return matches
