"""init/dev-loop 共享契约 — 从 .ae-answers.yml + 代码自检测解析工程环境.

解析流程见 design/v2.0-DESIGN.md §4.5 + design/v2.0-SHARED.md §共享契约.
v2.0 Plan B: 新增 load_ae_answers() 和 preflight() 函数.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import click
import yaml


@dataclass
class ProjectEnvironment:
    """项目工程环境。由 init 写入，dev-loop 消费。"""

    project_name: str = ""
    project_type: str = ""
    package_manager: str = ""
    test_runner: str = ""
    use_typescript: bool = False
    use_lefthook: bool = False
    ci_platform: str | None = None
    has_git: bool = True

    @classmethod
    def resolve_and_persist(cls, project_root: Path) -> ProjectEnvironment:
        """从 .ae-answers.yml + 代码自检测 解析工程环境并持久化。

        注意: 此方法有副作用——会将检测结果写入 .ae-answers.yml。
        若只需查询不写入, 请用 _from_answers_file 或 _from_detection 直接调用。
        """
        answers_file = project_root / ".ae-answers.yml"

        if answers_file.exists():
            env = cls._from_answers_file(answers_file)
            changed = env._sync_detectable(project_root)
            if changed:
                env.save(project_root)
            return env
        else:
            env = cls._from_detection(project_root)
            env.save(project_root)
            return env

    @classmethod
    def _from_answers_file(cls, path: Path) -> ProjectEnvironment:
        data = yaml.safe_load(path.read_text()) or {}
        data.pop("_meta", {})
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def _from_detection(cls, root: Path) -> ProjectEnvironment:
        return cls(
            project_name=root.resolve().name,
            # A7: package_manager 缺检测结果时默认 "npm"
            package_manager=cls._detect_package_manager(root) or "npm",
            test_runner=cls._detect_test_runner(root) or "",
            use_typescript=(root / "tsconfig.json").exists(),
            use_lefthook=(root / "lefthook.yml").exists(),
            ci_platform=cls._detect_ci(root),
            has_git=(root / ".git").exists(),
        )

    @staticmethod
    def _detect_package_manager(root: Path) -> str | None:
        for fname, pm in [
            ("uv.lock", "uv"),
            ("poetry.lock", "poetry"),
            ("pnpm-lock.yaml", "pnpm"),
            ("yarn.lock", "yarn"),
            ("package-lock.json", "npm"),
            ("bun.lock", "bun"),
        ]:
            if (root / fname).exists():
                return pm
        return None

    @staticmethod
    def _detect_test_runner(root: Path) -> str | None:
        for cfg, runner in [
            ("pytest.ini", "pytest"),
            ("pyproject.toml", "pytest"),
            ("vitest.config.ts", "vitest"),
            ("vitest.config.js", "vitest"),
            ("jest.config.ts", "jest"),
            ("jest.config.js", "jest"),
        ]:
            if cfg == "pyproject.toml" and (root / cfg).exists():
                return "pytest"
            if (root / cfg).exists():
                return runner
        return None

    @staticmethod
    def _detect_ci(root: Path) -> str | None:
        if (root / ".github/workflows").exists():
            return "github"
        if (root / ".gitlab-ci.yml").exists():
            return "gitlab"
        return None

    def _sync_detectable(self, root: Path) -> bool:
        """对可判定项执行代码检测，不一致则更新。"""
        changed = False
        detections = {
            "package_manager": self._detect_package_manager(root),
            "test_runner": self._detect_test_runner(root),
            "ci_platform": self._detect_ci(root),
            "use_typescript": (root / "tsconfig.json").exists(),
            "use_lefthook": (root / "lefthook.yml").exists(),
            "has_git": (root / ".git").exists(),
        }
        for field_name, detected in detections.items():
            if detected is not None and getattr(self, field_name) != detected:
                setattr(self, field_name, detected)
                changed = True
        return changed

    def get_undetectable_fields(self, root: Path) -> list[str]:
        """A5: 列出当前无法自动判定的字段 (供 CLI 层 warning 提示).

        Returns:
            不可判定字段名列表 (如 ['package_manager', 'test_runner']).
        """
        undetectable = []
        # 复用检测逻辑 — 若检测结果为 None/False,说明无法判定
        detections = {
            "package_manager": self._detect_package_manager(root),
            "test_runner": self._detect_test_runner(root),
            "ci_platform": self._detect_ci(root),
            "use_typescript": (root / "tsconfig.json").exists() or None,
            "use_lefthook": (root / "lefthook.yml").exists() or None,
            "has_git": (root / ".git").exists() or None,
        }
        for field_name, detected in detections.items():
            if detected is None:
                undetectable.append(field_name)
        return undetectable

    def save(self, project_root: Path) -> None:
        """写回 .ae-answers.yml。"""
        from datetime import datetime

        answers_file = project_root / ".ae-answers.yml"
        data = {
            f.name: getattr(self, f.name)
            for f in self.__dataclass_fields__.values()
            if not f.name.startswith("_")
        }
        if answers_file.exists():
            existing = yaml.safe_load(answers_file.read_text()) or {}
            meta = existing.get("_meta", {})
        else:
            meta = {}
        meta["updated_at"] = datetime.now().isoformat()
        data["_meta"] = meta
        answers_file.write_text(yaml.dump(data, allow_unicode=True))


# ----------------------------------------------------------------------
# v2.0 Plan B 新增: load_ae_answers() + preflight()
# ----------------------------------------------------------------------


def load_ae_answers(project_root: Path) -> dict | None:
    """读取 .ae-answers.yml,返回原始 dict.

    Returns:
        解析后的 dict(含 _meta 子键);文件不存在返回 None;空文件返回 {}.

    Note:
        这是 init/dev-loop 的低级加载函数,不做字段合并/冲突检测。
        字段冲突由 ProjectEnvironment.resolve_and_persist() 处理.
    """
    answers_file = project_root / ".ae-answers.yml"
    if not answers_file.exists():
        return None
    content = answers_file.read_text()
    if not content.strip():
        return {}
    return yaml.safe_load(content) or {}


def preflight(project_root: Path) -> None:
    """入口前置校验 — 检查 git/磁盘/Python 版本.

    任一校验失败抛 SystemExit(1) + 友好 click 错误消息(无 traceback).
    全部通过则静默返回.

    检查项:
        1. Python ≥ 3.12
        2. ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN (或 Plugin mode OAuth)
        3. Git 仓库 (.git 目录存在)
        4. 磁盘可用空间 ≥ 100 MB
    """
    errors: list[str] = []

    # 1. Python 版本
    py_version = sys.version_info
    if (py_version.major, py_version.minor) < (3, 12):
        errors.append(f"Python 版本过低: 当前 {py_version.major}.{py_version.minor}, 需要 ≥ 3.12")

    # 2. ANTHROPIC_API_KEY (或 ANTHROPIC_AUTH_TOKEN for plugin OAuth)
    # 2026-07-04 修复 (prismscan 真实 bug): 用 4 级 fallback detect_plugin_mode
    # 而非 2 级, 支持 CLAUDE_CODE_ENTRYPOINT + ANTHROPIC_AUTH_TOKEN (prismscan 实际 env)
    from auto_engineering.utils.plugin_mode import is_llm_available
    if not is_llm_available():
        errors.append(
            "环境变量 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置。"
            "请在 ~/.zshrc 中 export ANTHROPIC_API_KEY=sk-... 或在 .env 中设置。"
            "Plugin mode (Claude Code agent 内) 应通过 ANTHROPIC_AUTH_TOKEN OAuth 自动注入, 零配置."
        )

    # 3. Git 仓库
    if not (project_root / ".git").exists():
        errors.append(
            f"{project_root} 不是 git 仓库。"
            f"ae dev-loop 需要 git 状态跟踪。请在项目根目录运行 `git init` 后再试。"
        )

    # 4. 磁盘可用空间
    try:
        usage = shutil.disk_usage(project_root)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 100:
            errors.append(
                f"磁盘可用空间不足: {free_mb:.1f} MB < 100 MB。ae 检查点/历史可能占用数十 MB。"
            )
    except OSError as e:
        errors.append(f"无法获取磁盘信息: {e}")

    if errors:
        click.echo("✗ preflight 校验失败:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        raise SystemExit(1)
