"""ae-template.yml 解析 — TemplateConfig / Question / Task。

参考来源：
- copier/_template.py:60-299  — filter_config() + load_template_config() + !include
- copier/_user_data.py:136-295 — Question dataclass 定义

接口：load_ae_template(project_type: str) -> TemplateConfig

模板目录结构约定：
  templates/<type>/ae-template.yml          ← 问题+钩子定义
  templates/<type>/**/*.jinja               ← 模板文件
  templates/_shared/                        ← 所有类型共享的基础文件
  templates/_features/<feature>/            ← 可组合功能模块
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import jinja2

# ─── 常量 ────────────────────────────────────────────────────────────────────

TEMPLATES_ROOT = Path(__file__).parent / "templates"

# 默认排除列表（来源: Copier _template.py:DEFAULT_EXCLUDE）
DEFAULT_EXCLUDE = [
    "ae-template.yml", "ae-template.yaml",
    "~*", "*.py[co]", "__pycache__",
    ".git", ".DS_Store", ".svn",
]

DEFAULT_TEMPLATES_SUFFIX = ".jinja"


# ─── Question ─────────────────────────────────────────────────────────────────


@dataclass
class Question:
    """单个交互式问题。

    参考 Copier _user_data.py:137-221 的 Question dataclass。

    关键设计：
    - type 可从 default 值自动推断（default=True → type="bool"）
    - when/validator 为 Jinja2 模板字符串，渲染后判断
    - choices 支持 list[str] 或 dict[label, value]
    - secret=True 时 default 不能为空（Copier 规则）
    """

    var_name: str                     # 变量名，对应 ae-template.yml 的 key
    type: str = ""                    # str|bool|int|float|json|yaml|choice，空字符串=自动推导
    help: str = ""                    # 提示文本
    default: Any = None               # 默认值
    choices: list[str] | dict[str, Any] | None = None
    when: str | bool = True           # Jinja2 条件
    validator: str = ""               # Jinja2 校验模板，空=不校验
    secret: bool = False
    multiselect: bool = False
    placeholder: str = ""

    def get_type_name(self) -> str:
        """返回最终类型名。空字符串时从 default 类型推导。

        来源：Copier _user_data.py Question._check_type() 类型推导逻辑。
        """
        if self.type:
            return self.type
        default_type_map = {
            bool: "bool",
            int: "int",
            float: "float",
            list: "json" if self.multiselect else "yaml",
            dict: "json",
            str: "str",
        }
        mapped = default_type_map.get(type(self.default))
        if mapped:
            return mapped
        if self.default is not None:
            return "yaml"
        return "str"

    def render_when(self, context: dict, jinja_env: jinja2.Environment) -> bool:
        """渲染 when 条件。来源：Copier _user_data.py Question.get_when()"""
        if isinstance(self.when, bool):
            return self.when
        tpl = jinja_env.from_string(str(self.when))
        result = tpl.render(**context).strip()
        return result.lower() not in ("false", "no", "0", "")

    def render_validator(
        self, value: Any, context: dict, jinja_env: jinja2.Environment
    ) -> str:
        """渲染 validator 模板，返回错误信息或空字符串。

        来源：Copier _user_data.py Question._get_answer_validation_error()
        """
        if not self.validator:
            return ""
        tpl = jinja_env.from_string(self.validator)
        return tpl.render(**{**context, self.var_name: value}).strip()

    def cast_answer(self, raw: str) -> Any:
        """将用户输入的字符串转为目标类型。

        来源：Copier _user_data.py CAST_STR_TO_NATIVE 字典。
        支持：str / bool / int / float / json / yaml / choice 七种类型。
        """
        type_name = self.get_type_name()
        if type_name == "str":
            return raw
        if type_name == "bool":
            return raw.strip().lower() in ("yes", "y", "true", "t", "1")
        if type_name == "int":
            return int(raw)
        if type_name == "float":
            return float(raw)
        if type_name in ("json", "yaml"):
            return yaml.safe_load(raw) if raw.strip() else None
        if type_name == "choice":
            return raw
        return raw


# ─── Task ──────────────────────────────────────────────────────────────────────


@dataclass
class Task:
    """单个钩子命令。

    参考 Copier _template.py:162-188 Task dataclass。

    - cmd: 命令字符串（可含 Jinja2 变量）或命令列表（安全模式，无 shell 注入）
    - when: Jinja2 条件，False → 跳过
    - working_directory: 相对于项目根目录的执行路径
    - extra_vars: 注入为 Jinja 渲染变量（_ 前缀）和环境变量（大写）
    """

    cmd: str | list[str]
    when: str | bool = True
    working_directory: str = ""
    extra_vars: dict[str, Any] = field(default_factory=dict)


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
    exclude: list[str] = field(default_factory=lambda: DEFAULT_EXCLUDE.copy())
    skip_if_exists: list[str] = field(default_factory=list)

    # P1#7: _envops — Jinja2 环境选项（来源: Copier copier.yaml _envops）
    envops: dict = field(default_factory=lambda: {
        "autoescape": False,
        "keep_trailing_newline": True,
    })

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
    tasks_before: list[Task] = field(default_factory=list)   # Phase 3 前执行
    tasks_after: list[Task] = field(default_factory=list)    # Phase 3 后执行
    external_data: dict[str, str] = field(default_factory=dict)  # P1#8
    message_before: str = ""           # 渲染前打印
    message_after: str = ""            # 渲染后打印

    # ─── 加载 ─────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, project_type: str) -> "TemplateConfig":
        """加载并解析 ae-template.yml。

        约定：配置文件名为 ae-template.yml，位于 templates/<project_type>/ 下。
        配置中的 _ 前缀字段映射到 TemplateConfig 属性（去 _ 前缀）。
        其余字段解析为 Question 列表。
        """
        from .errors import ConfigFileError

        config_path = TEMPLATES_ROOT / project_type / "ae-template.yml"
        if not config_path.exists():
            raise ConfigFileError(f"模板配置文件不存在: {config_path}")

        # 支持 !include 标签合并（来源: Copier _template.py:92-106 YAML !include）
        raw = cls._load_yaml_with_includes(config_path)

        # 分离 _ 前缀配置与问题定义（来源：Copier filter_config）
        questions_data: dict[str, Any] = {}
        config_kwargs: dict[str, Any] = {}
        for key, value in raw.items():
            if key.startswith("_"):
                config_key = key[1:]  # 去 _ 前缀
                if config_key == "tasks":
                    cls._parse_tasks(value, config_kwargs)
                elif config_key == "exclude":
                    config_kwargs["exclude"] = DEFAULT_EXCLUDE + list(value)
                elif config_key == "skip_if_exists":
                    config_kwargs["skip_if_exists"] = list(value)
                elif config_key == "secret_questions":
                    config_kwargs["secret_questions"] = list(value)
                elif config_key == "envops":
                    config_kwargs["envops"] = {
                        **config_kwargs.get("envops", {}), **value
                    }
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
            chosen = cls._resolve_nested_template(config_path.parent, nested)
            if chosen:
                config_path = chosen

        questions = cls._parse_questions(questions_data)
        return cls(template_dir=config_path.parent, questions=questions, **config_kwargs)

    # ─── YAML !include 支持 ───────────────────────────────────────────────

    @staticmethod
    def _load_yaml_with_includes(config_path: Path) -> dict:
        """加载 YAML 并解析 !include 标签。

        来源：Copier _template.py:92-106 _include() + Loader。
        !include 后接相对路径（相对于当前配置文件），支持 glob 模式。
        被 include 的文件内容与当前文件合并。
        """
        class _IncludeLoader(yaml.SafeLoader):
            pass

        def _include(loader: yaml.Loader, node: yaml.Node) -> Any:
            include_spec = str(loader.construct_scalar(node))
            full_paths = list(config_path.parent.glob(include_spec))
            results: list[dict] = []
            for path_obj in full_paths:
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

    # ─── 嵌套模板解析 ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_nested_template(
        template_dir: Path, nested: dict
    ) -> Path | None:
        """解析嵌套模板选择。

        来源：Cookiecutter main.py:144-146 choose_nested_template。
        如果 nested = {"typescript": {"path": "./ts", "title": "..."}, ...}
        则返回选中的子模板目录下的 ae-template.yml 路径。

        非交互模式返回 None（交给 InteractivePrompt 处理）。
        """
        if not nested:
            return None
        # 交互式选择由 InteractivePrompt 处理，InitWorker._phase_prompt
        # 会检测 nested_templates 并调用 prompt_for_nested_template
        return None

    # ─── 问题解析 ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_questions(data: dict[str, Any]) -> list[Question]:
        """将 YAML 问题定义转为 Question 对象列表。

        简化格式（来源：Copier filter_config 68-71 行）:
          key: "default value"  →  Question(var_name=key, default="default value")
        完整格式:
          key:
            type: str
            help: "..."
            default: "..."
            choices: [...]
            when: "..."
            validator: "..."
        """
        questions: list[Question] = []
        for var_name, raw in data.items():
            if not isinstance(raw, dict):
                raw = {"default": raw}
            # 只传入 Question dataclass 定义的字段
            q_kwargs = {
                k: v for k, v in raw.items()
                if k in Question.__dataclass_fields__
            }
            questions.append(Question(var_name=var_name, **q_kwargs))
        return questions

    # ─── 任务解析 ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_tasks(
        tasks_raw: list[dict[str, Any]], config_kwargs: dict[str, Any]
    ) -> None:
        """将 _tasks 列表按默认 stage 分到 tasks_before / tasks_after。

        来源：Copier _template.py filter_config 中的 _tasks 处理。
        stage 默认为 "after"，"before" 阶段的在 Phase 3（渲染）前执行。
        """
        before: list[Task] = []
        after: list[Task] = []
        for t in tasks_raw:
            task_kwargs = {
                k: v for k, v in t.items()
                if k in Task.__dataclass_fields__
            }
            task = Task(**task_kwargs)
            stage = t.get("stage", "after")
            if stage == "before":
                before.append(task)
            else:
                after.append(task)
        config_kwargs["tasks_before"] = before
        config_kwargs["tasks_after"] = after
