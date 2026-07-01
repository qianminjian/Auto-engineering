"""Tests for ToolRegistry — Phase 3 C3b.

设计: design/LOOP-DEVELOPMENT-PLAN.md Phase 3 文件 13.

ToolRegistry:
- register(tool): add tool indexed by name
- get(name): retrieve tool
- list_tools(): all registered
- to_schemas(): list of Anthropic tool_use schemas
"""

from __future__ import annotations

import pytest


class _Echo:
    """最小 BaseTool-like stub for testing."""

    def __init__(self, name="echo", description="Echo input"):
        from auto_engineering.tools.base import BaseTool, ToolResult

        self.name = name
        self.description = description
        self.parameters = {"text": "string"}
        self._BaseTool = BaseTool
        self._ToolResult = ToolResult

    def execute(self, text: str):
        return self._ToolResult(success=True, content=text)

    def to_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {"text": "string"},
                "required": ["text"],
            },
        }


class TestToolRegistry:
    """ToolRegistry — 工具注册表."""

    def test_register_and_get(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        tool = _Echo()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_register_duplicate_name_raises(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_Echo())  # 同名再次注册

    def test_get_unknown_returns_none(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_list_tools_returns_all(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        echo = _Echo(name="echo")
        calc = _Echo(name="calc")
        reg.register(echo)
        reg.register(calc)
        tools = reg.list_tools()
        assert echo in tools
        assert calc in tools
        assert len(tools) == 2

    def test_to_schemas_returns_anthropic_format(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="echo"))
        schemas = reg.to_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "echo"
        assert "input_schema" in schemas[0]

    def test_to_schemas_empty_registry(self):
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.to_schemas() == []


class TestToolRegistryResolve:
    """Phase 10: resolve() 边界 (找不到抛 KeyError)."""

    def test_resolve_single_tool(self):
        """resolve(['echo']) → [Echo] 单元素列表."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        echo = _Echo(name="echo")
        reg.register(echo)
        result = reg.resolve(["echo"])
        assert result == [echo]

    def test_resolve_multiple_tools_preserves_order(self):
        """resolve([a, b]) → 保持入参顺序."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        a = _Echo(name="a")
        b = _Echo(name="b")
        c = _Echo(name="c")
        for t in (a, b, c):
            reg.register(t)
        result = reg.resolve(["c", "a", "b"])  # 入参顺序
        assert result == [c, a, b]

    def test_resolve_empty_list_returns_empty(self):
        """resolve([]) → [] 空列表 (无错误)."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.resolve([]) == []

    def test_resolve_unknown_tool_raises_keyerror(self):
        """resolve 含未注册名 → KeyError 含 name."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="echo"))
        with pytest.raises(KeyError, match="missing_tool"):
            reg.resolve(["echo", "missing_tool"])

    def test_resolve_all_unknown_raises_on_first(self):
        """resolve 全部未注册 → 第一个未注册抛 KeyError."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        with pytest.raises(KeyError):
            reg.resolve(["nonexistent_1", "nonexistent_2"])


class TestToolRegistryDuplicates:
    """Phase 10: 重复注册边界."""

    def test_register_duplicate_error_includes_name(self):
        """重复注册 → ValueError 含工具名 (便于调试)."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="my_tool"))
        with pytest.raises(ValueError) as exc_info:
            reg.register(_Echo(name="my_tool"))
        # 错误消息应含工具名
        assert "my_tool" in str(exc_info.value)
        assert "already registered" in str(exc_info.value)

    def test_register_overwrite_is_not_allowed(self):
        """register() 不允许覆盖已有工具 (防御性).

        设计意图: 避免子模块意外覆盖核心工具, 强制显式重命名.
        """
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        first = _Echo(name="dup")
        second = _Echo(name="dup")
        reg.register(first)
        with pytest.raises(ValueError):
            reg.register(second)
        # 第一个实例保留
        assert reg.get("dup") is first


class TestToolRegistrySchemas:
    """Phase 10: to_schemas 转换 + 真实 BaseTool."""

    def test_to_schemas_for_real_base_tool(self):
        """to_schemas() 对真实 BaseTool 也能转换 (e.g. ReadFileTool)."""
        from auto_engineering.tools.file_tools import ReadFileTool
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(ReadFileTool())
        schemas = reg.to_schemas()
        assert len(schemas) == 1
        s = schemas[0]
        assert s["name"] == "read_file"  # ReadFileTool.name
        assert "description" in s
        assert "input_schema" in s
        # input_schema 字段
        assert s["input_schema"]["type"] == "object"
        assert "properties" in s["input_schema"]
        assert "file_path" in s["input_schema"]["properties"]

    def test_to_schemas_preserves_insertion_order(self):
        """to_schemas 输出保持注册顺序 (LLM tool_use 调用匹配)."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        names = ["alpha", "beta", "gamma", "delta"]
        for n in names:
            reg.register(_Echo(name=n))
        schemas = reg.to_schemas()
        schema_names = [s["name"] for s in schemas]
        assert schema_names == names

    def test_to_schemas_each_has_required_field(self):
        """每个 schema 的 input_schema.required 含 parameters 全部 key."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="multi_param"))

        # 扩展 _Echo 支持多参数 (本测试场景)
        class _MultiParam:
            name = "multi"
            description = "Multi param"
            parameters = {"x": "integer", "y": "string", "z": "boolean"}

            def to_schema(self):
                return {
                    "name": self.name,
                    "description": self.description,
                    "input_schema": {
                        "type": "object",
                        "properties": self.parameters,
                        "required": list(self.parameters.keys()),
                    },
                }

        reg2 = ToolRegistry()
        reg2.register(_MultiParam())
        s = reg2.to_schemas()[0]
        assert sorted(s["input_schema"]["required"]) == ["x", "y", "z"]


class TestToolRegistryDefaults:
    """Phase 10: default_registry() 含 10 个内置工具."""

    def test_default_registry_has_10_tools(self):
        """default_registry() 注册 10 个内置工具."""
        from auto_engineering.tools.registry import default_registry

        reg = default_registry()
        assert len(reg.list_tools()) == 10

    def test_default_registry_includes_all_expected_tools(self):
        """default_registry 含全部预期工具 (按 name)."""
        from auto_engineering.tools.registry import default_registry

        reg = default_registry()
        tool_names = {t.name for t in reg.list_tools()}
        expected = {
            "read_file", "write_file", "edit_file",
            "search_code", "list_dir",
            "run_bash",
            "git_status", "git_commit", "git_diff",
            "run_tests",
        }
        assert tool_names == expected, (
            f"default_registry 工具集合不匹配. "
            f"缺失: {expected - tool_names}, 多余: {tool_names - expected}"
        )

    def test_default_registry_no_duplicate_names(self):
        """default_registry 10 工具无重名 (register 内部验证)."""
        from auto_engineering.tools.registry import default_registry

        # 构造过程中如有重名会抛 ValueError
        reg = default_registry()  # 不抛即通过
        tool_names = [t.name for t in reg.list_tools()]
        assert len(tool_names) == len(set(tool_names))  # 全唯一

    def test_default_registry_resolve_all(self):
        """default_registry.resolve(全部 name) 成功, 顺序匹配."""
        from auto_engineering.tools.registry import default_registry

        reg = default_registry()
        all_names = [t.name for t in reg.list_tools()]
        resolved = reg.resolve(all_names)
        assert len(resolved) == 10
        # 顺序匹配
        assert [t.name for t in resolved] == all_names

    def test_default_registry_to_schemas_count_matches(self):
        """to_schemas 输出数量 = list_tools 数量."""
        from auto_engineering.tools.registry import default_registry

        reg = default_registry()
        assert len(reg.to_schemas()) == len(reg.list_tools()) == 10


class TestToolRegistryIsolation:
    """Phase 10: 多 registry 实例隔离."""

    def test_two_registries_are_independent(self):
        """两个 ToolRegistry 实例互不影响."""
        from auto_engineering.tools.registry import ToolRegistry

        reg1 = ToolRegistry()
        reg2 = ToolRegistry()
        reg1.register(_Echo(name="reg1_tool"))
        assert reg1.get("reg1_tool") is not None
        assert reg2.get("reg1_tool") is None  # reg2 无

    def test_clear_registry_by_recreate(self):
        """ToolRegistry 无 clear 方法 — 用新建实例模拟清空."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(_Echo(name="x"))
        assert reg.get("x") is not None

        reg_new = ToolRegistry()
        assert reg_new.get("x") is None  # 新实例无

    def test_registry_with_zero_tools_schemas_empty(self):
        """零工具 registry: list_tools() / to_schemas() / resolve() 全为空."""
        from auto_engineering.tools.registry import ToolRegistry

        reg = ToolRegistry()
        assert reg.list_tools() == []
        assert reg.to_schemas() == []
        assert reg.resolve([]) == []
