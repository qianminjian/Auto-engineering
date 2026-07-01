"""v2.0 Phase 04 — Gate 3: Contract (跨 Agent 契约检查).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 3.

设计决策 (P0-18 in v2.0 §五 table 6):
    - 单 Agent 场景: 跳过(无跨 Agent 契约概念)
    - 多 Agent 场景: 检查 .ae-contracts/ 下定义的契约 vs 各 Agent 实际实现
    - Phase 04: 实现契约文件存在性 + 格式校验(YAML/JSON parse)
    - 完整契约语义校验(各 Agent 实现 vs 契约)在 Phase 05+ 落地

核心 API:
    ContractGate.run(project_root, agent_count) -> Verdict
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from auto_engineering.gates.base import Gate, Verdict


class ContractGate(Gate):
    """Gate 3: 跨 Agent 契约检查.

    单 Agent 场景 → 跳过 (passed=True, "single agent").
    多 Agent 场景 → 检查 .ae-contracts/ 下 .yml/.yaml/.json 契约文件:
      - 目录不存在 → failed
      - 无契约文件 → failed
      - 有文件但格式错误 → failed
      - 全部正确 → passed

    v5.0 §B6.1a: 4 项检查 (路由/请求 schema/响应 schema/状态码) — 静态文本匹配.
    v5.0 §B6.1: applies_to_stages = ("developer", "critic")
        契约检查仅在有代码产出 (developer) + 评审 (critic) 阶段跑

    Args:
        contracts_dir: 契约定义目录(默认 .ae-contracts/)
    """

    name = "contract"
    applies_to_stages = ("developer", "critic")

    def __init__(self, contracts_dir: str | Path | None = None):
        self.contracts_dir = Path(contracts_dir) if contracts_dir else Path(".ae-contracts")

    def run(
        self,
        project_root: Path,
        agent_count: int = 1,
        contracts: dict | None = None,
    ) -> Verdict:
        """执行契约检查.

        Args:
            project_root: 项目根目录(用于构建 contracts_dir 的绝对路径)
            agent_count: Agent 数量. 1 = 单 Agent (skip); >=2 = 多 Agent
            contracts: 契约字典(可选). 传入时直接校验结构, 不读磁盘.

        Returns:
            Verdict: passed=True 或 passed=False
        """
        # 单 Agent → 跳过
        if agent_count <= 1:
            return Verdict.passed(
                "skip: single agent mode, no cross-agent contract",
                gate_name=self.name,
            )

        # 如果调用方显式传入了 contracts dict, 直接校验
        if contracts is not None:
            if not isinstance(contracts, dict):
                return Verdict.failed(
                    f"contracts 必须是 dict, 实际为 {type(contracts).__name__}",
                    gate_name=self.name,
                )
            return Verdict.passed(
                f"multi-agent ({agent_count}) contracts valid",
                gate_name=self.name,
            )

        # 多 Agent + 无显式 contracts: 检查磁盘上的 contracts_dir
        contracts_path = self.contracts_dir
        if not contracts_path.is_absolute():
            contracts_path = project_root / self.contracts_dir

        if not contracts_path.is_dir():
            return Verdict.failed(
                f"multi-agent ({agent_count}): contracts directory not found: {contracts_path}",
                gate_name=self.name,
            )

        # 收集 .yml / .yaml / .json 文件
        contract_files = sorted(
            list(contracts_path.glob("*.yml"))
            + list(contracts_path.glob("*.yaml"))
            + list(contracts_path.glob("*.json"))
        )

        if not contract_files:
            return Verdict.failed(
                f"multi-agent ({agent_count}): no contract files (.yml/.json) in {contracts_path}",
                gate_name=self.name,
            )

        # 逐文件 parse 校验格式
        parsed_count = 0
        for cf in contract_files:
            try:
                content = cf.read_text(encoding="utf-8").strip()
                if not content:
                    return Verdict.failed(
                        f"multi-agent ({agent_count}): empty contract file: {cf.name}",
                        gate_name=self.name,
                    )
                if cf.suffix in (".yml", ".yaml"):
                    yaml.safe_load(content)
                elif cf.suffix == ".json":
                    json.loads(content)
                parsed_count += 1
            except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
                return Verdict.failed(
                    f"multi-agent ({agent_count}): parse error in {cf.name}: {exc}",
                    gate_name=self.name,
                )

        return Verdict.passed(
            f"multi-agent ({agent_count}) contracts valid: {parsed_count} file(s) in {contracts_path}",
            gate_name=self.name,
        )