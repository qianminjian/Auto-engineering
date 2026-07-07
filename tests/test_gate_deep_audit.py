"""v5.5 — DeepAuditGate 单元测试.

测试 DeepAuditGate 的 Gate ABC 接口合规性、findings 分类、阈值判定逻辑.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.gates.base import Gate, GateVerdict
from auto_engineering.gates.deep_audit import DeepAuditFinding, DeepAuditGate, DeepAuditReport


class TestDeepAuditGateInterface:
    """Gate ABC 接口合规性测试."""

    def test_is_gate_subclass(self):
        """DeepAuditGate 应是 Gate 的子类."""
        assert issubclass(DeepAuditGate, Gate)

    def test_has_name_property(self):
        """应实现 name 属性."""
        gate = DeepAuditGate()
        assert gate.name == "DeepAuditGate"

    def test_run_returns_gateverdict(self):
        """run() 应返回 GateVerdict 实例."""
        gate = DeepAuditGate()
        verdict = gate.run(Path("/tmp"))
        assert isinstance(verdict, GateVerdict)

    def test_run_accepts_contracts(self):
        """run() 应通过 contracts 实例属性接受数据."""
        gate = DeepAuditGate()
        gate.contracts = {"files_changed": ["a.py"]}
        verdict = gate.run(Path("/tmp"))
        assert isinstance(verdict, GateVerdict)


class TestDeepAuditGateEmptyRun:
    """空项目 (无 findings) 的判定."""

    def test_empty_context_passes(self):
        """无 context 时应 pass (P0=0, P1=0)."""
        gate = DeepAuditGate()
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is True
        assert verdict.gate_name == "DeepAuditGate"

    def test_empty_context_default_threshold(self):
        """默认 P1 阈值为 6, 空输入 details 正确."""
        gate = DeepAuditGate()
        verdict = gate.run(Path("/tmp"))
        assert verdict.details is not None
        assert verdict.details["p0_count"] == 0
        assert verdict.details["p1_count"] == 0
        assert verdict.details["p2_count"] == 0
        assert verdict.details["p1_threshold"] == 6


class TestDeepAuditGateWithFindings:
    """有 findings 时的判定逻辑."""

    def test_p0_causes_failure(self):
        """任何 P0 → fail (即使 P1 未超阈值)."""
        findings = [
            {"severity": "P0", "dimension": "代码质量", "file": "a.py", "line": 10,
             "description": "硬编码密钥", "evidence": "API_KEY = 'abc123'", "suggested_fix": "用环境变量"},
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is False
        assert verdict.details["p0_count"] == 1

    def test_p1_within_threshold_passes(self):
        """P1 数量 <= 阈值 → pass."""
        findings = [
            {"severity": "P1", "dimension": "工程化规范", "file": f"mod{i}.py", "line": i,
             "description": f"TODO #{i}", "evidence": "", "suggested_fix": ""}
            for i in range(5)  # 5 <= 6 阈值
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is True
        assert verdict.details["p1_count"] == 5

    def test_p1_exceeds_threshold_fails(self):
        """P1 数量 > 阈值 → fail."""
        findings = [
            {"severity": "P1", "dimension": "工程化规范", "file": f"mod{i}.py", "line": i,
             "description": f"TODO #{i}", "evidence": "", "suggested_fix": ""}
            for i in range(7)  # 7 > 6 阈值
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is False
        assert verdict.details["p1_count"] == 7

    def test_custom_p1_threshold(self):
        """自定义 P1 阈值应生效."""
        findings = [
            {"severity": "P1", "dimension": "工程化规范", "file": f"mod{i}.py", "line": i,
             "description": f"TODO #{i}", "evidence": "", "suggested_fix": ""}
            for i in range(8)
        ]
        # threshold=10, 8 <= 10 → pass
        gate = DeepAuditGate(p1_threshold=10)
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is True

    def test_p2_only_passes(self):
        """仅有 P2 (无 P0, P1 在阈值内) → pass."""
        findings = [
            {"severity": "P2", "dimension": "工程化规范", "file": f"mod{i}.py", "line": i,
             "description": f"裸 print #{i}", "evidence": "", "suggested_fix": ""}
            for i in range(20)
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is True
        assert verdict.details["p2_count"] == 20

    def test_mixed_severities(self):
        """混合 severity: P0 控制 fail, P1+P2 追加."""
        findings = [
            {"severity": "P1", "dimension": "工程化规范", "file": "a.py", "line": 1,
             "description": "TODO", "evidence": "", "suggested_fix": ""},
            {"severity": "P0", "dimension": "代码质量", "file": "b.py", "line": 5,
             "description": "硬编码密钥", "evidence": "secret", "suggested_fix": "env var"},
            {"severity": "P2", "dimension": "工程化规范", "file": "c.py", "line": 10,
             "description": "裸 print", "evidence": "", "suggested_fix": ""},
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is False
        assert verdict.details["p0_count"] == 1
        assert verdict.details["p1_count"] == 1
        assert verdict.details["p2_count"] == 1

    def test_suggestions_included_on_failure(self):
        """失败时 suggestions 应包含所有有 suggested_fix 的 finding."""
        findings = [
            {"severity": "P0", "dimension": "代码质量", "file": "a.py", "line": 10,
             "description": "硬编码密钥", "evidence": "KEY='abc'", "suggested_fix": "用 os.environ"},
            {"severity": "P0", "dimension": "代码质量", "file": "b.py", "line": 20,
             "description": "空 except", "evidence": "except:", "suggested_fix": ""},
            {"severity": "P1", "dimension": "工程化规范", "file": "c.py", "line": 30,
             "description": "TODO", "evidence": "", "suggested_fix": "移除或创建 issue"},
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is False
        assert verdict.suggestions is not None
        assert "用 os.environ" in verdict.suggestions
        assert "移除或创建 issue" in verdict.suggestions

    def test_no_suggestions_on_pass(self):
        """通过时 suggestions 应为空列表."""
        findings = [
            {"severity": "P2", "dimension": "工程化规范", "file": "a.py", "line": 1,
             "description": "裸 print", "evidence": "", "suggested_fix": "替换为 logger"},
        ]
        gate = DeepAuditGate()
        gate.contracts = {"findings": findings}
        verdict = gate.run(Path("/tmp"))
        assert verdict.passed is True
        assert verdict.suggestions == []


class TestDeepAuditFinding:
    """DeepAuditFinding 数据类测试."""

    def test_default_agent_source(self):
        """agent_source 默认应为空字符串."""
        f = DeepAuditFinding(
            severity="P0", dimension="代码质量", file="a.py", line=10,
            description="test", evidence="e", suggested_fix="f",
        )
        assert f.agent_source == ""

    def test_line_can_be_none(self):
        """line 可为 None (如架构维度无具体行号)."""
        f = DeepAuditFinding(
            severity="P1", dimension="架构合理性", file="a.py", line=None,
            description="循环依赖", evidence="", suggested_fix="",
        )
        assert f.line is None


class TestDeepAuditReport:
    """DeepAuditReport 数据类测试."""

    def test_defaults(self):
        """默认值应全部为零/空."""
        r = DeepAuditReport()
        assert r.findings == []
        assert r.p0_count == 0
        assert r.p1_count == 0
        assert r.p2_count == 0
        assert r.total_audited_files == 0
        assert r.audit_duration_ms == 0
