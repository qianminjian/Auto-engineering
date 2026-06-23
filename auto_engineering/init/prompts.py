"""InteractivePrompt — 交互式问答.

来源：
- copier/_user_data.py:297-460 — Question.get_default_rendered() + render_value()
- cookiecutter/prompt.py:284-363 — prompt_for_config() 两遍循环 + 进度显示
- cookiecutter/prompt.py:61-80 — read_user_yes_no() 灵活的布尔解析

接口：
  InteractivePrompt(questions, answers) -> .run() -> AnswersMap
  prompt_for_project_type(available_types) -> str  (当 --type 未指定且无法自动检测时)
"""

from typing import Any

import jinja2
import click

from .config import Question
from .answers import AnswersMap


# 问题类型 → click 方法映射
# 来源：Copier CAST_STR_TO_NATIVE + Cookiecutter read_user_* 系列
_PROMPT_DISPATCH = {
    "str":    lambda q, ctx: click.prompt(q.help, default=q.default or ""),
    "bool":   lambda q, ctx: click.confirm(
        q.help,
        default=q.default if isinstance(q.default, bool) else True,
    ),
    "int":    lambda q, ctx: click.prompt(
        q.help, type=int, default=q.default or 0,
    ),
    "float":  lambda q, ctx: click.prompt(
        q.help, type=float, default=q.default or 0.0,
    ),
    "choice": lambda q, ctx: click.prompt(
        q.help,
        type=click.Choice(
            list(q.choices) if isinstance(q.choices, list)
            else list(q.choices.keys())
        ),
        default=q.default,
        show_choices=True,
    ),
    "secret": lambda q, ctx: click.prompt(
        q.help, hide_input=True, default=q.default or "",
    ),
    "json":   lambda q, ctx: click.prompt(
        q.help, default=str(q.default or "{}"),
    ),
    "yaml":   lambda q, ctx: click.prompt(
        q.help, default=str(q.default or ""),
    ),
}


class InteractivePrompt:
    """逐一展示 Question。

    参考 Cookiecutter prompt_for_config() 的两遍循环结构：
    - 第一遍：简单类型（str/bool/int/float/choice/secret）→ 先收集基础信息
    - 第二遍：复杂类型（json/yaml）→ 依赖基础信息可渲染
    同时借鉴 Copier Question 的 when 条件跳过逻辑。

    示例用法：
        questions: list[Question] = [...]
        answers = AnswersMap(defaults={"name": "test"})
        prompt = InteractivePrompt(questions, answers)
        result = prompt.run()  # 返回更新后的 AnswersMap
    """

    def __init__(self, questions: list[Question], answers: AnswersMap):
        self.questions = questions
        self.answers = answers
        self._jinja_env = jinja2.Environment()

    def run(self) -> AnswersMap:
        """执行交互式问答。返回更新后的 AnswersMap。

        两遍循环：
        1. 第一遍：简单类型 → 收集基础变量
        2. 第二遍：复杂类型 → 依赖第一遍的变量进行渲染
        """
        context = self.answers.combined()

        # 第一遍：简单类型（非 json/yaml）
        for i, q in enumerate(self._visible_questions("simple")):
            self._ask_one(q, context, progress=f"[{i+1}/{len(self.questions)}]")
            context = self.answers.combined()  # 刷新 context 供后续 when 判断

        # 第二遍：复杂类型（json/yaml — 依赖第一遍收集的变量）
        for q in self._visible_questions("complex"):
            self._ask_one(q, context, progress="")
            context = self.answers.combined()

        return self.answers

    def _ask_one(self, q: Question, context: dict, progress: str = "") -> None:
        """询问单个问题。

        流程：
        1. CLI flag 已提供 → 跳过
        2. when 条件不满足 → 跳过
        3. 类型推导 → 选择 Click 方法
        4. 渲染默认值（Jinja2 模板）
        5. 循环：prompt → cast → validate → 重试或通过
        6. 存入 answers.interactive
        """
        # CLI flag 已提供 → 跳过
        if q.var_name in self.answers.cli_overrides:
            return

        # when 条件不满足 → 跳过
        if not q.render_when(context, self._jinja_env):
            return

        # 类型推导 → 选择 Click 方法
        type_name = q.get_type_name()
        prompt_fn = _PROMPT_DISPATCH.get(type_name, _PROMPT_DISPATCH["str"])

        # 渲染 default（来源：Copier Question.get_default_rendered()）
        rendered_default = self._render_default(q, context)

        # 临时替换 q.default 为渲染后的值
        orig_default = q.default
        q.default = rendered_default

        prefix = f"  {progress} " if progress else "  "
        click.echo(f"{prefix}{q.help}", err=False)

        while True:
            raw_value = prompt_fn(q, context)
            try:
                value = q.cast_answer(raw_value)
            except (ValueError, TypeError) as e:
                click.echo(f"  ✗ 类型转换失败: {e}", err=True)
                continue

            error = q.render_validator(value, context, self._jinja_env)
            if error:
                click.echo(f"  ✗ {error}", err=True)
                continue
            break

        q.default = orig_default
        self.answers.interactive[q.var_name] = value

    def _visible_questions(self, pass_name: str) -> list[Question]:
        """过滤出当前遍应展示的问题。

        过滤规则：
        - 跳过 cli_overrides 中已提供的变量
        - pass_name="simple" → 排除 json/yaml 类型
        - pass_name="complex" → 仅包含 json/yaml 类型

        注：when 条件过滤延迟到 _ask_one() 中处理，
        因为 when 可能依赖同 pass 中先收集的变量。
        """
        result = []
        for q in self.questions:
            if q.var_name in self.answers.cli_overrides:
                continue
            type_name = q.get_type_name()
            if pass_name == "simple":
                if type_name not in ("json", "yaml"):
                    result.append(q)
            else:  # "complex"
                if type_name in ("json", "yaml"):
                    result.append(q)
        return result

    def _render_default(self, q: Question, context: dict) -> Any:
        """渲染 Jinja2 模板默认值。

        来源：Copier Question.get_default_rendered()
        - None → None
        - bool/int/float → 原样返回（非模板类型）
        - str 含 {{ → 作为 Jinja2 模板渲染
        - 其他 → 原样返回
        """
        if q.default is None:
            return None
        if isinstance(q.default, (bool, int, float)):
            return q.default
        if isinstance(q.default, str) and "{{" in q.default:
            tpl = self._jinja_env.from_string(q.default)
            return tpl.render(**context)
        return q.default


def prompt_for_project_type(available_types: list[str]) -> str:
    """当无法自动检测项目类型且非 --defaults 模式时调用。

    来源：Cookiecutter main.py choose_nested_template() 的交互式选择。
    """
    return click.prompt(
        "请选择项目类型",
        type=click.Choice(available_types),
        show_choices=True,
    )
