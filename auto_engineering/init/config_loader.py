"""TemplateConfig YAML 加载逻辑 — 从 config.py 提取的 load() 流程。

将 TemplateConfig.load() 中的解析流水线（YAML → kwargs → TemplateConfig）
抽到独立模块，config.py 只保留 dataclass 字段声明。
"""

from pathlib import Path
from typing import Any

import yaml

from .config_types import DEFAULT_EXCLUDE, TEMPLATES_ROOT, Question, Task
from .errors import ConfigFileError


def load_template_config(project_type: str) -> "TemplateConfig":  # noqa: F821
    """加载并解析 ae-template.yml，返回 TemplateConfig 实例。

    完整流程：
    1. 读取 templates/<project_type>/ae-template.yml
    2. 解析 !include 标签（递归合并）
    3. 分离 _ 前缀配置与问题定义
    4. 解析 _tasks 列表到 tasks_before / tasks_after
    5. 处理 nested_templates 子模板
    6. 构造 TemplateConfig
    """
    from .config import TemplateConfig

    config_path = TEMPLATES_ROOT / project_type / "ae-template.yml"
    if not config_path.exists():
        raise ConfigFileError(f"模板配置文件不存在: {config_path}")

    # 支持 !include 标签合并（来源: Copier _template.py:92-106 YAML !include）
    raw = _load_yaml_with_includes(config_path)

    # 分离 _ 前缀配置与问题定义（来源：Copier filter_config）
    questions_data: dict[str, Any] = {}
    config_kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            config_key = key[1:]  # 去 _ 前缀
            if config_key == "tasks":
                _parse_tasks(value, config_kwargs)
            elif config_key == "exclude":
                config_kwargs["exclude"] = DEFAULT_EXCLUDE + list(value)
            elif config_key == "skip_if_exists":
                config_kwargs["skip_if_exists"] = list(value)
            elif config_key == "secret_questions":
                config_kwargs["secret_questions"] = list(value)
            elif config_key == "envops":
                config_kwargs["envops"] = {**config_kwargs.get("envops", {}), **value}
            elif config_key == "no_render":
                config_kwargs["no_render"] = list(value)
            elif config_key == "external_data":
                config_kwargs["external_data"] = dict(value)
            elif config_key == "nested_templates":
                config_kwargs["nested_templates"] = dict(value)
            elif config_key == "subdirectory":
                config_kwargs["subdirectory"] = str(value)
            elif config_key == "templates_suffix":
                config_kwargs["templates_suffix"] = str(value)
            elif config_key == "min_ae_version":
                config_kwargs["min_ae_version"] = str(value)
            elif config_key == "message_before":
                config_kwargs["message_before"] = str(value)
            elif config_key == "message_after":
                config_kwargs["message_after"] = str(value)
            else:
                config_kwargs[config_key] = value
        else:
            questions_data[key] = value

    # 嵌套模板处理（来源: Cookiecutter main.py:144-146 choose_nested_template）
    nested = config_kwargs.get("nested_templates", {})
    if nested:
        chosen = _resolve_nested_template(config_path.parent, nested)
        if chosen:
            config_path = chosen

    questions = _parse_questions(questions_data)
    return TemplateConfig(template_dir=config_path.parent, questions=questions, **config_kwargs)


def _load_yaml_with_includes(config_path: Path) -> dict:
    """加载 YAML 并解析 !include 标签。

    来源：Copier _template.py:92-106 _include() + Loader。
    !include 后接相对路径（相对于当前配置文件），支持 glob 模式。
    被 include 的文件内容与当前文件合并。

    v2.5 P2-C-1: glob 解析后验证每个匹配 path 在 config_path.parent
    (realpath) 内, 防止恶意模板 `!include ../../../*.yml` 越界读到
    模板目录外的文件 (例如 ~/.ssh/, /etc/ 等).
    """

    class _IncludeLoader(yaml.SafeLoader):
        pass

    def _include(loader: yaml.Loader, node: yaml.Node) -> Any:
        include_spec = str(loader.construct_scalar(node))
        full_paths = list(config_path.parent.glob(include_spec))
        results: list[dict] = []
        for path_obj in full_paths:
            # P2-C-1: 验证 path 在 config_path.parent 内 (realpath 防御 symlink)
            import os
            config_parent_real = os.path.realpath(config_path.parent)
            path_real = os.path.realpath(path_obj)
            root_prefix = (
                config_parent_real
                if config_parent_real.endswith(os.sep)
                else config_parent_real + os.sep
            )
            if not (
                path_real == config_parent_real
                or path_real.startswith(root_prefix)
            ):
                raise ValueError(
                    f"!include glob '{include_spec}' 匹配到模板目录外的文件: "
                    f"{path_obj} (resolved: {path_real}). 模板目录: {config_parent_real}. "
                    f"Refusing to load (potential template injection)."
                )
            with open(path_obj) as fh:
                for doc in yaml.safe_load_all(fh):
                    if doc:
                        results.append(doc)
        if not results:
            return None
        if len(results) == 1:
            return results[0]
        return results

    _IncludeLoader.add_constructor("!include", _include)

    with open(config_path) as fh:
        all_docs = list(yaml.load_all(fh, Loader=_IncludeLoader))
        result: dict[str, Any] = {}
        for doc in filter(None, all_docs):
            result.update(doc)
        return result


def _resolve_nested_template(template_dir: Path, nested: dict) -> Path | None:
    """解析嵌套模板选择。

    来源：Cookiecutter main.py:144-146 choose_nested_template。
    非交互模式返回 None（交给 InteractivePrompt 处理）。
    """
    if not nested:
        return None
    # 交互式选择由 InteractivePrompt 处理，InitWorker._phase_prompt
    # 会检测 nested_templates 并调用 prompt_for_nested_template
    return None


def _parse_questions(data: dict[str, Any]) -> list[Question]:
    """将 YAML 问题定义转为 Question 对象列表。

    简化格式（来源：Copier filter_config 68-71 行）:
      key: "default value"  →  Question(var_name=key, default="default value")
    完整格式:
      key:
        type: str
        help: "..."
        default: "..."
        ...
    """
    questions: list[Question] = []
    for var_name, raw in data.items():
        if not isinstance(raw, dict):
            raw = {"default": raw}
        q_kwargs = {k: v for k, v in raw.items() if k in Question.__dataclass_fields__}
        questions.append(Question(var_name=var_name, **q_kwargs))
    return questions


def _parse_tasks(tasks_raw: list[dict[str, Any]], config_kwargs: dict[str, Any]) -> None:
    """将 _tasks 列表按默认 stage 分到 tasks_before / tasks_after。

    来源：Copier _template.py filter_config 中的 _tasks 处理。
    stage 默认为 "after"，"before" 阶段的在 v2.0（渲染）前执行。
    """
    before: list[Task] = []
    after: list[Task] = []
    for t in tasks_raw:
        task_kwargs = {k: v for k, v in t.items() if k in Task.__dataclass_fields__}
        task = Task(**task_kwargs)
        stage = t.get("stage", "after")
        if stage == "before":
            before.append(task)
        else:
            after.append(task)
    config_kwargs["tasks_before"] = before
    config_kwargs["tasks_after"] = after
