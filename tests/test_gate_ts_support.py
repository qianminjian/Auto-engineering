"""P0 (2026-07-26 真跑): Gate 对 TS 项目支持 + skip 一等公民 回归测试。

真跑发现 7+1 gates 中 test/lint/type_check 对 TS 项目静默 skip 却报 ✓（质量门禁
形同虚设）。修复：① GateVerdict.skip 一等公民（passed=True 不阻断 + skipped=True
区别于真通过）；② test gate 无测试(exit=4/5)→skip；③ lint 按语言选 eslint via npx；
④ type_check tsc via npx tsc --noEmit；⑤ formatter 显示 ⊘ SKIPPED。
"""

from __future__ import annotations

from pathlib import Path


class TestGateSkipFirstClass:
    def test_verdict_skip_is_first_class(self):
        from auto_engineering.gates.base import GateVerdict
        v = GateVerdict.skip("工具未安装", gate_name="lint")
        assert v.passed is True    # 不阻断 dev-loop
        assert v.skipped is True   # 区别于真通过
        assert v.gate_name == "lint"

    def test_verdict_ok_not_skipped(self):
        from auto_engineering.gates.base import GateVerdict
        v = GateVerdict.ok("通过", gate_name="build")
        assert v.passed is True
        assert v.skipped is False


class TestTestGateNoTestsFailsClosed:
    def test_no_tests_collected_fails_closed(self, tmp_path, monkeypatch):
        """vitest exit=4（未收集到测试）→ fail，不得作为验证通过。"""
        import auto_engineering.gates.test_gate as tg
        from auto_engineering.gates.base import SubprocessResult
        from auto_engineering.gates.test_gate import TestGate

        monkeypatch.setattr(
            tg, "run_gate_command",
            lambda cmd, cwd, timeout: SubprocessResult(
                returncode=4, stdout="No test files found", stderr=""))
        gate = TestGate(test_runner_bin="vitest")
        verdict = gate.run(tmp_path)
        assert verdict.skipped is False
        assert verdict.passed is False

    def test_default_gate_uses_vitest_command_for_typescript_project(
        self, tmp_path, monkeypatch
    ):
        """自动检测到 TypeScript 后，实际命令也必须是 vitest，不能仍执行 pytest。"""
        import auto_engineering.gates.test_gate as tg
        from auto_engineering.gates.base import SubprocessResult
        from auto_engineering.gates.test_gate import TestGate

        (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}')
        captured: list[list[str]] = []

        def fake_run(cmd, _cwd, _timeout):
            captured.append(cmd)
            return SubprocessResult(returncode=0, stdout="1 passed", stderr="")

        monkeypatch.setattr(tg, "run_gate_command", fake_run)
        verdict = TestGate().run(tmp_path)

        assert verdict.passed is True
        assert captured == [["npx", "vitest", "run", "tests"]]

    def test_unknown_runner_fails_without_execution(self, tmp_path, monkeypatch):
        import auto_engineering.gates.test_gate as tg
        from auto_engineering.gates.test_gate import TestGate

        monkeypatch.setattr(
            tg,
            "run_gate_command",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("未知 runner 不得执行")
            ),
        )

        verdict = TestGate(test_runner_bin="unknown-runner").run(tmp_path)

        assert verdict.passed is False
        assert "不支持" in verdict.message


class TestLintGateTsSupport:
    def test_ts_project_resolves_npx_eslint(self, tmp_path: Path):
        """TS 项目 lint 解析为 npx eslint（eslint 在项目 node_modules，非全局）。"""
        from auto_engineering.gates.lint import LintGate
        (tmp_path / "package.json").write_text("{}")  # TS 标记
        gate = LintGate()  # 默认 ruff
        cmd = gate._resolve_lint_cmd(tmp_path, "eslint")
        assert cmd == ["npx", "eslint"]

    def test_python_project_keeps_ruff_fallback(self, tmp_path: Path):
        """Python 项目仍走 ruff 5 级兜底（不受 TS 改动影响）。"""
        from auto_engineering.gates.lint import LintGate
        gate = LintGate(linter_bin="ruff")
        cmd = gate._resolve_lint_cmd(tmp_path, "ruff")
        assert cmd[0].endswith("ruff") or cmd[0] == "ruff"


class TestTypeCheckGateTsSupport:
    def test_tsc_resolves_npx_noemit(self):
        """tsc 解析为 npx tsc --noEmit（tsc 在项目 node_modules，非全局 PATH）。"""
        from auto_engineering.gates.type_check import TypeCheckGate
        gate = TypeCheckGate(type_checker_bin="tsc")
        cmd = gate._resolve_type_check_cmd("tsc")
        assert cmd == ["npx", "tsc", "--noEmit"]

    def test_mypy_keeps_direct(self):
        """mypy 仍直接调用（Python 生态，不受 TS 改动影响）。"""
        from auto_engineering.gates.type_check import TypeCheckGate
        gate = TypeCheckGate(type_checker_bin="mypy")
        cmd = gate._resolve_type_check_cmd("mypy")
        assert cmd == ["mypy"]
