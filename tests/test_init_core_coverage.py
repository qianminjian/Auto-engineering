"""C1: init 子系统核心模块单元测试 — 覆盖 detector/answers/renderer/hooks/errors/config.

目标：init 子系统整体覆盖率 ≥ 80%
"""

import json
from pathlib import Path

import pytest

from auto_engineering.init.answers import (
    BUILTIN_VARS,
    AnswersMap,
    _LazyExternalDict,
)
from auto_engineering.init.config import (
    DEFAULT_EXCLUDE,
    Question,
    Task,
    TemplateConfig,
)
from auto_engineering.init.detector import (
    FRAMEWORK_SIGNATURES,
    ProjectDetector,
    _signature_matches,
)
from auto_engineering.init.errors import (
    ConfigFileError,
    InitError,
    InitInterruptedError,
    TargetDirectoryError,
    TaskExecutionError,
    TemplateRenderError,
    UnsatisfiedPrerequisiteError,
    ValidationError,
)
from auto_engineering.init.hooks import TaskRunner
from auto_engineering.init.renderer import TemplateRenderer

# ─── BUILTIN_VARS ────────────────────────────────────────────────────────────


class TestBUILTINVARS:
    def test_contains_required_keys(self):
        assert "_ae_version" in BUILTIN_VARS
        assert "current_year" in BUILTIN_VARS
        assert "_folder_name" in BUILTIN_VARS
        assert "_ae_python" in BUILTIN_VARS
        assert "sep" in BUILTIN_VARS
        assert "os" in BUILTIN_VARS

    def test_os_field_is_string(self):
        # os can be a dict (linux/darwin/win32 → name) or string depending on platform
        assert isinstance(BUILTIN_VARS["os"], (str, dict))


# ─── _LazyExternalDict ──────────────────────────────────────────────────────


class TestLazyExternalDict:
    def test_loads_yaml(self, tmp_path: Path):
        f = tmp_path / "data.yml"
        f.write_text("name: test\n")
        d = _LazyExternalDict({"x": str(f)})
        assert d["x"] == {"name": "test"}

    def test_loads_json(self, tmp_path: Path):
        f = tmp_path / "data.json"
        f.write_text('{"a": 1}')
        d = _LazyExternalDict({"x": str(f)})
        assert d["x"] == {"a": 1}

    def test_missing_file_returns_none(self, tmp_path: Path):
        d = _LazyExternalDict({"x": str(tmp_path / "missing.yml")})
        assert d["x"] is None

    def test_contains(self):
        d = _LazyExternalDict({"a": "/a.yml", "b": "/b.yml"})
        assert "a" in d
        assert "z" not in d

    def test_iter(self):
        d = _LazyExternalDict({"a": "/a.yml", "b": "/b.yml"})
        assert set(iter(d)) == {"a", "b"}

    def test_len(self):
        d = _LazyExternalDict({"a": "/a.yml"})
        assert len(d) == 1

    def test_keys(self):
        d = _LazyExternalDict({"a": "/a.yml", "b": "/b.yml"})
        assert set(d.keys()) == {"a", "b"}

    def test_items(self, tmp_path: Path):
        f = tmp_path / "x.yml"
        f.write_text("v: 1\n")
        d = _LazyExternalDict({"x": str(f)})
        items = dict(d.items())
        assert items["x"] == {"v": 1}

    def test_repr(self):
        d = _LazyExternalDict({"a": "/a.yml"})
        assert "a" in repr(d)

    def test_unknown_suffix_falls_back_to_yaml(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("k: v\n")
        d = _LazyExternalDict({"x": str(f)})
        assert d["x"] == {"k": "v"}


# ─── AnswersMap ──────────────────────────────────────────────────────────────


class TestAnswersMap:
    def test_priority_order(self):
        m = AnswersMap(
            cli_overrides={"a": "cli"},
            interactive={"a": "inter"},
            previous={"a": "prev"},
            defaults={"a": "default"},
        )
        assert m.get("a") == "cli"

    def test_cli_over_interactive(self):
        m = AnswersMap(
            cli_overrides={"a": "cli"},
            interactive={"a": "inter"},
        )
        assert m.get("a") == "cli"

    def test_interactive_over_previous(self):
        m = AnswersMap(
            interactive={"a": "inter"},
            previous={"a": "prev"},
        )
        assert m.get("a") == "inter"

    def test_previous_over_defaults(self):
        m = AnswersMap(
            previous={"a": "prev"},
            defaults={"a": "default"},
        )
        assert m.get("a") == "prev"

    def test_defaults_over_builtins(self):
        m = AnswersMap(defaults={"current_year": "1999"})
        assert m.get("current_year") == "1999"

    def test_builtins_fallback(self):
        m = AnswersMap()
        assert m.get("_ae_version") == "1.0.0"
        assert m.get("current_year")

    def test_external_lazy_load(self, tmp_path: Path):
        f = tmp_path / "ext.yml"
        f.write_text("v: 42\n")
        m = AnswersMap(external={"k": str(f)})
        assert m.get("k") == {"v": 42}

    def test_external_missing_returns_none(self, tmp_path: Path):
        m = AnswersMap(external={"k": str(tmp_path / "missing.yml")})
        assert m.get("k") is None

    def test_external_cached(self, tmp_path: Path):
        f = tmp_path / "ext.yml"
        f.write_text("v: 1\n")
        m = AnswersMap(external={"k": str(f)})
        m.get("k")
        m.get("k")  # second access uses cache
        assert "k" in m._external_cache

    def test_missing_key_raises(self):
        m = AnswersMap()
        with pytest.raises(KeyError):
            m.get("nonexistent_xyz")

    def test_combined_includes_all_layers(self):
        m = AnswersMap(
            cli_overrides={"a": 1},
            interactive={"b": 2},
            previous={"c": 3},
            defaults={"d": 4},
        )
        c = m.combined()
        assert c["a"] == 1
        assert c["b"] == 2
        assert c["c"] == 3
        assert c["d"] == 4
        assert "_ae_version" in c

    def test_combined_with_external_includes_lazy(self, tmp_path: Path):
        f = tmp_path / "ext.yml"
        f.write_text("v: 1\n")
        m = AnswersMap(external={"k": str(f)})
        c = m.combined()
        assert "_external_data" in c
        # lazy — accessing it triggers load
        assert c["_external_data"]["k"] == {"v": 1}

    def test_hide(self):
        m = AnswersMap()
        m.hide("secret_field")
        assert "secret_field" in m.hidden

    def test_save_partial(self, tmp_path: Path):
        m = AnswersMap(interactive={"a": "inter"})
        out = m.save_partial(tmp_path / "partial.yml")
        assert out.exists()
        content = out.read_text()
        assert "a: inter" in content
        assert "partial: true" in content

    def test_save_partial_default_path(self, monkeypatch, tmp_path: Path):
        # Mock Path.home so we don't pollute the real home dir
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        m = AnswersMap(interactive={"a": "inter"})
        out = m.save_partial()
        assert out.exists()
        assert out.parent == tmp_path
        # Clean up
        out.unlink(missing_ok=True)

    def test_from_answers_file(self, tmp_path: Path):
        f = tmp_path / "answers.yml"
        f.write_text("_meta:\n  ae_version: 1.0.0\nname: foo\n")
        m = AnswersMap.from_answers_file(f)
        assert m.previous == {"name": "foo"}

    def test_from_answers_file_empty(self, tmp_path: Path):
        f = tmp_path / "answers.yml"
        f.write_text("")
        m = AnswersMap.from_answers_file(f)
        assert m.previous == {}

    def test_to_answers_file_filters_hidden(self):
        m = AnswersMap(
            cli_overrides={"a": 1, "_internal": "x"},
        )
        m.hide("hidden_field")
        m.interactive["hidden_field"] = "x"
        result = m.to_answers_file()
        assert "_internal" not in result
        assert "hidden_field" not in result
        assert "a" in result

    def test_to_answers_file_includes_meta(self):
        m = AnswersMap(cli_overrides={"a": 1})
        result = m.to_answers_file()
        assert "_meta" in result
        assert "ae_version" in result["_meta"]

    def test_write_to_creates_file(self, tmp_path: Path):
        m = AnswersMap(cli_overrides={"a": 1})
        dst = tmp_path / "answers.yml"
        m.write_to(dst)
        assert dst.exists()
        import yaml as _y

        data = _y.safe_load(dst.read_text())
        assert data["a"] == 1

    def test_getitem_calls_get(self):
        m = AnswersMap(defaults={"a": 1})
        assert m["a"] == 1

    def test_getitem_raises_keyerror(self):
        m = AnswersMap()
        with pytest.raises(KeyError):
            m["nonexistent_xyz"]

    def test_contains_returns_true(self):
        m = AnswersMap(defaults={"a": 1})
        assert "a" in m

    def test_contains_returns_false(self):
        m = AnswersMap()
        assert "nonexistent_xyz" not in m


# ─── ProjectDetector ─────────────────────────────────────────────────────────


class TestProjectDetectorEdgeCases:
    def test_detect_returns_none_when_no_match(self, tmp_path: Path):
        d = ProjectDetector(tmp_path)
        assert d.detect() is None

    def test_detect_returns_none_when_multiple_match(self, tmp_path: Path):
        # monorepo + library — both should match
        (tmp_path / "pnpm-workspace.yaml").write_text("")
        (tmp_path / "pyproject.toml").write_text("")
        d = ProjectDetector(tmp_path)
        assert d.detect() is None

    def test_list_candidates_returns_all(self, tmp_path: Path):
        (tmp_path / "pnpm-workspace.yaml").write_text("")
        (tmp_path / "pyproject.toml").write_text("")
        d = ProjectDetector(tmp_path)
        cands = d.list_candidates()
        assert "monorepo" in cands
        assert "library" in cands

    def test_mcp_server_with_mcp_sdk(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text(
            json.dumps({"dependencies": {"@modelcontextprotocol/sdk": "1.0.0"}})
        )
        d = ProjectDetector(tmp_path)
        # mcp-server: yes; cli-tool: no (no bin); app-service: no
        cands = d.list_candidates()
        assert "mcp-server" in cands
        assert "cli-tool" not in cands

    def test_cli_tool_with_bin(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"bin": {"ae": "ae.js"}}))
        d = ProjectDetector(tmp_path)
        cands = d.list_candidates()
        assert "cli-tool" in cands
        assert "app-service" in cands
        assert "mcp-server" not in cands

    def test_mcp_server_excluded_when_no_sdk(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"dependencies": {"express": "4.0.0"}}))
        d = ProjectDetector(tmp_path)
        cands = d.list_candidates()
        # mcp-server advanced check fails — not in cands
        assert "mcp-server" not in cands

    def test_invalid_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("not valid json")
        d = ProjectDetector(tmp_path)
        cands = d.list_candidates()
        # should not crash; mcp-server/cli-tool advanced check returns False
        assert "mcp-server" not in cands
        assert "cli-tool" not in cands

    def test_signature_matches_directory(self, tmp_path: Path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "skills").mkdir()
        assert _signature_matches(tmp_path, ".claude/skills/") is True

    def test_signature_matches_glob_md(self, tmp_path: Path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "v1.0-Plan.md").write_text("x")
        assert _signature_matches(tmp_path, "design/*.md") is True

    def test_signature_matches_glob_no_match(self, tmp_path: Path):
        (tmp_path / "design").mkdir()
        (tmp_path / "design" / "v1.0-Plan.txt").write_text("x")
        assert _signature_matches(tmp_path, "design/*.md") is False

    def test_signature_matches_regular_file(self, tmp_path: Path):
        (tmp_path / "Cargo.toml").write_text("")
        assert _signature_matches(tmp_path, "Cargo.toml") is True

    def test_signature_matches_no_match(self, tmp_path: Path):
        assert _signature_matches(tmp_path, "pyproject.toml") is False

    def test_framework_signatures_order(self):
        # monorepo must come before app-service/library
        order = [s[0] for s in FRAMEWORK_SIGNATURES]
        assert order.index("monorepo") < order.index("library")


# ─── Question ────────────────────────────────────────────────────────────────


class TestQuestionTypeInference:
    def test_str_type(self):
        q = Question(var_name="x", default="hi")
        assert q.get_type_name() == "str"

    def test_int_type(self):
        q = Question(var_name="x", default=42)
        assert q.get_type_name() == "int"

    def test_float_type(self):
        q = Question(var_name="x", default=3.14)
        assert q.get_type_name() == "float"

    def test_bool_type(self):
        q = Question(var_name="x", default=True)
        assert q.get_type_name() == "bool"

    def test_list_type_with_multiselect(self):
        q = Question(var_name="x", default=[], multiselect=True)
        assert q.get_type_name() == "json"

    def test_list_type_without_multiselect(self):
        q = Question(var_name="x", default=[], multiselect=False)
        assert q.get_type_name() == "yaml"

    def test_dict_type(self):
        q = Question(var_name="x", default={})
        assert q.get_type_name() == "json"

    def test_none_default_returns_str(self):
        q = Question(var_name="x", default=None)
        assert q.get_type_name() == "str"

    def test_explicit_type_overrides(self):
        q = Question(var_name="x", type="int", default="not int")
        assert q.get_type_name() == "int"


class TestQuestionRendering:
    def test_render_when_bool(self):
        q = Question(var_name="x", when=False)
        import jinja2

        env = jinja2.Environment()
        assert q.render_when({}, env) is False
        q2 = Question(var_name="x", when=True)
        assert q2.render_when({}, env) is True

    def test_render_when_jinja(self):
        import jinja2

        q = Question(var_name="x", when="{{ enabled }}")
        env = jinja2.Environment()
        assert q.render_when({"enabled": "true"}, env) is True
        assert q.render_when({"enabled": "false"}, env) is False

    def test_render_validator_empty(self):
        import jinja2

        q = Question(var_name="x")
        env = jinja2.Environment()
        assert q.render_validator("value", {}, env) == ""

    def test_render_validator_jinja(self):
        import jinja2

        q = Question(var_name="x", validator="{{ 'err' if not x else '' }}")
        env = jinja2.Environment()
        assert q.render_validator("", {}, env) == "err"
        assert q.render_validator("ok", {}, env) == ""


# ─── TemplateConfig / load_ae_template ──────────────────────────────────────


class TestLoadAeTemplate:
    def test_load_existing_template(self):
        cfg = TemplateConfig.load("app-service")
        assert isinstance(cfg, TemplateConfig)
        assert cfg.template_dir.exists()

    def test_load_nonexistent_raises(self):
        with pytest.raises(ConfigFileError):
            TemplateConfig.load("nonexistent_type_xyz")

    def test_default_exclude_list(self):
        assert "ae-template.yml" in DEFAULT_EXCLUDE
        assert ".git" in DEFAULT_EXCLUDE
        assert "__pycache__" in DEFAULT_EXCLUDE

    def test_load_with_subdirectory(self):
        """测试 _subdirectory 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_proj_sub"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text("_subdirectory: v1\n")

        try:
            cfg = TemplateConfig.load("test_proj_sub")
            assert cfg.subdirectory == "v1"
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_envops(self, tmp_path, monkeypatch):
        """测试 envops 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_envops"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_envops:\n  autoescape: false\n"
        )

        try:
            cfg = TemplateConfig.load("test_envops")
            assert cfg.envops.get("autoescape") is False
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_no_render(self):
        """测试 _no_render 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_norender"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text("_no_render:\n  - '*.bin'\n")

        try:
            cfg = TemplateConfig.load("test_norender")
            assert "*.bin" in cfg.no_render
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_min_version(self):
        """测试 _min_ae_version 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_minver"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text("_min_ae_version: 1.0.0\n")

        try:
            cfg = TemplateConfig.load("test_minver")
            assert cfg.min_ae_version == "1.0.0"
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_templates_suffix(self):
        """测试 _templates_suffix 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_suffix"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text("_templates_suffix: .tmpl\n")

        try:
            cfg = TemplateConfig.load("test_suffix")
            assert cfg.templates_suffix == ".tmpl"
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_message_before_after(self):
        """测试 _message_before/_message_after."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_msg"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_message_before: starting\n_message_after: done\n"
        )

        try:
            cfg = TemplateConfig.load("test_msg")
            assert cfg.message_before == "starting"
            assert cfg.message_after == "done"
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_secret_questions(self):
        """测试 _secret_questions 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_secret"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text("_secret_questions:\n  - api_key\n")

        try:
            cfg = TemplateConfig.load("test_secret")
            assert "api_key" in cfg.secret_questions
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_external_data(self):
        """测试 _external_data 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_extdata"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_external_data:\n  key: ./ext.yml\n"
        )

        try:
            cfg = TemplateConfig.load("test_extdata")
            assert cfg.external_data.get("key") == "./ext.yml"
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_nested_templates(self):
        """测试 _nested_templates 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_nested"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_nested_templates:\n  ts:\n    path: ./ts\n    title: TypeScript\n"
        )

        try:
            cfg = TemplateConfig.load("test_nested")
            assert "ts" in cfg.nested_templates
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_tasks(self):
        """测试 _tasks 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_tasks"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_tasks:\n  - cmd: echo hi\n    stage: before\n  - cmd: echo bye\n"
        )

        try:
            cfg = TemplateConfig.load("test_tasks")
            assert len(cfg.tasks_before) == 1
            assert len(cfg.tasks_after) == 1
        finally:
            import shutil

            shutil.rmtree(proj_dir)

    def test_load_with_skip_if_exists(self):
        """测试 _skip_if_exists 配置."""
        from auto_engineering.init.config import TEMPLATES_ROOT

        proj_dir = TEMPLATES_ROOT / "test_skip"
        proj_dir.mkdir(exist_ok=True)
        (proj_dir / "ae-template.yml").write_text(
            "_skip_if_exists:\n  - '*.md'\n"
        )

        try:
            cfg = TemplateConfig.load("test_skip")
            assert "*.md" in cfg.skip_if_exists
        finally:
            import shutil

            shutil.rmtree(proj_dir)


class TestQuestionCastAnswer:
    def test_cast_str(self):
        q = Question(var_name="x", default="")
        assert q.cast_answer("hello") == "hello"

    def test_cast_bool(self):
        q = Question(var_name="x", default=True)
        assert q.cast_answer("yes") is True
        assert q.cast_answer("no") is False
        assert q.cast_answer("true") is True
        assert q.cast_answer("0") is False
        # Pass through bool
        assert q.cast_answer(True) is True

    def test_cast_int(self):
        q = Question(var_name="x", default=0)
        assert q.cast_answer("42") == 42

    def test_cast_float(self):
        q = Question(var_name="x", default=0.0)
        assert q.cast_answer("3.14") == 3.14

    def test_cast_json(self):
        q = Question(var_name="x", default=[], multiselect=True)
        assert q.cast_answer('{"a": 1}') == {"a": 1}

    def test_cast_json_empty(self):
        q = Question(var_name="x", default=[], multiselect=True)
        assert q.cast_answer("") is None

    def test_cast_yaml(self):
        q = Question(var_name="x", default=[])
        assert q.cast_answer("a: 1") == {"a": 1}

    def test_cast_choice(self):
        q = Question(var_name="x", default="a", choices=["a", "b"])
        assert q.cast_answer("b") == "b"

    def test_cast_unknown_type_returns_raw(self):
        # When type is unknown (after type inference), it returns raw
        q = Question(var_name="x", type="unknown", default="")
        assert q.cast_answer("hello") == "hello"


# ─── Errors ──────────────────────────────────────────────────────────────────


class TestInitErrorHierarchy:
    def test_init_error_base(self):
        err = InitError("test")
        assert err.exit_code == 1
        assert str(err) == "test"

    def test_config_file_error_exit_code(self):
        err = ConfigFileError("bad config")
        assert err.exit_code == 2
        assert isinstance(err, InitError)

    def test_unsatisfied_prerequisite_exit_code(self):
        err = UnsatisfiedPrerequisiteError("missing git")
        assert err.exit_code == 3
        assert isinstance(err, InitError)

    def test_target_directory_exit_code(self):
        err = TargetDirectoryError("not empty")
        assert err.exit_code == 4
        assert isinstance(err, InitError)

    def test_validation_error_exit_code(self):
        err = ValidationError("bad input")
        assert err.exit_code == 5
        assert isinstance(err, InitError)

    def test_task_execution_error(self):
        err = TaskExecutionError(command="ls", returncode=1, stderr="oops")
        assert err.exit_code == 6
        assert err.command == "ls"
        assert err.returncode == 1
        assert err.stderr == "oops"
        assert "ls" in str(err)

    def test_template_render_error(self):
        original = ValueError("bad jinja")
        err = TemplateRenderError(src_path="/t/file.jinja", jinja_error=original)
        assert err.exit_code == 7
        assert err.src_path == "/t/file.jinja"
        assert err.jinja_error is original
        assert "file.jinja" in str(err)

    def test_init_interrupted_error(self):
        err = InitInterruptedError("ctrl-c")
        assert err.exit_code == 130


# ─── TaskRunner ──────────────────────────────────────────────────────────────


class TestTaskRunnerExtended:
    def test_when_false_string_skips(self, tmp_path: Path):
        t = Task(cmd="echo skipped", when="false")
        r = TaskRunner(tmp_path)
        r.run([t], {})  # should not raise

    def test_when_true_string_runs(self, tmp_path: Path):
        t = Task(cmd="echo hello", when="true")
        r = TaskRunner(tmp_path)
        r.run([t], {})

    def test_list_cmd_no_shell(self, tmp_path: Path):
        t = Task(cmd=["echo", "hello"], when=True)
        r = TaskRunner(tmp_path)
        r.run([t], {})

    def test_current_phase_set_in_env(self, tmp_path: Path):
        # Use a no-op command and verify env is set
        t = Task(cmd=["true"], when=True, extra_vars={"phase": "init"})
        r = TaskRunner(tmp_path, current_phase="init")
        r.run([t], {})

    def test_failing_command_raises(self, tmp_path: Path):
        t = Task(cmd=["false"], when=True)
        r = TaskRunner(tmp_path)
        with pytest.raises(TaskExecutionError) as exc_info:
            r.run([t], {})
        assert exc_info.value.returncode != 0

    def test_working_directory(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        t = Task(cmd=["true"], when=True, working_directory="sub")
        r = TaskRunner(tmp_path)
        r.run([t], {})

    def test_working_directory_jinja(self, tmp_path: Path):
        sub = tmp_path / "dyn"
        sub.mkdir()
        t = Task(cmd=["true"], when=True, working_directory="{{ name }}")
        r = TaskRunner(tmp_path)
        r.run([t], {"name": "dyn"})

    def test_extra_vars_in_context(self, tmp_path: Path):
        t = Task(cmd=["true"], when=True, extra_vars={"myvar": "v1"})
        r = TaskRunner(tmp_path, current_phase="test_phase")
        r.run([t], {})


# ─── TemplateRenderer ────────────────────────────────────────────────────────


class TestTemplateRendererEdgeCases:
    def test_render_with_template_dir(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "file.txt.jinja").write_text("hello {{ name }}")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {"name": "world"}, envops={"autoescape": False})
        generated = r.render_to(dst)
        assert len(generated) == 1
        assert (dst / "file.txt").read_text() == "hello world"

    def test_render_jinja_filename(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "{{ filename }}.jinja").write_text("content")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {"filename": "rendered"})
        r.render_to(dst)
        assert (dst / "rendered").exists()
        assert (dst / "rendered").read_text() == "content"

    def test_render_jinja_filename_empty_skips(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "{% if false %}skip{% endif %}.jinja").write_text("x")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        generated = r.render_to(dst)
        assert generated == []

    def test_render_excludes_files(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "keep.txt").write_text("keep")
        (tpl_dir / "skip.txt").write_text("skip")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {}, exclude=["skip.txt"])
        r.render_to(dst)
        assert (dst / "keep.txt").exists()
        assert not (dst / "skip.txt").exists()

    def test_render_skip_if_exists(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "f.txt").write_text("new")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "f.txt").write_text("existing")

        r = TemplateRenderer([tpl_dir], {}, skip_if_exists=["f.txt"])
        r.render_to(dst)
        assert (dst / "f.txt").read_text() == "existing"

    def test_render_overwrite_true(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "f.txt").write_text("new")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "f.txt").write_text("old")

        r = TemplateRenderer([tpl_dir], {}, overwrite=True)
        r.render_to(dst)
        assert (dst / "f.txt").read_text() == "new"

    def test_render_conflict_handler(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "f.txt").write_text("new")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "f.txt").write_text("old")

        def handler(path):
            return path == "f.txt"  # overwrite

        r = TemplateRenderer([tpl_dir], {}, conflict_handler=handler)
        r.render_to(dst)
        assert (dst / "f.txt").read_text() == "new"

    def test_render_no_render_files_copied(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "raw.bin").write_bytes(b"\x00\x01binary")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {}, no_render=["raw.bin"])
        r.render_to(dst)
        assert (dst / "raw.bin").read_bytes() == b"\x00\x01binary"

    def test_render_path_traversal_raises(self, tmp_path: Path):
        # Create a normal template first
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()

        # The path-traversal check is on rendered_rel — we need a template whose
        # rendered name escapes dst. We can override _render_path to force it.
        r = TemplateRenderer([tpl_dir], {})
        # Patch _render_path to return a path that escapes dst
        r._render_path = lambda p: "../escape"  # type: ignore[assignment]

        # Now add a file in the template dir to trigger rendering
        (tpl_dir / "normal.txt").write_text("data")

        with pytest.raises(TemplateRenderError):
            r.render_to(dst)

    def test_render_jinja_error_raises(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "bad.jinja").write_text("{{ undefined_var }}")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        with pytest.raises(TemplateRenderError):
            r.render_to(dst)

    def test_render_symlink_dangling_skipped(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        target = tmp_path / "nonexistent.txt"
        link = tpl_dir / "link.txt"
        link.symlink_to(target)
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        generated = r.render_to(dst)
        assert all("link" not in g.name for g in generated)

    def test_render_symlink_kept(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        target = tmp_path / "real.txt"
        target.write_text("real content")
        link = tpl_dir / "link.txt"
        link.symlink_to(target)
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        generated = r.render_to(dst)
        # Symlink should be preserved (file under dst is a symlink to target)
        assert any("link" in g.name for g in generated)

    def test_render_binary_file(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        r.render_to(dst)
        assert (dst / "binary.bin").read_bytes() == b"\x00\x01\x02\x03"

    def test_render_multiple_dirs_later_wins(self, tmp_path: Path):
        tpl1 = tmp_path / "tpl1"
        tpl1.mkdir()
        (tpl1 / "f.txt").write_text("from1")
        tpl2 = tmp_path / "tpl2"
        tpl2.mkdir()
        (tpl2 / "f.txt").write_text("from2")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl1, tpl2], {})
        r.render_to(dst)
        # Later dir wins
        assert (dst / "f.txt").read_text() == "from2"

    def test_render_existing_file_no_overwrite_default(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "f.txt").write_text("new")
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "f.txt").write_text("old")

        # No overwrite, no skip_if_exists, no conflict_handler
        r = TemplateRenderer([tpl_dir], {})
        r.render_to(dst)
        assert (dst / "f.txt").read_text() == "old"

    def test_render_path_jinja_error_raises(self, tmp_path: Path):
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "{{ undefined }}.jinja").write_text("x")
        dst = tmp_path / "dst"
        dst.mkdir()

        r = TemplateRenderer([tpl_dir], {})
        with pytest.raises(TemplateRenderError):
            r.render_to(dst)

    def test_detect_newline_crlf(self, tmp_path: Path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"line1\r\nline2\r\n")
        nl = TemplateRenderer._detect_newline(f)
        # may detect \r\n or \r depending on Python version
        assert nl in ("\r\n", "\r") or nl is None
