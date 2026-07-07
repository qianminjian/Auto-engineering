"""Tests for v5.0 Phase 05 — M6 Gate 体系扩展.

设计: v5.0 §B6.1 Gate applies_to_stages (按 stage 过滤哪些 Gate 运行) +
      §B6.1a ContractGate 4 项检查 +
      §B6.2 run_gates 按 stage 过滤并行.

Gate 阶段映射 (v5.0 §B6.1):
    - safety / lint / type_check: (architect, developer, critic) 三阶段都跑
    - contract / test:            (developer, critic)
    - coverage:                   (developer,) — 但 BEACON 决策 25 永远 skip
    - build:                      (developer,) — 打包构建
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ============================================================
# Group 1: Gate 基类 applies_to_stages
# ============================================================


class TestGateAppliesToStages:
    """v5.0 §B6.1 — Gate 基类扩展 applies_to_stages 类属性."""

    def test_safety_gate_runs_all_stages(self):
        from auto_engineering.gates.safety import SafetyGate

        gate = SafetyGate(use_gitleaks=False)
        assert "architect" in gate.applies_to_stages
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages

    def test_lint_gate_runs_all_stages(self):
        from auto_engineering.gates.lint import LintGate

        gate = LintGate()
        assert "architect" in gate.applies_to_stages
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages

    def test_type_check_gate_runs_all_stages(self):
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()
        assert "architect" in gate.applies_to_stages
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages

    def test_contract_gate_runs_developer_critic_only(self):
        from auto_engineering.gates.contract import ContractGate

        gate = ContractGate()
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages
        assert "architect" not in gate.applies_to_stages

    def test_test_gate_runs_developer_critic_only(self):
        from auto_engineering.gates.test_gate import TestGate

        gate = TestGate()
        assert "developer" in gate.applies_to_stages
        assert "critic" in gate.applies_to_stages
        assert "architect" not in gate.applies_to_stages

    def test_build_gate_developer_only(self):
        from auto_engineering.gates.build import BuildGate

        gate = BuildGate()
        assert gate.applies_to_stages == ("developer",)


# ============================================================
# Group 2: Gate 基类扩展
# ============================================================


class TestGateBaseClass:
    """v5.0 §B6.1 — Gate 基类扩展 + DEFAULT_GATES 入口."""

    def test_base_gate_has_applies_to_stages_attribute(self):
        from auto_engineering.gates.base import Gate

        # 基类应有默认 applies_to_stages (tuple, 至少存在)
        assert hasattr(Gate, "applies_to_stages")
        assert isinstance(Gate.applies_to_stages, tuple)

    def test_gate_has_contracts_instance_attribute(self):
        """Gate 基类应具有 contracts 实例属性 (v5.5 P1-9: 从 run() 参数改为实例属性)."""
        from auto_engineering.gates.base import Gate

        assert hasattr(Gate, "contracts")
        # 默认值应当是 None
        gate = Gate.__new__(Gate)
        assert gate.contracts is None

    def test_default_gates_list(self):
        """DEFAULT_GATES 应当是 7 道 Gate 的实例列表 (safety/lint/type_check/audit/contract/test/build)."""
        from auto_engineering.gates.registry import DEFAULT_GATES

        assert isinstance(DEFAULT_GATES, list)
        assert len(DEFAULT_GATES) == 7  # v5.4 Q1: TDDGate/StageTransitionGate 已移出, 保留 7 道


# ============================================================
# Group 3: GateVerdict 重命名 + Verdict 别名
# ============================================================


class TestGateVerdictRename:
    """v5.0 §B6.1 — Verdict → GateVerdict 重命名 (保留别名)."""

    def test_gate_verdict_class_exists(self):
        from auto_engineering.gates.base import GateVerdict

        v = GateVerdict.ok("ok", gate_name="lint")
        assert v.passed is True
        assert v.message == "ok"
        assert v.gate_name == "lint"

    def test_verdict_alias_to_gate_verdict(self):
        """Verdict 应当作为 GateVerdict 的别名 (向后兼容)."""
        from auto_engineering.gates.base import GateVerdict, Verdict

        assert Verdict is GateVerdict


# ============================================================
# Group 4: ContractGate 4 项检查
# ============================================================


class TestContractGateChecks:
    """v5.0 §B6.1a — ContractGate 4 项检查:

        1. 路由 (path):  声明的 path 在源码中可见
        2. 请求 schema:  声明的请求参数在 handler 签名中可见
        3. 响应 schema:  声明的 response 在源码中可见
        4. 状态码:      声明的 status 出现在 handler 中

    实现策略: 静态文本匹配 (不做 AST).
    搜索范围: project_root/src/ 或 project_root/, 限 .py/.ts/.js/.go/.rs
    contracts=None/空 → passed("无契约定义, 跳过")
    """

    def test_contract_gate_no_contracts_passes(self, tmp_path: Path):
        """contracts=None 或空 → passed(skip)."""
        from auto_engineering.gates.contract import ContractGate

        gate = ContractGate()
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

        gate2 = ContractGate()
        gate2.contracts = {}
        verdict2 = gate2.run(tmp_path)
        assert verdict2.passed is True

    def test_contract_gate_finds_route_in_source(self, tmp_path: Path):
        """契约声明的 path 在源码 .py 中可找到 → passed."""
        from auto_engineering.gates.contract import ContractGate

        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text(
            "@app.route('/api/users', methods=['GET'])\n"
            "def list_users():\n"
            "    return {'users': []}\n"
        )
        gate = ContractGate()
        gate.contracts = {
            "list_users": {
                "path": "/api/users",
                "method": "GET",
            }
        }
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_contract_gate_missing_route_fails(self, tmp_path: Path):
        """契约声明的 path 在源码中找不到 → failed."""
        from auto_engineering.gates.contract import ContractGate

        gate = ContractGate()
        gate.contracts = {"missing_route": {"path": "/api/nonexistent"}}
        verdict = gate.run(tmp_path)
        assert verdict.passed is False

    def test_contract_gate_scans_src_directory(self, tmp_path: Path):
        """搜索范围: project_root/src/ 优先."""
        from auto_engineering.gates.contract import ContractGate

        src = tmp_path / "src"
        src.mkdir()
        (src / "api.py").write_text("def handler():\n    return 200\n")
        gate = ContractGate()
        gate.contracts = {"api_endpoint": {"status_code": 200}}
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_contract_gate_only_scans_source_extensions(self, tmp_path: Path):
        """扫描仅限 .py/.ts/.js/.go/.rs 文件."""
        from auto_engineering.gates.contract import ContractGate

        # 创建非源码文件
        (tmp_path / "README.md").write_text("# /api/users status=200\n")
        gate = ContractGate()
        gate.contracts = {"api": {"path": "/api/users", "status_code": 200}}
        verdict = gate.run(tmp_path)
        # README.md 不被扫描 → 路径找不到 → failed
        assert verdict.passed is False
