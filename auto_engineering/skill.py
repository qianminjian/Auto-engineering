"""Agent Skill 入口 — ae init 作为 Claude Code Skill 运行.

用法:
    from auto_engineering.skill import skill
    result = skill("init my-project --type app-service")
    result = skill("analyze /path/to/existing/project")

作为 Claude Code Skill 调用时, skill() 接收自然语言指令,
解析后调用 InitWorker 或 ProjectDetector, 返回结构化结果.

Skill 描述 (用于 Claude Code skill 注册):
    "初始化项目环境: ae init <project> --type <type>
     分析存量项目: ae init --analyze <path>"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillResult:
    """Skill 执行结果。"""

    success: bool
    message: str
    action: str = ""  # "init", "analyze", "detect"
    project_path: str | None = None
    project_type: str | None = None
    candidates: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def skill(prompt: str, cwd: Path | None = None) -> SkillResult:
    """解析 agent prompt 并执行对应的 init 操作。

    Args:
        prompt: agent 的自然语言指令，如 "init my-project --type app-service"
        cwd: 当前工作目录，默认为 Path.cwd()

    Returns:
        SkillResult: 执行结果
    """
    import subprocess

    if cwd is None:
        cwd = Path.cwd()

    # 解析 prompt
    action, project_path, options = _parse_prompt(prompt)

    if action == "analyze":
        return _run_analyze(project_path, cwd)
    elif action == "init":
        return _run_init(project_path, options, cwd)
    elif action == "detect":
        return _run_detect(project_path, cwd)
    else:
        return SkillResult(
            success=False,
            message=f"无法解析指令: {prompt}",
            action="parse",
        )


def _parse_prompt(prompt: str) -> tuple[str, str | None, dict]:
    """解析 prompt 为 action/project_path/options。

    支持的格式:
        "init my-project --type app-service"
        "init /path/to/project --type library"
        "analyze /path/to/project"
        "analyze ."
        "detect ."
        "init my-project"
    """
    prompt = prompt.strip()

    # detect
    detect_match = re.match(r"^detect\s+(.+)$", prompt)
    if detect_match:
        return ("detect", detect_match.group(1).strip(), {})

    # analyze
    analyze_match = re.match(r"^(?:analyze|analyse)\s+(.+)$", prompt)
    if analyze_match:
        return ("analyze", analyze_match.group(1).strip(), {})

    # init
    init_match = re.match(r"^init\s+(.+)$", prompt)
    if init_match:
        args_str = init_match.group(1).strip()
        options = {}
        project_path = None

        # 解析选项
        for opt_match in re.finditer(r"--(\w+)(?:\s+(.+?))?(?=\s+--|\s+|$)", args_str):
            key, val = opt_match.group(1), opt_match.group(2) or "true"
            options[key] = val

        # 剩余的 non-option 是 project path
        parts = args_str.split()
        for part in parts:
            if not part.startswith("--") and part != "true":
                project_path = part
                break

        return ("init", project_path, options)

    return ("unknown", None, {})


def _run_analyze(project_path: str | None, cwd: Path) -> SkillResult:
    """运行存量项目分析。"""
    from auto_engineering.init.detector import ProjectDetector

    target = cwd if project_path in (None, ".") else Path(project_path).expanduser()

    if not target.exists():
        return SkillResult(
            success=False,
            message=f"目录不存在: {target}",
            action="analyze",
        )

    detector = ProjectDetector(target)
    candidates = detector.list_candidates()
    detected = detector.detect()

    if candidates:
        return SkillResult(
            success=True,
            message=f"检测到 {len(candidates)} 个项目类型候选",
            action="analyze",
            project_path=str(target),
            project_type=detected,
            candidates=candidates,
            details={
                "candidates": candidates,
                "detected": detected,
            },
        )
    else:
        return SkillResult(
            success=True,
            message="未检测到已知项目类型",
            action="analyze",
            project_path=str(target),
            candidates=[],
        )


def _run_init(project_path: str | None, options: dict, cwd: Path) -> SkillResult:
    """运行项目初始化。"""
    from auto_engineering.init import InitWorker

    dst_path = cwd if project_path in (None, ".") else Path(project_path).expanduser()

    # 构建 CLI 参数
    kwargs = {}
    for key, val in options.items():
        # 转换 CLI 选项名到 InitWorker 参数名
        param_map = {
            "type": "project_type",
            "package-manager": "package_manager",
            "ci": "ci_platform",
            "test-runner": "test_runner",
            "no-typescript": "use_typescript",
            "no-lefthook": "use_lefthook",
            "defaults": "defaults",
            "force": "force",
            "quiet": "quiet",
            "incremental": "incremental",
        }
        if key in param_map:
            param = param_map[key]
            if val == "true":
                kwargs[param] = True
            elif val not in ("true", "false"):
                kwargs[param] = val

    try:
        worker = InitWorker(dst_path=dst_path, **kwargs)
        result = worker.execute()
        return SkillResult(
            success=True,
            message=f"项目已初始化: {result.dst_path}",
            action="init",
            project_path=str(result.dst_path),
            project_type=result.project_type,
            details={"files_count": len(result.files)},
        )
    except Exception as e:
        return SkillResult(
            success=False,
            message=f"初始化失败: {e}",
            action="init",
            project_path=str(dst_path),
        )


def _run_detect(project_path: str | None, cwd: Path) -> SkillResult:
    """运行项目类型检测（不初始化）。"""
    return _run_analyze(project_path, cwd)


# Claude Code Skill 入口点
# 当作为 Skill 调用时, Claude Code 会调用 skill() 函数
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        result = skill(" ".join(sys.argv[1:]))
        print(result.message)
        sys.exit(0 if result.success else 1)
    else:
        print("Usage: python -m auto_engineering.skill <command>")
        print("  analyze <path>  - 分析存量项目")
        print("  detect <path>  - 检测项目类型")
        print("  init <project> [--type <type>] - 初始化新项目")
