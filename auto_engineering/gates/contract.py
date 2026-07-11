"""v2.0 Phase 04 — Gate 3: Contract (跨 Agent 契约检查) + v5.0 4 项语义检查.

设计来源:
    - design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 3
    - v5.0 §B6.1a 4 项检查 (路由/请求 schema/响应 schema/状态码) — 静态文本匹配

设计决策 (P0-18 in v2.0 §五 table 6):
    - 单 Agent 场景: 跳过(无跨 Agent 契约概念)
    - 多 Agent 场景: 检查 .ae-contracts/ 下定义的契约 vs 各 Agent 实际实现
    - Phase 04: 实现契约文件存在性 + 格式校验(YAML/JSON parse)
    - Phase 05 (v5.0 §B6.1a): 4 项检查 — 静态文本匹配, 不做 AST

核心 API (v5.5 P1-9: contracts 为实例属性, 不再作为 run() 参数):
    ContractGate(contracts_dir=...)      # 构造 (contracts_dir 供旧 multi-agent 路径)
    gate.contracts = {...}               # 可选: 预设 4 项检查契约 (dict)
    gate.run(project_root) -> GateVerdict # contracts=None → skip single-agent
"""

from __future__ import annotations

import logging
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict

__all__ = ["ContractGate"]

_logger = logging.getLogger("ae.gates.contract")

# v5.0 §B6.1a — 扫描的源文件扩展名 (限静态文本匹配范围, 不扫描 README/配置)
_SOURCE_EXTENSIONS = {".py", ".ts", ".js", ".go", ".rs"}

# v5.0 §B6.1a — 搜索根目录优先级: project_root/src/ 优先, 否则 project_root/
_SEARCH_ROOTS = ("src", "")


def _collect_source_files(project_root: Path) -> list[Path]:
    """v5.0 §B6.1a — 收集源码文件 (限 _SOURCE_EXTENSIONS).

    搜索范围: project_root/src/ (若存在) → 否则 project_root/.
    返回所有匹配 _SOURCE_EXTENSIONS 的文件路径.
    """
    files: list[Path] = []
    # 按优先级找第一个存在的根
    for sub in _SEARCH_ROOTS:
        root = project_root / sub if sub else project_root
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in _SOURCE_EXTENSIONS:
                files.append(path)
        # 找到第一个存在的根就返回 (不重复扫描根目录)
        if files or sub == "":
            return files
    return files


def _check_contract_in_source(
    contract: dict,
    source_files: list[Path],
) -> tuple[bool, str]:
    """v5.0 §B6.1a — 静态文本匹配检查单个契约.

    4 项检查:
        1. 路由 (path)     — contract["path"] 在源码中可见
        2. 请求 schema      — contract.get("request") 的字段名在源码中可见 (可选)
        3. 响应 schema      — contract.get("response") 的字段名在源码中可见 (可选)
        4. 状态码           — contract.get("status_code") 出现在源码中 (可选)

    Args:
        contract: 单个契约 dict (key: name, path/method/request/response/status_code)
        source_files: 待扫描源文件列表

    Returns:
        (passed, message) — passed=True 表示所有声明的项都在源码中找到
    """
    # 收集源码文本 (合并所有源文件, 一次扫描)
    source_text_parts: list[str] = []
    for path in source_files:
        try:
            source_text_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            _logger.warning("跳过不可读文件: %s", path)
            continue
    source_text = "\n".join(source_text_parts)

    # 1. 路由 (path) — 必须存在
    declared_path = contract.get("path")
    if declared_path:
        if str(declared_path) not in source_text:
            return False, f"path '{declared_path}' not found in source"

    # 2. 状态码 (status_code) — 可选
    status_code = contract.get("status_code")
    if status_code is not None:
        if str(status_code) not in source_text:
            return False, f"status_code '{status_code}' not found in source"

    # 3. 请求 schema — 可选 (字段名存在性检查)
    request_schema = contract.get("request")
    if isinstance(request_schema, dict):
        for field_name in request_schema:
            if field_name and str(field_name) not in source_text:
                return False, f"request field '{field_name}' not found in source"

    # 4. 响应 schema — 可选 (字段名存在性检查)
    response_schema = contract.get("response")
    if isinstance(response_schema, dict):
        for field_name in response_schema:
            if field_name and str(field_name) not in source_text:
                return False, f"response field '{field_name}' not found in source"

    return True, "ok"


class ContractGate(Gate):
    """Gate 3: 跨 Agent 契约检查 + 4 项语义检查.

    v5.0 §B6.1a 4 项检查 (路由/请求 schema/响应 schema/状态码):
        - 静态文本匹配, 不做 AST
        - 搜索范围: project_root/src/ (若存在) → 否则 project_root/
        - 仅扫描 .py/.ts/.js/.go/.rs 文件
        - contracts=None 或空 → passed("无契约定义, 跳过")

    向后兼容:
        - v5.0+ 路径: 传入 contracts=dict → 走 4 项检查 (path/status_code/request/response)

    Args:
        contracts_dir: 契约定义目录(默认 .ae-contracts/) — 旧 multi-agent 路径用
    """

    name = "contract"
    applies_to_stages = ("developer", "critic")

    def __init__(self, contracts_dir: str | Path | None = None):
        self.contracts_dir = Path(contracts_dir) if contracts_dir else Path(".ae-contracts")

    def run(self, project_root: Path) -> GateVerdict:
        """执行契约检查.

        v5.5 P1-9: contracts 改为实例属性 (self.contracts), 不再作为 run() 参数.

        Returns:
            GateVerdict: passed=True 或 passed=False
        """
        # v5.0 §B6.1a 路径: self.contracts 有值 → 4 项检查
        if self.contracts is not None:
            if not isinstance(self.contracts, dict):
                return GateVerdict.failed(
                    f"contracts 必须是 dict, 实际为 {type(self.contracts).__name__}",
                    gate_name=self.name,
                )
            if not self.contracts:
                return GateVerdict.ok(
                    "skip: 无契约定义, 跳过 (contracts 为空)",
                    gate_name=self.name,
                )
            return self._check_contracts(project_root)

        return GateVerdict.ok(
            "skip: single agent mode, no cross-agent contract",
            gate_name=self.name,
        )

    def _check_contracts(self, project_root: Path) -> GateVerdict:
        """v5.0 §B6.1a — 4 项检查 (path/status_code/request/response)."""
        if verdict := self._validate_project_root(project_root):
            return verdict

        root = Path(project_root)
        source_files = _collect_source_files(root)
        if not source_files:
            return GateVerdict.failed(
                f"未找到源文件 (扫描 _SOURCE_EXTENSIONS={sorted(_SOURCE_EXTENSIONS)})",
                gate_name=self.name,
            )

        contracts = self.contracts or {}
        # 逐契约检查
        for name, contract in contracts.items():
            if not isinstance(contract, dict):
                return GateVerdict.failed(
                    f"contract '{name}' 必须是 dict, 实际为 {type(contract).__name__}",
                    gate_name=self.name,
                )
            passed, msg = _check_contract_in_source(contract, source_files)
            if not passed:
                return GateVerdict.failed(
                    f"contract '{name}': {msg}",
                    gate_name=self.name,
                )

        return GateVerdict.ok(
            f"所有 {len(contracts)} 个契约 4 项检查通过",
            gate_name=self.name,
        )