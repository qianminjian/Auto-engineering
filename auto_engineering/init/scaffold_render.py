"""scaffold 阶段辅助函数 — 模板目录选择 + 阶段渲染。

从 scaffold_phases.py 提取（v2.2 Phase I），让 InitWorker 主类保持简短。

模块内容：
- build_template_dirs() : feature → path 映射
- render_to()           : InitWorker._phase_render() 提取的渲染函数
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .config import TEMPLATES_ROOT

if TYPE_CHECKING:
    from .answers import AnswersMap

# language → 模板 feature 子目录映射（来源: Copier _template.py 风格）
_LANG_FEATURE_MAP = {
    "typescript": "typescript",
    "python": "python",
    "go": "go",
    "rust": "rust",
    "bash": "bash",
}

# ci_platform → 模板 feature 子目录映射
_CI_FEATURE_MAP = {
    "github": "github-actions",
    "gitlab": "gitlab-ci",
}

# 渲染阶段需要回填默认空值的 str 变量
_RENDER_STR_VARS = [
    "project_name",
    "project_description",
    "language",
    "package_manager",
    "test_runner",
    "ci_platform",
    "project_type",
]


def build_template_dirs(
    context: dict,
    type_dir: Path,
    subdirectory: str = "",
) -> list[Path]:
    """根据 context 决定要加载的模板目录列表（按优先级排列）。

    拆分自 InitWorker._phase_render() 的模板选择逻辑。

    Args:
        context: AnswersMap.combined() 的渲染上下文
        type_dir: 项目类型对应的模板根目录 (e.g. templates/app-service/)
        subdirectory: 可选子目录（TemplateConfig.subdirectory）

    Returns:
        模板目录列表，按查找顺序排列（_shared → language feature → ... → type_dir）
    """
    template_dirs: list[Path] = [TEMPLATES_ROOT / "_shared"]

    # 1. language → _features/<lang>
    language = context.get("language", "typescript")
    if lang_feat := _LANG_FEATURE_MAP.get(language):
        feat_dir = TEMPLATES_ROOT / "_features" / lang_feat
        if feat_dir.exists():
            template_dirs.append(feat_dir)

    # 2. feature 映射：lefthook / ci_platform / docker / monorepo
    feature_map: dict[str, str] = {"use_lefthook": "lefthook"}
    ci_platform = context.get("ci_platform")
    if ci_platform:
        feature_map[ci_platform] = _CI_FEATURE_MAP.get(ci_platform, "")

    if context.get("use_docker"):
        feature_map["use_docker"] = "docker"
    if context.get("project_type") == "monorepo":
        feature_map["monorepo"] = "monorepo"

    for answer_key, feature_name in feature_map.items():
        if not feature_name:
            continue
        if answer_key == "monorepo" or context.get(answer_key):
            feat_dir = TEMPLATES_ROOT / "_features" / feature_name
            if feat_dir.exists():
                template_dirs.append(feat_dir)

    # 3. type_dir（项目类型主模板，最后追加以获得最高优先级）
    final_type_dir = type_dir / subdirectory if subdirectory else type_dir
    template_dirs.append(final_type_dir)

    return template_dirs


def render_to(
    answers: AnswersMap,
    folder_name: str,
    template_dir: Path,
    subdirectory: str,
    exclude: list[str],
    skip_if_exists: list[str],
    no_render: list[str],
    envops: dict,
    overwrite: bool,
    tmpdir: Path,
    exclude_callback: str = "auto_engineering.init._shared.exclude:default_match_exclude",
) -> list[Path]:
    """Phase 渲染 — 委托给 TemplateRenderer，渲染到 tmpdir。

    拆分自 InitWorker._phase_render()，让 InitWorker 主类保持简短。

    Args:
        answers: InitWorker._answers（duck-typed，需要 .builtins + .combined()）
        folder_name: 目标目录名 (dst_path.name)
        template_dir: 模板根目录
        subdirectory: 可选子目录
        exclude_callback: P1.2 — "module:function" 格式 spec, 渲染阶段动态排除
            来源: Copier _main.py:753 match_exclude
        其他: TemplateRenderer 参数

    Returns:
        生成的文件相对路径列表
    """
    # 回填 builtin 变量（保持向后兼容原 _phase_render 行为）
    answers.builtins["_folder_name"] = folder_name
    for var in _RENDER_STR_VARS:
        if var not in answers:
            answers.builtins[var] = ""
    if "use_typescript" not in answers:
        answers.builtins["use_typescript"] = ""
    if "use_lefthook" not in answers:
        answers.builtins["use_lefthook"] = ""

    context = answers.combined()
    template_dirs = build_template_dirs(
        context=context,
        type_dir=template_dir,
        subdirectory=subdirectory,
    )

    # P1.2: 解析 exclude_callback spec 为可调用对象
    # 解析失败时回退到默认 callback, 避免渲染失败 (优雅降级)
    from ._shared.exclude import default_match_exclude, parse_exclude_callback

    try:
        match_exclude = parse_exclude_callback(exclude_callback)
    except (ValueError, ImportError, AttributeError):
        match_exclude = default_match_exclude

    from .renderer import TemplateRenderer

    renderer = TemplateRenderer(
        template_dirs=template_dirs,
        context=context,
        exclude=exclude,
        skip_if_exists=skip_if_exists,
        no_render=no_render,
        envops=envops,
        overwrite=overwrite,
        match_exclude=match_exclude,
    )
    return renderer.render_to(tmpdir)
