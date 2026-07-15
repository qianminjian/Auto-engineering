"""Tests for PrismScan extract.py — tree-sitter 符号提取."""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from auto_engineering.prismscan.schemas import SymbolInfo


class TestParseAST:
    """parse_ast() 符号提取."""

    def test_extracts_class_symbol(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {
                    "type": "class_declaration",
                    "name": "MyClass",
                    "line": 10,
                    "children": [
                        {
                            "type": "method_declaration",
                            "name": "my_method",
                            "line": 12,
                        }
                    ],
                }
            ],
        }
        symbols = parse_ast(json.dumps(ast), "src/my_class.py")
        names = [s.name for s in symbols]
        assert "MyClass" in names
        kinds = {s.name: s.kind for s in symbols}
        assert kinds.get("MyClass") == "class"
        assert kinds.get("my_method") == "method"

    def test_extracts_function_symbol(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {
                    "type": "function_declaration",
                    "name": "my_function",
                    "line": 5,
                }
            ],
        }
        symbols = parse_ast(json.dumps(ast), "src/utils.py")
        assert len(symbols) == 1
        assert symbols[0].name == "my_function"
        assert symbols[0].kind == "function"
        assert symbols[0].line == 5
        assert symbols[0].file == "src/utils.py"

    def test_handles_empty_ast(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {"type": "program", "children": []}
        symbols = parse_ast(json.dumps(ast), "empty.py")
        assert symbols == []

    def test_handles_malformed_json(self):
        from auto_engineering.prismscan.extract import parse_ast

        symbols = parse_ast("not valid json", "bad.py")
        assert symbols == []


class TestDeduplicate:
    """deduplicate() 去重逻辑."""

    def test_deduplicates_by_name_file_kind(self):
        from auto_engineering.prismscan.extract import deduplicate
        from auto_engineering.prismscan.schemas import SymbolInfo

        symbols = [
            SymbolInfo(name="Foo", kind="class", file="a.py", line=10),
            SymbolInfo(name="Foo", kind="class", file="a.py", line=10),
            SymbolInfo(name="Bar", kind="function", file="a.py", line=20),
        ]
        result = deduplicate(symbols)
        assert len(result) == 2
        names = {s.name for s in result}
        assert names == {"Foo", "Bar"}


class TestBuildDependencyGraph:
    """build_dependency_graph() 依赖边."""

    def test_builds_graph_from_imports(self):
        from auto_engineering.prismscan.extract import build_dependency_graph
        from auto_engineering.prismscan.schemas import SymbolInfo

        symbols = [
            SymbolInfo(name="main", kind="function", file="main.py", line=1,
                       scope='import os\nfrom core import Client'),
            SymbolInfo(name="Client", kind="class", file="core.py", line=1),
        ]
        graph = build_dependency_graph(symbols)
        assert "main" in graph
        assert "Client" in graph["main"]

    def test_filters_unresolved_deps(self):
        from auto_engineering.prismscan.extract import build_dependency_graph
        from auto_engineering.prismscan.schemas import SymbolInfo

        symbols = [
            SymbolInfo(name="main", kind="function", file="main.py", line=1,
                       scope='from external_lib import Helper'),
        ]
        graph = build_dependency_graph(symbols)
        assert "main" in graph
        assert "Helper" not in graph["main"]

    def test_empty_symbols_graph(self):
        from auto_engineering.prismscan.extract import build_dependency_graph

        graph = build_dependency_graph([])
        assert graph == {}

    def test_deduplicate_empty_list(self):
        from auto_engineering.prismscan.extract import deduplicate

        assert deduplicate([]) == []

    def test_deduplicate_all_unique(self):
        from auto_engineering.prismscan.extract import deduplicate
        from auto_engineering.prismscan.schemas import SymbolInfo

        symbols = [
            SymbolInfo(name="A", kind="class", file="a.py", line=1),
            SymbolInfo(name="B", kind="class", file="a.py", line=2),
            SymbolInfo(name="A", kind="function", file="a.py", line=3),
        ]
        result = deduplicate(symbols)
        assert len(result) == 3  # 不同 name/kind 组合均为 unique


class TestExtractImports:
    """_extract_imports() import 语句解析."""

    def test_parses_import_x_syntax(self):
        from auto_engineering.prismscan.extract import _extract_imports
        from auto_engineering.prismscan.schemas import SymbolInfo

        s = SymbolInfo(name="main", kind="function", file="main.py", line=1,
                       scope="import os\nimport sys, json")
        deps = _extract_imports(s)
        assert "os" in deps
        assert "sys" in deps
        assert "json" in deps

    def test_parses_from_x_import_y_with_alias(self):
        from auto_engineering.prismscan.extract import _extract_imports
        from auto_engineering.prismscan.schemas import SymbolInfo

        s = SymbolInfo(name="main", kind="function", file="main.py", line=1,
                       scope="from core import Client as C")
        deps = _extract_imports(s)
        assert "Client" in deps  # actual symbol name
        assert "core" in deps    # module name

    def test_empty_scope_returns_empty(self):
        from auto_engineering.prismscan.extract import _extract_imports
        from auto_engineering.prismscan.schemas import SymbolInfo

        s = SymbolInfo(name="main", kind="function", file="main.py", line=1)
        deps = _extract_imports(s)
        assert deps == []

    def test_none_scope_returns_empty(self):
        from auto_engineering.prismscan.extract import _extract_imports
        from auto_engineering.prismscan.schemas import SymbolInfo

        s = SymbolInfo(name="main", kind="function", file="main.py", line=1, scope="")
        deps = _extract_imports(s)
        assert deps == []


class TestParseFileErrors:
    """S1.5: _parse_file() tree-sitter 错误分支 — 优雅降级."""

    def test_tree_sitter_not_installed_returns_empty(self):
        from auto_engineering.prismscan.extract import _parse_file

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            result = _parse_file("dummy.py")
            assert result == []

    def test_tree_sitter_nonzero_exit_returns_empty(self):
        from auto_engineering.prismscan.extract import _parse_file

        fake_result = mock.Mock()
        fake_result.returncode = 1
        fake_result.stderr = "parse error"
        with mock.patch("subprocess.run", return_value=fake_result):
            result = _parse_file("dummy.py")
            assert result == []

    def test_tree_sitter_timeout_returns_empty(self):
        from auto_engineering.prismscan.extract import _parse_file

        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("npx", 30)):
            result = _parse_file("dummy.py")
            assert result == []

    def test_tree_sitter_os_error_returns_empty(self):
        from auto_engineering.prismscan.extract import _parse_file

        with mock.patch("subprocess.run", side_effect=OSError("no such process")):
            result = _parse_file("dummy.py")
            assert result == []


class TestParseASTEdgeCases:
    """parse_ast() 边界条件."""

    def test_interface_struct_enum_variable_module_kinds(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {"type": "interface_declaration", "name": "IMyInterface", "line": 1},
                {"type": "struct_declaration", "name": "MyStruct", "line": 5},
                {"type": "enum_declaration", "name": "MyEnum", "line": 10},
                {"type": "variable_declaration", "name": "my_var", "line": 15},
                {"type": "module", "name": "my_module", "line": 1},
            ],
        }
        symbols = parse_ast(json.dumps(ast), "types.rs")
        kinds = {s.name: s.kind for s in symbols}
        assert kinds["IMyInterface"] == "interface"
        assert kinds["MyStruct"] == "struct"
        assert kinds["MyEnum"] == "enum"
        assert kinds["my_var"] == "variable"
        assert kinds["my_module"] == "module"

    def test_unknown_node_type_skipped(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {"type": "unknown_thing", "name": "x", "line": 1},
                {"type": "class_declaration", "name": "RealClass", "line": 2},
            ],
        }
        symbols = parse_ast(json.dumps(ast), "test.py")
        assert len(symbols) == 1
        assert symbols[0].name == "RealClass"

    def test_node_without_name_skipped(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {"type": "class_declaration", "line": 1},
                {"type": "function_declaration", "name": "real_func", "line": 3},
            ],
        }
        symbols = parse_ast(json.dumps(ast), "test.py")
        assert len(symbols) == 1
        assert symbols[0].name == "real_func"

    def test_deeply_nested_ast(self):
        from auto_engineering.prismscan.extract import parse_ast

        ast = {
            "type": "program",
            "children": [
                {"type": "class_declaration", "name": "Outer", "line": 1,
                 "children": [
                     {"type": "method_declaration", "name": "method1", "line": 2,
                      "children": [
                          {"type": "class_declaration", "name": "Inner", "line": 3,
                           "children": [
                               {"type": "method_declaration", "name": "inner_method", "line": 4}
                           ]}
                      ]}
                 ]}
            ],
        }
        symbols = parse_ast(json.dumps(ast), "nested.py")
        names = {s.name for s in symbols}
        assert names == {"Outer", "method1", "Inner", "inner_method"}
