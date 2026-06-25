"""Tests for InteractivePrompt — 交互式问答."""

from unittest.mock import patch

import click
import jinja2
import pytest

from auto_engineering.init.answers import AnswersMap
from auto_engineering.init.config import Question
from auto_engineering.init.prompts import (
    _PROMPT_DISPATCH,
    InteractivePrompt,
    prompt_for_project_type,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def jinja_env() -> jinja2.Environment:
    return jinja2.Environment()


@pytest.fixture
def basic_questions() -> list[Question]:
    return [
        Question(var_name="name", type="str", default="test-project", help="项目名称"),
        Question(var_name="use_typescript", type="bool", default=True, help="是否使用 TypeScript"),
        Question(var_name="port", type="int", default=8080, help="服务端口"),
        Question(var_name="version", type="float", default=1.0, help="版本号"),
    ]


@pytest.fixture
def complex_questions() -> list[Question]:
    return [
        Question(var_name="name", type="str", default="test-app", help="项目名称"),
        Question(var_name="config_json", type="json", default="{}", help="JSON 配置"),
        Question(var_name="config_yaml", type="yaml", default="version: '1.0'", help="YAML 配置"),
    ]


@pytest.fixture
def answers() -> AnswersMap:
    return AnswersMap()


# ─── _PROMPT_DISPATCH ───────────────────────────────────────────────────────────


class TestPromptDispatch:
    """_PROMPT_DISPATCH 类型映射表."""

    def test_has_all_eight_types(self):
        """确认 8 种类型全部映射."""
        assert "str" in _PROMPT_DISPATCH
        assert "bool" in _PROMPT_DISPATCH
        assert "int" in _PROMPT_DISPATCH
        assert "float" in _PROMPT_DISPATCH
        assert "choice" in _PROMPT_DISPATCH
        assert "secret" in _PROMPT_DISPATCH
        assert "json" in _PROMPT_DISPATCH
        assert "yaml" in _PROMPT_DISPATCH
        assert len(_PROMPT_DISPATCH) == 8

    def test_all_are_callable(self):
        """确认全部映射值都是可调用对象."""
        for key, fn in _PROMPT_DISPATCH.items():
            assert callable(fn), f"_PROMPT_DISPATCH['{key}'] is not callable"


# ─── InteractivePrompt.__init__ ──────────────────────────────────────────────────


class TestInteractivePromptInit:
    """InteractivePrompt 构造."""

    def test_stores_questions_and_answers(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        assert prompt.questions is basic_questions
        assert prompt.answers is answers

    def test_creates_jinja2_environment(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        assert isinstance(prompt._jinja_env, jinja2.Environment)


# ─── _render_default ────────────────────────────────────────────────────────────


class TestRenderDefault:
    """_render_default() Jinja2 模板默认值渲染."""

    def test_none_default_returns_none(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="no_default", type="str", default=None)
        result = prompt._render_default(q, {})
        assert result is None

    def test_bool_returns_as_is(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="flag", type="bool", default=True)
        result = prompt._render_default(q, {})
        assert result is True

    def test_int_returns_as_is(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="port", type="int", default=8080)
        result = prompt._render_default(q, {})
        assert result == 8080

    def test_float_returns_as_is(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="version", type="float", default=1.5)
        result = prompt._render_default(q, {})
        assert result == 1.5

    def test_str_without_template_returns_as_is(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="name", type="str", default="hello")
        result = prompt._render_default(q, {})
        assert result == "hello"

    def test_str_with_template_renders(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="greeting", type="str", default="Hello {{ name }}!")
        result = prompt._render_default(q, {"name": "World"})
        assert result == "Hello World!"

    def test_list_default_renders_template(self, basic_questions, answers):
        """列表类型的 default 如果是含模板的字符串，也应渲染."""
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="tags", type="yaml", default="[{{ name }}, 'v2']")
        result = prompt._render_default(q, {"name": "app"})
        assert result == "[app, 'v2']"


# ─── _visible_questions ─────────────────────────────────────────────────────────


class TestVisibleQuestions:
    """_visible_questions() 问题过滤."""

    def test_simple_pass_excludes_json_yaml(self, complex_questions, answers):
        prompt = InteractivePrompt(complex_questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        assert "name" in var_names
        assert "config_json" not in var_names
        assert "config_yaml" not in var_names

    def test_complex_pass_includes_only_json_yaml(self, complex_questions, answers):
        prompt = InteractivePrompt(complex_questions, answers)
        visible = prompt._visible_questions("complex")
        var_names = [q.var_name for q in visible]
        assert "name" not in var_names
        assert "config_json" in var_names
        assert "config_yaml" in var_names

    def test_excludes_cli_overrides(self, basic_questions, answers):
        answers.cli_overrides["name"] = "cli-value"
        prompt = InteractivePrompt(basic_questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        assert "name" not in var_names
        assert "use_typescript" in var_names

    def test_excludes_when_false(self, basic_questions, answers):
        """when=False 的问题也会出现在 _visible_questions 中，由 _ask_one 跳过."""
        questions = [
            Question(var_name="use_ts", type="bool", default=True),
            Question(var_name="ts_config", type="str", default="strict", when=False),  # 永远跳过
        ]
        answers.interactive["use_ts"] = True
        prompt = InteractivePrompt(questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        # _visible_questions 不再过滤 when（交给 _ask_one），所以 ts_config 会出现
        assert "ts_config" in var_names
        # 但 _ask_one 应跳过它
        prompt._ask_one(questions[1], answers.combined())
        assert "ts_config" not in answers.interactive

    def test_excludes_when_jinja_false(self, basic_questions, answers):
        """when 为 Jinja2 模板且求值为 False 时，_visible_questions 包含但 _ask_one 跳过."""
        questions = [
            Question(var_name="use_ts", type="bool", default=True),
            Question(
                var_name="ts_strict", type="bool", default=False, when="{{ use_ts == false }}"
            ),
        ]
        answers.defaults["use_ts"] = True
        prompt = InteractivePrompt(questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        # _visible_questions 不再过滤 when，所以 ts_strict 会出现
        assert "ts_strict" in var_names
        # 但 _ask_one 应在 when 求值为 False 时跳过
        prompt._ask_one(questions[1], answers.combined())
        assert "ts_strict" not in answers.interactive

    def test_when_true_includes(self, basic_questions, answers):
        questions = [
            Question(var_name="lang", type="choice", choices=["py", "js"], default="py"),
            Question(var_name="py_version", type="str", default="3.12", when="{{ lang == 'py' }}"),
        ]
        answers.defaults["lang"] = "py"
        prompt = InteractivePrompt(questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        assert "py_version" in var_names

    def test_when_with_rendered_context(self, basic_questions, answers):
        """when 使用 interactive 层已收集的变量."""
        questions = [
            Question(var_name="name", type="str", default="app"),
            Question(var_name="suffix", type="str", default="", when="{{ name != '' }}"),
        ]
        answers.interactive["name"] = "myapp"
        prompt = InteractivePrompt(questions, answers)
        visible = prompt._visible_questions("simple")
        var_names = [q.var_name for q in visible]
        assert "suffix" in var_names


# ─── _ask_one ───────────────────────────────────────────────────────────────────


class TestAskOne:
    """_ask_one() 单个问题询问."""

    def test_skip_when_cli_override(self, basic_questions, answers):
        answers.cli_overrides["name"] = "cli-name"
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="name", type="str", default="test")
        prompt._ask_one(q, {"name": "cli-name"})
        # 不应写入 interactive
        assert "name" not in answers.interactive

    def test_skip_when_condition_false(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="skipped", type="str", default="nope", when=False)
        prompt._ask_one(q, {})
        assert "skipped" not in answers.interactive

    def test_stores_value_in_interactive(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="name", type="str", default="default-name", help="项目名称")
        with patch("click.prompt", return_value="my-project"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["name"] == "my-project"

    def test_casts_to_int(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="port", type="int", default=8000)
        with patch("click.prompt", return_value="3000"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["port"] == 3000
        assert isinstance(answers.interactive["port"], int)

    def test_casts_to_bool(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="flag", type="bool", default=False)
        # click.confirm returns bool directly
        with patch("click.confirm", return_value=True), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["flag"] is True

    def test_casts_to_float(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="version", type="float", default=1.0)
        with patch("click.prompt", return_value="2.5"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["version"] == 2.5

    def test_retry_on_cast_failure(self, basic_questions, answers):
        """类型转换失败时应重试."""
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="port", type="int", default=8000)
        with (
            patch("click.prompt", side_effect=["not-a-number", "3000"]),
            patch("click.echo"),
        ):
            prompt._ask_one(q, {})
        assert answers.interactive["port"] == 3000

    def test_retry_on_validator_failure(self, basic_questions, answers):
        """校验失败时应重试."""
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(
            var_name="name",
            type="str",
            default="",
            validator="{{ '不能为空' if not name else '' }}",
        )
        with patch("click.prompt", side_effect=["", "valid-name"]), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["name"] == "valid-name"

    def test_restores_original_default(self, basic_questions, answers):
        """_ask_one 结束后应恢复原始 default 值."""
        prompt = InteractivePrompt(basic_questions, answers)
        orig_default = "original"
        q = Question(var_name="name", type="str", default=orig_default)
        with patch("click.prompt", return_value="new-value"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert q.default == orig_default

    def test_echoes_progress(self, basic_questions, answers):
        """有 progress 参数时应输出前缀."""
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="name", type="str", default="test", help="项目名称")
        with (
            patch("click.prompt", return_value="my-name"),
            patch("click.echo") as mock_echo,
        ):
            prompt._ask_one(q, {}, progress="[1/3]")
        # 验证 click.echo 被调用（前缀 + help）
        assert mock_echo.called

    def test_secret_type(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="api_key", type="secret", default="", secret=True)
        with patch("click.prompt", return_value="sk-abc123"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["api_key"] == "sk-abc123"

    def test_choice_type(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(
            var_name="lang", type="choice", choices=["python", "javascript", "go"], default="python"
        )
        with patch("click.prompt", return_value="python"), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["lang"] == "python"

    def test_json_type_parsed(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="config", type="json", default="{}")
        with patch("click.prompt", return_value='{"key": "value"}'), patch("click.echo"):
            prompt._ask_one(q, {})
        assert answers.interactive["config"] == {"key": "value"}

    def test_yaml_type_parsed(self, basic_questions, answers):
        prompt = InteractivePrompt(basic_questions, answers)
        q = Question(var_name="spec", type="yaml", default="version: '1.0'")
        with (
            patch("click.prompt", return_value="name: app\nversion: '2.0'"),
            patch("click.echo"),
        ):
            prompt._ask_one(q, {})
        assert answers.interactive["spec"] == {"name": "app", "version": "2.0"}


# ─── run() ──────────────────────────────────────────────────────────────────────


class TestRun:
    """run() 两遍循环."""

    def test_collects_simple_then_complex(self, complex_questions, answers):
        """第一遍收集 simple，第二遍收集 complex."""
        prompt = InteractivePrompt(complex_questions, answers)

        def mock_prompt_side_effect(*args, **kwargs):
            # 根据类型返回不同值
            # str → "my-app", json → '{"k":"v"}', yaml → "key: val"
            return "mock-value"

        with (
            patch("click.prompt", side_effect=mock_prompt_side_effect),
            patch("click.confirm", return_value=True),
            patch("click.echo"),
        ):
            result = prompt.run()

        assert result is answers
        # simple pass 应收集 name
        assert "name" in answers.interactive
        # complex pass 应收集 json 和 yaml
        assert "config_json" in answers.interactive
        assert "config_yaml" in answers.interactive

    def test_refreshes_context_between_passes(self, basic_questions, answers):
        """每遍过后应刷新 context，供后续 when 判断使用."""
        questions = [
            Question(var_name="use_ts", type="bool", default=False),
            Question(var_name="ts_mode", type="str", default="strict", when="{{ use_ts == true }}"),
        ]
        prompt = InteractivePrompt(questions, answers)

        with (
            patch("click.confirm", return_value=True),
            patch("click.prompt", return_value="relaxed"),
            patch("click.echo"),
        ):
            prompt.run()

        # use_ts=True → ts_mode 的 when 变为 True → 应被追问
        assert "use_ts" in answers.interactive
        assert "ts_mode" in answers.interactive

    def test_skips_cli_overridden_questions(self, basic_questions, answers):
        answers.cli_overrides["name"] = "cli-project"
        prompt = InteractivePrompt(basic_questions, answers)
        with (
            patch("click.prompt", return_value="ignored"),
            patch("click.confirm", return_value=True),
            patch("click.echo"),
        ):
            prompt.run()
        # name 由 CLI 提供，不应出现在 interactive 中
        assert "name" not in answers.interactive
        # 但其他问题应该被追问
        assert "use_typescript" in answers.interactive

    def test_no_questions_returns_unchanged(self, answers):
        prompt = InteractivePrompt([], answers)
        result = prompt.run()
        assert result is answers
        assert answers.interactive == {}

    def test_all_cli_overrides_skips_all(self, basic_questions, answers):
        """全部问题都由 CLI 提供时，run() 不应询问任何问题."""
        for q in basic_questions:
            answers.cli_overrides[q.var_name] = f"cli-{q.var_name}"
        prompt = InteractivePrompt(basic_questions, answers)
        with (
            patch("click.prompt") as mock_prompt,
            patch("click.confirm") as mock_confirm,
            patch("click.echo"),
        ):
            prompt.run()
        # 不应调用任何 prompt
        mock_prompt.assert_not_called()
        mock_confirm.assert_not_called()

    def test_when_jinja_template_uses_answers_context(self, basic_questions, answers):
        """when 条件使用 combined() 上下文中的变量."""
        questions = [
            Question(var_name="project_name", type="str", default="test"),
            Question(
                var_name="project_slug",
                type="str",
                default="{{ project_name | lower | replace(' ', '-') }}",
                when="{{ project_name != '' }}",
            ),
        ]
        answers.defaults["project_name"] = "My App"
        prompt = InteractivePrompt(questions, answers)

        with patch("click.prompt", return_value="My App"), patch("click.echo"):
            prompt.run()

        # project_slug 的 when 条件 project_name != '' 应为 True
        assert "project_slug" in answers.interactive


# ─── prompt_for_project_type ────────────────────────────────────────────────────


class TestPromptForProjectType:
    """prompt_for_project_type() 函数."""

    def test_returns_selected_type(self):
        available = ["app-service", "library", "cli-tool"]
        with patch("click.prompt", return_value="library"):
            result = prompt_for_project_type(available)
        assert result == "library"

    def test_passes_available_as_choices(self):
        available = ["app-service", "library", "cli-tool"]
        with patch("click.prompt") as mock_prompt:
            mock_prompt.return_value = "app-service"
            prompt_for_project_type(available)
        # 验证 click.prompt 的参数中包含 type=click.Choice
        call_kwargs = mock_prompt.call_args[1]
        assert isinstance(call_kwargs["type"], click.Choice)
        assert call_kwargs["show_choices"] is True
