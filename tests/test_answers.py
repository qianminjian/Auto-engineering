"""Tests for AnswersMap — 6 层优先级答案解析."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from auto_engineering.init.answers import BUILTIN_VARS, AnswersMap, _LazyExternalDict


class TestBuiltinVars:
    """BUILTIN_VARS 常量."""

    def test_has_ae_version(self):
        assert BUILTIN_VARS["_ae_version"] == "1.0.0"

    def test_is_dict(self):
        assert isinstance(BUILTIN_VARS, dict)


class TestAnswersMapConstruction:
    """构造与默认值."""

    def test_default_construction(self):
        am = AnswersMap()
        assert am.cli_overrides == {}
        assert am.interactive == {}
        assert am.previous == {}
        assert am.defaults == {}
        assert am.builtins == BUILTIN_VARS
        assert am.external == {}
        assert am.hidden == set()
        # _external_cache 是 init=False 的 field，也应存在
        assert am._external_cache == {}

    def test_construction_with_layers(self):
        am = AnswersMap(
            cli_overrides={"name": "cli"},
            interactive={"name": "interactive"},
            previous={"name": "previous"},
            defaults={"name": "defaults"},
            builtins={"name": "builtins"},
            external={"ext_key": "/tmp/data.yml"},
            hidden={"secret"},
        )
        assert am.cli_overrides["name"] == "cli"
        assert am.interactive["name"] == "interactive"
        assert am.previous["name"] == "previous"
        assert am.defaults["name"] == "defaults"
        assert am.builtins["name"] == "builtins"
        assert am.external["ext_key"] == "/tmp/data.yml"
        assert am.hidden == {"secret"}

    def test_builtins_is_independent_copy(self):
        """每个 AnswersMap 实例有独立的 builtins 副本."""
        am1 = AnswersMap()
        am2 = AnswersMap()
        am1.builtins["_custom"] = "only_in_am1"
        assert "_custom" not in am2.builtins


class TestGet:
    """get() 优先级查找."""

    def test_cli_overrides_highest_priority(self):
        am = AnswersMap(
            cli_overrides={"name": "cli"},
            interactive={"name": "interactive"},
            previous={"name": "previous"},
            defaults={"name": "defaults"},
            builtins={"name": "builtins"},
        )
        assert am.get("name") == "cli"

    def test_interactive_over_previous(self):
        am = AnswersMap(
            interactive={"name": "interactive"},
            previous={"name": "previous"},
            defaults={"name": "defaults"},
            builtins={"name": "builtins"},
        )
        assert am.get("name") == "interactive"

    def test_previous_over_defaults(self):
        am = AnswersMap(
            previous={"name": "previous"},
            defaults={"name": "defaults"},
            builtins={"name": "builtins"},
        )
        assert am.get("name") == "previous"

    def test_defaults_over_builtins(self):
        am = AnswersMap(
            defaults={"name": "defaults"},
            builtins={"name": "builtins"},
        )
        assert am.get("name") == "defaults"

    def test_builtins_as_last_resort(self):
        am = AnswersMap(builtins={"_ae_version": "1.0.0"})
        assert am.get("_ae_version") == "1.0.0"

    def test_skips_none_values_in_layer(self):
        """None 值的键视为"未设置"，继续查找下一层."""
        am = AnswersMap(
            cli_overrides={"name": None},
            interactive={"name": "interactive"},
        )
        assert am.get("name") == "interactive"

    def test_external_fallback_when_not_in_layers(self):
        """external 中的 key 在所有层都找不到时，通过 _load_external 懒加载 YAML 文件内容."""
        am = AnswersMap(
            external={"data_key": "/tmp/test_data.yml"},
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump("external_value", f)
            tmp_path = f.name
        try:
            am.external["data_key"] = tmp_path
            am._external_cache = {}
            assert am.get("data_key") == "external_value"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_raises_keyerror_when_not_found(self):
        am = AnswersMap()
        with pytest.raises(KeyError):
            am.get("nonexistent")

    def test_external_takes_precedence_over_raises(self):
        """external 中的 key 如果在所有层都找不到，会尝试 external."""
        am = AnswersMap(external={"ext": "/tmp/ext.yml"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(42, f)
            tmp_path = f.name
        try:
            am.external["ext"] = tmp_path
            am._external_cache = {}
            assert am.get("ext") == 42
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestCombined:
    """combined() 全量合并."""

    def test_merges_all_layers(self):
        am = AnswersMap(
            cli_overrides={"a": 1},
            interactive={"b": 2},
            previous={"c": 3},
            defaults={"d": 4},
            builtins={"e": 5},
        )
        result = am.combined()
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3
        assert result["d"] == 4
        assert result["e"] == 5

    def test_higher_priority_overrides_lower(self):
        am = AnswersMap(
            cli_overrides={"x": "cli"},
            defaults={"x": "default"},
        )
        result = am.combined()
        assert result["x"] == "cli"

    def test_no_external_data_key_when_no_external(self):
        am = AnswersMap()
        result = am.combined()
        assert "_external_data" not in result

    def test_injects_lazy_external_data_when_external_present(self):
        am = AnswersMap(external={"key1": "/tmp/data.yml"})
        result = am.combined()
        assert "_external_data" in result
        assert isinstance(result["_external_data"], _LazyExternalDict)

    def test_external_data_is_lazy(self):
        """_external_data 应当是一个 lazy-loading 对象，不在 combined() 时就加载所有文件."""
        am = AnswersMap(external={"key1": "/nonexistent/path.yml"})
        result = am.combined()
        ext_data = result["_external_data"]
        # 确认是 lazy 对象（不是普通 dict）
        assert isinstance(ext_data, _LazyExternalDict)
        # 确认尚未加载（_cache 为空）
        assert ext_data._cache == {}

    def test_lazy_external_data_loads_on_access(self):
        am = AnswersMap(external={"key1": "/tmp/test.yml"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"name": "lazy_loaded"}, f)
            tmp_path = f.name
        try:
            am.external["key1"] = tmp_path
            result = am.combined()
            ext_data = result["_external_data"]
            # 初次访问触发加载
            value = ext_data["key1"]
            assert value == {"name": "lazy_loaded"}
            # 确认已缓存
            assert "key1" in ext_data._cache
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestLoadExternal:
    """_load_external() 懒加载."""

    def test_loads_yaml_file(self):
        am = AnswersMap(external={"key": "/tmp/test.yaml"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"nested": {"value": 99}}, f)
            tmp_path = f.name
        try:
            am.external["key"] = tmp_path
            am._external_cache = {}
            result = am._load_external("key")
            assert result == {"nested": {"value": 99}}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_caches_result(self):
        am = AnswersMap(external={"key": "/tmp/test.yaml"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"data": "original"}, f)
            tmp_path = f.name
        try:
            am.external["key"] = tmp_path
            am._external_cache = {}
            # 第一次调用：加载并缓存
            result1 = am._load_external("key")
            assert result1 == {"data": "original"}
            # 修改文件（模拟外部变化），但缓存应返回旧值
            Path(tmp_path).write_text(yaml.dump({"data": "changed"}))
            result2 = am._load_external("key")
            assert result2 == {"data": "original"}  # 缓存没变
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_returns_none_for_missing_file(self):
        am = AnswersMap(external={"key": "/nonexistent/file.yml"})
        am._external_cache = {}
        result = am._load_external("key")
        assert result is None

    def test_caches_none_for_missing_file(self):
        am = AnswersMap(external={"key": "/nonexistent/file.yml"})
        am._external_cache = {}
        am._load_external("key")
        am._load_external("key")
        # 确认只缓存了一次（None 也被缓存）
        assert "key" in am._external_cache
        assert am._external_cache["key"] is None


class TestHide:
    """hide() 标记敏感字段."""

    def test_adds_key_to_hidden_set(self):
        am = AnswersMap()
        am.hide("secret_key")
        assert "secret_key" in am.hidden

    def test_multiple_hides(self):
        am = AnswersMap()
        am.hide("a")
        am.hide("b")
        assert am.hidden == {"a", "b"}


class TestSavePartial:
    """save_partial() 保存部分答案."""

    def test_saves_interactive_with_meta(self):
        am = AnswersMap(interactive={"name": "test_project", "type": "app"})
        with tempfile.NamedTemporaryFile(mode="r", suffix=".yml", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            result = am.save_partial(path=tmp_path)
            assert result == tmp_path
            data = yaml.safe_load(tmp_path.read_text())
            assert data["name"] == "test_project"
            assert data["type"] == "app"
            assert data["_meta"]["partial"] is True
            assert "saved_at" in data["_meta"]
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_default_path_is_home_partial(self):
        am = AnswersMap(interactive={"key": "value"})
        with (
            patch.object(Path, "home", return_value=Path("/tmp")),
            patch.object(Path, "write_text") as mock_write,
        ):
            result = am.save_partial()
            assert result == Path("/tmp/.ae-partial-answers.yml")
            mock_write.assert_called_once()


class TestFromAnswersFile:
    """from_answers_file() 类方法."""

    def test_loads_previous_layer(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"name": "from_file", "version": "1.0"}, f)
            tmp_path = Path(f.name)
        try:
            am = AnswersMap.from_answers_file(tmp_path)
            assert am.previous["name"] == "from_file"
            assert am.previous["version"] == "1.0"
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_pops_meta_from_data(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"_meta": {"ae_version": "1.0.0"}, "name": "proj"}, f)
            tmp_path = Path(f.name)
        try:
            am = AnswersMap.from_answers_file(tmp_path)
            assert "name" in am.previous
            assert "_meta" not in am.previous
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_handles_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("")
            tmp_path = Path(f.name)
        try:
            am = AnswersMap.from_answers_file(tmp_path)
            assert am.previous == {}
        finally:
            tmp_path.unlink(missing_ok=True)


class TestToAnswersFile:
    """to_answers_file() 生成 .ae-answers.yml 数据."""

    def test_filters_underscore_prefixed_keys(self):
        am = AnswersMap(
            cli_overrides={"name": "test"},
            builtins={"_ae_version": "1.0.0"},
        )
        result = am.to_answers_file()
        assert "name" in result
        assert "_ae_version" not in result

    def test_filters_hidden_keys(self):
        am = AnswersMap(
            cli_overrides={"name": "test", "secret": "hidden_val"},
            hidden={"secret"},
        )
        result = am.to_answers_file()
        assert "name" in result
        assert "secret" not in result

    def test_includes_meta(self):
        am = AnswersMap(
            cli_overrides={"name": "test"},
            builtins={"_ae_version": "1.0.0"},
        )
        result = am.to_answers_file()
        assert "_meta" in result
        assert result["_meta"]["ae_version"] == "1.0.0"
        assert "created_at" in result["_meta"]

    def test_only_includes_serializable_types(self):
        """只包含基本类型的值."""
        am = AnswersMap(cli_overrides={"name": "test"})

        class CustomObj:
            pass

        am.interactive["custom"] = CustomObj()
        result = am.to_answers_file()
        assert "custom" not in result
        assert "name" in result


class TestWriteTo:
    """write_to() 写入 .ae-answers.yml."""

    def test_writes_to_file(self):
        am = AnswersMap(
            cli_overrides={"name": "test-project"},
            builtins={"_ae_version": "1.0.0"},
        )
        with tempfile.NamedTemporaryFile(mode="r", suffix=".yml", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            am.write_to(tmp_path)
            data = yaml.safe_load(tmp_path.read_text())
            assert data["name"] == "test-project"
            assert "_meta" in data
        finally:
            tmp_path.unlink(missing_ok=True)


class TestDictLikeAccess:
    """__getitem__ / __contains__ 字典式访问."""

    def test_getitem_delegates_to_get(self):
        am = AnswersMap(cli_overrides={"key": "value"})
        assert am["key"] == "value"

    def test_getitem_raises_keyerror(self):
        am = AnswersMap()
        with pytest.raises(KeyError):
            _ = am["nonexistent"]

    def test_contains_returns_true(self):
        am = AnswersMap(cli_overrides={"key": "value"})
        assert "key" in am

    def test_contains_returns_false(self):
        am = AnswersMap()
        assert "nonexistent" not in am

    def test_contains_with_external(self):
        am = AnswersMap(external={"ext": "/tmp/ext.yml"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"ext": 123}, f)
            tmp_path = f.name
        try:
            am.external["ext"] = tmp_path
            am._external_cache = {}
            assert "ext" in am
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestLazyExternalDict:
    """_LazyExternalDict 类."""

    def test_init_with_external_map(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml", "b": "/tmp/b.yml"})
        assert d._external_map == {"a": "/tmp/a.yml", "b": "/tmp/b.yml"}
        assert d._cache == {}

    def test_contains(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml"})
        assert "a" in d
        assert "b" not in d

    def test_len(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml", "b": "/tmp/b.yml"})
        assert len(d) == 2

    def test_iter_yields_keys(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml", "b": "/tmp/b.yml"})
        assert set(d) == {"a", "b"}

    def test_keys(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml"})
        assert set(d.keys()) == {"a"}

    def test_getitem_loads_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"data": "yaml_value"}, f)
            tmp_path = f.name
        try:
            d = _LazyExternalDict({"key": tmp_path})
            result = d["key"]
            assert result == {"data": "yaml_value"}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_getitem_returns_none_for_missing_file(self):
        d = _LazyExternalDict({"key": "/nonexistent/file.yml"})
        result = d["key"]
        assert result is None

    def test_getitem_caches(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"data": "first"}, f)
            tmp_path = f.name
        try:
            d = _LazyExternalDict({"key": tmp_path})
            result1 = d["key"]
            assert result1 == {"data": "first"}
            # 修改文件，缓存仍返回旧值
            Path(tmp_path).write_text(yaml.dump({"data": "second"}))
            result2 = d["key"]
            assert result2 == {"data": "first"}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_items_lazy_loads(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"x": 1}, f)
            tmp_path = f.name
        try:
            d = _LazyExternalDict({"key": tmp_path})
            items = list(d.items())
            assert len(items) == 1
            assert items[0][0] == "key"
            assert items[0][1] == {"x": 1}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_getitem_loads_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"json_key": [1, 2, 3]}, f)
            tmp_path = f.name
        try:
            d = _LazyExternalDict({"key": tmp_path})
            result = d["key"]
            assert result == {"json_key": [1, 2, 3]}
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_getitem_other_suffix_falls_back_to_yaml(self):
        """非 .yml/.yaml/.json 后缀文件，降级用 yaml.safe_load."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            yaml.dump("fallback_value", f)
            tmp_path = f.name
        try:
            d = _LazyExternalDict({"key": tmp_path})
            result = d["key"]
            assert result == "fallback_value"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_repr(self):
        d = _LazyExternalDict({"a": "/tmp/a.yml", "b": "/tmp/b.yml"})
        r = repr(d)
        assert "_LazyExternalDict" in r
