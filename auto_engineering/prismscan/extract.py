"""PrismScan V5.1 — Extract: tree-sitter 符号提取 + 依赖图构建.

确定性计算, 不涉及 LLM.
输入: ProjectShape
输出: SymbolIndex (symbols + dependency_graph)

策略:
  - 优先: subprocess tree-sitter CLI (npx tree-sitter parse --json)
  - 降级: Python AST 模块 (ast, 标准库, 零外部依赖)
  - 兜底: regex 模式匹配
"""

from __future__ import annotations

import ast as _ast
import json
import logging
import re
import subprocess
from pathlib import Path

from auto_engineering.prismscan.schemas import ProjectShape, SymbolIndex, SymbolInfo

_logger = logging.getLogger("ae.prismscan.extract")

_TREE_SITTER_KINDS: dict[str, str] = {
    "class_declaration": "class",
    "function_declaration": "function",
    "method_declaration": "method",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "variable_declaration": "variable",
    "module": "module",
}


def _parse_file(filepath: str | Path) -> list[SymbolInfo]:
    """通过 subprocess 调用 tree-sitter 解析单个文件.

    错误处理: tree-sitter 未安装 / 非零退出 / 超时 / OS 错误 → 返回空列表（优雅降级）.
    """
    fp = str(filepath)
    try:
        result = subprocess.run(
            ["npx", "tree-sitter", "parse", fp, "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        _logger.debug("tree-sitter not installed, skip: %s", fp)
        return []
    except subprocess.TimeoutExpired:
        _logger.debug("tree-sitter timeout: %s", fp)
        return []
    except OSError:
        _logger.debug("tree-sitter OS error: %s", fp)
        return []

    if result.returncode != 0:
        _logger.debug("tree-sitter nonzero exit for %s: %s", fp, result.stderr[:200])
        return []

    if not result.stdout.strip():
        return []

    return parse_ast(result.stdout, str(fp))


def parse_ast(ast_json: str, filename: str) -> list[SymbolInfo]:
    """解析 tree-sitter JSON 输出, 提取符号列表.

    Args:
        ast_json: tree-sitter --json 输出的 JSON 字符串.
        filename: 源文件路径 (填充到 SymbolInfo.file).

    Returns:
        SymbolInfo 列表. 格式错误时返回空列表.
    """
    try:
        tree = json.loads(ast_json)
    except (json.JSONDecodeError, TypeError):
        return []

    symbols: list[SymbolInfo] = []

    def _walk(node: dict, parent_class: str = "") -> None:
        node_type = node.get("type", "")
        name = node.get("name", "")
        line = node.get("line", 1)

        kind = _TREE_SITTER_KINDS.get(node_type)
        if kind and name:
            scope = parent_class
            if kind == "method":
                scope = parent_class
            symbols.append(SymbolInfo(
                name=name, kind=kind, file=filename, line=line, scope=scope,
            ))

        children = node.get("children", [])
        next_parent = name if kind == "class" else parent_class
        for child in children:
            _walk(child, next_parent)

    _walk(tree)
    return symbols


def deduplicate(symbols: list[SymbolInfo]) -> list[SymbolInfo]:
    """按 (name, kind, file) 去重, 保留首次出现."""
    seen: dict[tuple[str, str, str], SymbolInfo] = {}
    for s in symbols:
        key = (s.name, s.kind, s.file)
        if key not in seen:
            seen[key] = s
    return list(seen.values())


def _extract_imports(symbol: SymbolInfo) -> list[str]:
    """从 SymbolInfo.scope 中提取 import 依赖.

    解析 import 语句字符串:
      - "import os" → ["os"]
      - "import os, sys, json" → ["os", "sys", "json"]
      - "from core import Client" → ["core", "Client"]
      - "from core import Client as C" → ["core", "Client"]
    """
    scope = (symbol.scope or "").strip()
    if not scope:
        return []

    deps: list[str] = []
    for line in scope.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("from "):
            m = re.match(r"from\s+(\S+)\s+import\s+(.+)", line)
            if m:
                deps.append(m.group(1))
                for item in re.split(r"\s*,\s*", m.group(2)):
                    name = re.split(r"\s+as\s+", item.strip())[0].strip()
                    if name:
                        deps.append(name)
        elif line.startswith("import "):
            m = re.match(r"import\s+(.+)", line)
            if m:
                for item in re.split(r"\s*,\s*", m.group(1)):
                    name = re.split(r"\s+as\s+", item.strip())[0].strip()
                    if name:
                        deps.append(name)
    return deps


def build_dependency_graph(symbols: list[SymbolInfo]) -> dict[str, list[str]]:
    """从符号列表构建依赖图.

    每个符号的 scope 字符串中的 import 被解析为依赖.
    未解析的外部依赖 (不在 symbols 中的) 被过滤.
    """
    if not symbols:
        return {}

    symbol_names = {s.name for s in symbols}
    graph: dict[str, list[str]] = {}
    for s in symbols:
        all_deps = _extract_imports(s)
        resolved = [d for d in all_deps if d in symbol_names and d != s.name]
        unresolved = [d for d in all_deps if d not in symbol_names and d != s.name]
        if resolved or unresolved:
            graph[s.name] = resolved
    return graph


# ── Python AST 降级路径 (tree-sitter 不可用时) ──


class _ASTSymbolExtractor(_ast.NodeVisitor):
    """Python AST 遍历器: 提取函数/类/方法 + 导入关系."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.symbols: list[SymbolInfo] = []
        self._current_class: str = ""
        self._imports: str = ""

    def visit_Import(self, node: _ast.Import) -> None:
        for alias in node.names:
            self._imports += f"import {alias.name}\n"
        self.generic_visit(node)

    def visit_ImportFrom(self, node: _ast.ImportFrom) -> None:
        if node.module:
            names = ", ".join(a.name for a in node.names)
            self._imports += f"from {node.module} import {names}\n"
        self.generic_visit(node)

    def visit_FunctionDef(self, node: _ast.FunctionDef) -> None:
        kind = "method" if self._current_class else "function"
        sig = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
        self.symbols.append(SymbolInfo(
            name=node.name, kind=kind, file=self.filepath,
            line=node.lineno, scope=self._current_class, signature=sig,
        ))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: _ast.AsyncFunctionDef) -> None:
        kind = "method" if self._current_class else "function"
        sig = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
        self.symbols.append(SymbolInfo(
            name=node.name, kind=kind, file=self.filepath,
            line=node.lineno, scope=self._current_class, signature=sig,
        ))
        self.generic_visit(node)

    def visit_ClassDef(self, node: _ast.ClassDef) -> None:
        bases = ", ".join(_ast.unparse(b) for b in node.bases) if node.bases else ""
        sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
        self.symbols.append(SymbolInfo(
            name=node.name, kind="class", file=self.filepath, line=node.lineno, signature=sig,
        ))
        prev_scope = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = prev_scope


def _extract_python_ast(filepath: str, source: str) -> tuple[list[SymbolInfo], str]:
    """用 Python AST 解析源文件."""
    try:
        tree = _ast.parse(source)
    except SyntaxError:
        return [], ""
    extractor = _ASTSymbolExtractor(filepath)
    extractor.visit(tree)
    return extractor.symbols, extractor._imports


def _extract_regex(filepath: str, source: str) -> list[SymbolInfo]:
    """Regex 降级: 提取函数/类声明."""
    symbols: list[SymbolInfo] = []
    for match in re.finditer(
        r"^\s*(?:def|class)\s+(\w+)", source, re.MULTILINE
    ):
        name = match.group(1)
        line_no = source[:match.start()].count("\n") + 1
        kind = "class" if match.group(0).lstrip().startswith("class") else "function"
        symbols.append(SymbolInfo(name=name, kind=kind, file=filepath, line=line_no))
    return symbols


def extract(shape: ProjectShape) -> SymbolIndex:
    """从 ProjectShape 中提取所有源文件的符号表和依赖图.

    优先使用 tree-sitter CLI, 不可用时降级到 Python AST + regex.
    """
    root = Path.cwd()
    all_symbols: list[SymbolInfo] = []
    all_scopes: dict[str, str] = {}

    source_files: list[Path] = []
    for module in shape.modules:
        module_path = root / module.path
        if module_path.exists():
            source_files.extend(sorted(module_path.rglob("*.py")))

    for filepath in source_files:
        try:
            rel_path = str(filepath.relative_to(root))
        except ValueError:
            rel_path = str(filepath)

        # Try tree-sitter first
        symbols = _parse_file(str(filepath))
        scope_str = ""

        if not symbols:
            # Fallback: Python AST
            try:
                source = filepath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            symbols, scope_str = _extract_python_ast(rel_path, source)
            if not symbols:
                symbols = _extract_regex(rel_path, source)

        all_symbols.extend(symbols)
        if scope_str:
            all_scopes[rel_path] = scope_str

    symbols = deduplicate(all_symbols)

    # Build dependency graph from AST-parsed imports
    dep_graph: dict[str, list[str]] = {}
    symbol_names = {s.name for s in symbols}
    for symbol in symbols:
        if symbol.scope:
            deps = [d for d in _extract_imports(symbol) if d in symbol_names and d != symbol.name]
            if deps:
                dep_graph[symbol.name] = deps

    return SymbolIndex(symbols=symbols, dependency_graph=dep_graph)
