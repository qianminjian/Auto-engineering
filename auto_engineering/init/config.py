"""ae-template.yml 解析 — TemplateConfig dataclass + 加载入口。

参考来源：
- copier/_template.py:60-299  — filter_config() + load_template_config() + !include
- copier/_user_data.py:136-295 — Question dataclass 定义

接口：load_ae_template(project_type: str) -> TemplateConfig

模块结构（v2.2 Phase I 拆分后）：
- config_types.py  : Question / Task dataclass + 共享常量
- config_loader.py : YAML 解析流水线（!include / nested / questions / tasks）
- config.py        : TemplateConfig dataclass + .load() 入口

模板目录结构约定：
  templates/<type>/ae-template.yml          ← 问题+钩子定义
  templates/<type>/**/*.jinja               ← 模板文件
  templates/_shared/                        ← 所有类型共享的基础文件
  templates/_features/<feature>/            ← 可组合功能模块
"""

from dataclasses import dataclass, field
from pathlib import Path

from .config_loader import load_template_config
from .config_types import (
    DEFAULT_EXCLUDE,
    DEFAULT_TEMPLATES_SUFFIX,
    TEMPLATES_ROOT,
    Question,
    Task,
)

# 重新导出公共符号,保持旧路径 from init.config import ... 可工作
__all__ = [
    "DEFAULT_EXCLUDE",
    "DEFAULT_TEMPLATES_SUFFIX",
    "TEMPLATES_ROOT",
    "Question",
    "Task",
    "TemplateConfig",
]


# ─── TemplateConfig ────────────────────────────────────────────────────────────


@dataclass
class TemplateConfig:
    """从 ae-template.yml 解析的完整模板配置。

    参考 Copier _template.py:192-299 Template dataclass。

    ae-template.yml 约定：
    - _ 前缀字段映射到 TemplateConfig 属性（去 _ 前缀后）
    - 其余字段解析为 Question 列表
    """

    template_dir: Path
    min_ae_version: str = "1.0.0"
    templates_suffix: str = DEFAULT_TEMPLATES_SUFFIX
    # T2-5: preserve_symlinks 可配置 — True 保留 symlink; False 跳过 dangling 或解析内容
    # 来源: Copier _main.py + cookiecutter generate.py symlink 处理
    preserve_symlinks: bool = True
    exclude: list[str] = field(default_factory=lambda: DEFAULT_EXCLUDE.copy())
    skip_if_exists: list[str] = field(default_factory=list)

    # P1.2: exclude_callback — module:function 格式 spec, 渲染阶段动态排除路径
    # （来源: Copier _main.py:753 match_exclude Callable[[Path], bool]）
    # 默认指向 _shared.exclude.default_match_exclude
    exclude_callback: str = (
        "auto_engineering.init._shared.exclude:default_match_exclude"
    )

    # P1#7: _envops — Jinja2 环境选项（来源: Copier copier.yaml _envops）
    envops: dict = field(
        default_factory=lambda: {
            "autoescape": False,
            "keep_trailing_newline": True,
        }
    )

    # P1#6: _copy_without_render — 标记文件不渲染只复制
    # （来源: Cookiecutter generate.py:39-56）
    no_render: list[str] = field(default_factory=list)

    # P2#15: _subdirectory — 模板子目录（来源: Copier Template._subdirectory）
    subdirectory: str = ""

    # P1#12: nested_templates — 嵌套模板变体
    # （来源: Cookiecutter main.py:144-146）
    nested_templates: dict[str, dict[str, str]] = field(default_factory=dict)

    secret_questions: list[str] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    tasks_before: list[Task] = field(default_factory=list)  # v2.0 前执行
    tasks_after: list[Task] = field(default_factory=list)  # v2.0 后执行
    external_data: dict[str, str] = field(default_factory=dict)  # P1#8
    message_before: str = ""  # 渲染前打印
    message_after: str = ""  # 渲染后打印

    # ─── 加载入口（委托给 config_loader.load_template_config）────────

    @classmethod
    def load(cls, project_type: str) -> "TemplateConfig":
        """加载并解析 ae-template.yml。

        约定：配置文件名为 ae-template.yml，位于 templates/<project_type>/ 下。
        配置中的 _ 前缀字段映射到 TemplateConfig 属性（去 _ 前缀）。
        其余字段解析为 Question 列表。
        """
        return load_template_config(project_type)
