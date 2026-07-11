"""v5.5 P1-7: Gate timeout env var 默认值测试.

验证 AE_GATE_TIMEOUT 环境变量在所有 Gate 子类中被正确读取作为默认 timeout。
"""

from __future__ import annotations

# ============================================================
# 测试: AE_GATE_TIMEOUT env var 被各子类读取
# ============================================================


class TestGateTimeoutEnvVar:
    """P1-7: AE_GATE_TIMEOUT 环境变量应在所有 Gate 子类中作为 timeout 默认值."""

    def test_lint_gate_respects_env_var(self, monkeypatch):
        """LintGate() 无显式 timeout 时应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "90")
        from auto_engineering.gates.lint import LintGate

        gate = LintGate()
        assert gate.timeout == 90.0, f"期望 90.0 (env var), 实际 {gate.timeout}"

    def test_type_check_gate_respects_env_var(self, monkeypatch):
        """TypeCheckGate() 无显式 timeout 时应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "150")
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()
        assert gate.timeout == 150.0, f"期望 150.0 (env var), 实际 {gate.timeout}"

    def test_test_gate_respects_env_var(self, monkeypatch):
        """TestGate() 无显式 timeout 时应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "90")
        from auto_engineering.gates.test_gate import TestGate

        gate = TestGate()
        assert gate.timeout == 90.0, f"期望 90.0 (env var), 实际 {gate.timeout}"

    def test_build_gate_respects_env_var(self, monkeypatch):
        """BuildGate() 无显式 timeout 时应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "45")
        from auto_engineering.gates.build import BuildGate

        gate = BuildGate()
        assert gate.timeout == 45.0, f"期望 45.0 (env var), 实际 {gate.timeout}"

    def test_safety_gate_respects_env_var(self, monkeypatch):
        """SafetyGate() 无显式 timeout 时应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "45")
        from auto_engineering.gates.safety import SafetyGate

        gate = SafetyGate()
        assert gate.timeout == 45.0, f"期望 45.0 (env var), 实际 {gate.timeout}"

    def test_explicit_timeout_overrides_env_var(self, monkeypatch):
        """显式 timeout 参数应覆盖环境变量."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "90")
        from auto_engineering.gates.lint import LintGate

        gate = LintGate(timeout=30.0)
        assert gate.timeout == 30.0, f"期望 30.0 (显式), 实际 {gate.timeout}"

    def test_subclass_default_when_no_env_var(self, monkeypatch):
        """未设 AE_GATE_TIMEOUT 时使用子类特定默认值."""
        monkeypatch.delenv("AE_GATE_TIMEOUT", raising=False)
        from auto_engineering.gates.lint import LintGate

        gate = LintGate()
        # LintGate 默认 60.0
        assert gate.timeout == 60.0, f"期望 60.0 (默认), 实际 {gate.timeout}"

    def test_from_manifest_respects_env_var(self, monkeypatch):
        """from_manifest() 不传 timeout 时也应读取 AE_GATE_TIMEOUT."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "90")
        from auto_engineering.gates.lint import LintGate

        manifest = {"language": "python", "conventions": {"linter": "ruff"}}
        gate = LintGate.from_manifest(manifest)
        assert gate.timeout == 90.0, f"期望 90.0 (env var via from_manifest), 实际 {gate.timeout}"

    def test_from_manifest_explicit_timeout_overrides_env_var(self, monkeypatch):
        """from_manifest() 传入显式 timeout 应覆盖环境变量."""
        monkeypatch.setenv("AE_GATE_TIMEOUT", "90")
        from auto_engineering.gates.lint import LintGate

        manifest = {"language": "python", "conventions": {"linter": "ruff"}}
        gate = LintGate.from_manifest(manifest, timeout=30.0)
        assert gate.timeout == 30.0, f"期望 30.0 (显式 via from_manifest), 实际 {gate.timeout}"

    def test_base_gate_resolve_timeout_helper(self, monkeypatch):
        """Gate._resolve_timeout 静态方法应正确读取 env var."""
        monkeypatch.delenv("AE_GATE_TIMEOUT", raising=False)
        from auto_engineering.gates.base import Gate

        # 无 env var → 使用 default
        assert Gate._resolve_timeout(60.0) == 60.0

        # 有 env var → 使用 env var
        monkeypatch.setenv("AE_GATE_TIMEOUT", "120")
        assert Gate._resolve_timeout(60.0) == 120.0
