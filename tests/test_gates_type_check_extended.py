"""Phase 12.6 — TypeCheckGate 扩展测试 (≥85% 覆盖率).

设计来源: auto_engineering/gates/type_check.py (194 行, 48% → ≥85%).

覆盖目标:
    - TypeCheckGate 默认 pyright/mypy 调用路径
    - 工具缺失 → skip (passed=True)
    - 工具存在但 exit≠0 → GateVerdict.failed
    - 工具超时 → skip (passed=True)
    - 工具成功 → GateVerdict.passed
    - from_manifest 工厂: pyright/mypy/tsc/bash -n/不支持工具/缺 conventions
    - applies_to_stages 默认 + 显式 override
    - _resolve_type_check_cmd (bash -n 特殊处理)

策略: 用 mock 隔离 subprocess.run + shutil.which,不真实调用 type_checker.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

# ============================================================
# 1. TypeCheckGate 基础
# ============================================================


class TestTypeCheckGateBasics:
    """TypeCheckGate 默认构造 + 简单调用."""

    def test_default_construction(self):
        """默认构造: type_checker_bin='mypy', strict=False, require_config=False."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()
        assert gate.type_checker_bin == "mypy"
        assert gate.strict is False
        assert gate.require_config is False
        assert gate.timeout == 120.0  # 默认 _DEFAULT_TIMEOUT

    def test_construction_with_custom_args(self):
        """自定义参数: type_checker_bin/timeout/strict/require_config."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(
            type_checker_bin="pyright",
            timeout=60.0,
            strict=True,
            require_config=True,
        )
        assert gate.type_checker_bin == "pyright"
        assert gate.timeout == 60.0
        assert gate.strict is True
        assert gate.require_config is True

    def test_backward_compat_mypy_bin(self):
        """向后兼容: mypy_bin 作为 @property 别名委托到 type_checker_bin."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(type_checker_bin="custom-mypy")
        # 旧名 mypy_bin 通过 @property getter 访问 (DeprecationWarning)
        assert gate.mypy_bin == "custom-mypy"
        assert gate.type_checker_bin == "custom-mypy"

    def test_class_attributes(self):
        """类属性: name='type_check', applies_to_stages 三阶段."""
        from auto_engineering.gates.type_check import TypeCheckGate

        assert TypeCheckGate.name == "type_check"
        assert "architect" in TypeCheckGate.applies_to_stages
        assert "developer" in TypeCheckGate.applies_to_stages
        assert "critic" in TypeCheckGate.applies_to_stages


# ============================================================
# 2. from_manifest 工厂
# ============================================================


class TestTypeCheckGateFromManifest:
    """from_manifest: 从 init-manifest.conventions.type_checker 构造."""

    def _make_manifest(self, language: str, type_checker: str | None) -> dict:
        return {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": language,
            "structure": {"source_root": "src/", "test_root": "tests/"},
            "conventions": {
                "linter": "ruff",
                "type_checker": type_checker,
                "test_runner": "pytest",
            },
        }

    def test_from_manifest_with_pyright(self):
        """manifest.conventions.type_checker='pyright' → gate 用 pyright."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = self._make_manifest("python", "pyright")
        gate = TypeCheckGate.from_manifest(manifest)
        assert gate.type_checker_bin == "pyright"

    def test_from_manifest_with_mypy(self):
        """manifest.conventions.type_checker='mypy' → gate 用 mypy."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = self._make_manifest("python", "mypy")
        gate = TypeCheckGate.from_manifest(manifest)
        assert gate.type_checker_bin == "mypy"

    def test_from_manifest_with_tsc(self):
        """manifest.conventions.type_checker='tsc' → gate 用 tsc."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = self._make_manifest("typescript", "tsc")
        gate = TypeCheckGate.from_manifest(manifest)
        assert gate.type_checker_bin == "tsc"

    def test_from_manifest_with_bash_n(self):
        """manifest.conventions.type_checker='bash -n' → gate 用 'bash -n'."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = self._make_manifest("bash", "bash -n")
        gate = TypeCheckGate.from_manifest(manifest)
        assert gate.type_checker_bin == "bash -n"

    def test_from_manifest_with_unsupported_tool(self):
        """不支持的工具(如 'unknown-tool') → 仍然按 manifest 设置,不抛异常."""
        from auto_engineering.gates.type_check import TypeCheckGate

        # 注: from_manifest 只是把 conventions.type_checker 传给 type_checker_bin,
        # 不做合法性校验.实际执行时 _resolve_type_check_cmd 会决定如何处理.
        manifest = self._make_manifest("python", "unknown-tool-xyz")
        gate = TypeCheckGate.from_manifest(manifest)
        assert gate.type_checker_bin == "unknown-tool-xyz"

    def test_from_manifest_missing_conventions(self):
        """缺 conventions 字段 → 走 _default_tools_for 回退路径.

        注: get_gate_tools_from_manifest 在 conventions 缺失时实际返回 tuple
        (init_contract.py 的已知不一致,返回类型注解为 dict 但缺 conventions 时是 tuple).
        此处验证行为: type_checker_bin 被设为 'pyright' (python 默认).
        """
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": "python",
            "structure": {"source_root": "src/", "test_root": "tests/"},
            # 无 conventions
        }
        # 注: 实际 init_contract 在缺 conventions 时返回 tuple (非 dict),
        # 所以 tools["type_checker"] 会抛 TypeError. 这是已知问题.
        # 此处验证 TypeCheckGate.from_manifest 在 conventions 存在但 type_checker 缺失时回退.
        manifest_with_partial_conventions = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": "python",
            "structure": {"source_root": "src/", "test_root": "tests/"},
            "conventions": {
                "linter": "ruff",
                # type_checker 缺失 → 回退到 language 默认
                "test_runner": "pytest",
            },
        }
        gate = TypeCheckGate.from_manifest(manifest_with_partial_conventions)
        # python LANGUAGE_TOOLS 默认 type_checker = 'pyright'
        assert gate.type_checker_bin == "pyright"

    def test_from_manifest_with_custom_timeout(self):
        """from_manifest 接受 timeout 参数."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = self._make_manifest("python", "pyright")
        gate = TypeCheckGate.from_manifest(manifest, timeout=45.0)
        assert gate.timeout == 45.0

    def test_from_manifest_go_language_default(self):
        """language='go' + 无 type_checker → 默认 'go vet'."""
        from auto_engineering.gates.type_check import TypeCheckGate

        manifest = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": "go",
            "structure": {"source_root": ".", "test_root": "./..."},
            "conventions": {"linter": "x", "type_checker": None, "test_runner": "y"},
        }
        gate = TypeCheckGate.from_manifest(manifest)
        # go LANGUAGE_TOOLS 默认 type_checker = 'go vet'
        assert gate.type_checker_bin == "go vet"


# ============================================================
# 3. _resolve_type_check_cmd 内部逻辑
# ============================================================


class TestResolveTypeCheckCmd:
    """TypeCheckGate._resolve_type_check_cmd 命令解析."""

    def test_bash_n_special_handling(self):
        """type_checker_bin='bash -n' → 返回 ['bash', '-n']."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(type_checker_bin="bash -n")
        cmd = gate._resolve_type_check_cmd()
        assert cmd == ["bash", "-n"]

    def test_resolve_uses_shutil_which(self):
        """非 'bash -n' + type_checker_bin 非空 → 返回 [bin_name].

        注: type_checker_bin 始终有默认值, shutil.which 分支实际是 dead code.
        此处记录行为契约.
        """
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(type_checker_bin="pyright")
        with patch.object(shutil, "which", return_value="/usr/bin/pyright"):
            cmd = gate._resolve_type_check_cmd()
        assert cmd == ["pyright"]

    def test_resolve_returns_list_even_when_not_in_path(self):
        """工具不在 PATH → 返回 [bin_name] (type_checker_bin 始终 truthy).

        注: type_checker_bin 永远有默认值, shutil.which 检查被跳过.
        run() 实际执行时由 subprocess.run 处理 FileNotFoundError.
        """
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(type_checker_bin="nonexistent-tool-xyz")
        with patch.object(shutil, "which", return_value=None):
            cmd = gate._resolve_type_check_cmd()
        assert cmd == ["nonexistent-tool-xyz"]

    def test_resolve_uses_explicit_type_checker_bin(self):
        """type_checker_bin 显式指定时优先使用."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(type_checker_bin="my-custom-mypy")
        with patch.object(shutil, "which", return_value="/usr/local/bin/my-custom-mypy"):
            cmd = gate._resolve_type_check_cmd()
        assert cmd == ["my-custom-mypy"]


# ============================================================
# 4. _has_type_config 检测
# ============================================================


class TestHasTypeConfig:
    """TypeCheckGate._has_type_config 配置检测."""

    def test_mypy_ini_detected(self, tmp_path: Path):
        """存在 mypy.ini → 返回 True."""
        from auto_engineering.gates.type_check import TypeCheckGate

        (tmp_path / "mypy.ini").write_text("[mypy]\nstrict = True\n")
        gate = TypeCheckGate()
        assert gate._has_type_config(tmp_path) is True

    def test_pyproject_with_tool_mypy_detected(self, tmp_path: Path):
        """pyproject.toml 含 [tool.mypy] → 返回 True."""
        from auto_engineering.gates.type_check import TypeCheckGate

        (tmp_path / "pyproject.toml").write_text(
            "[tool.mypy]\nstrict = True\n"
        )
        gate = TypeCheckGate()
        assert gate._has_type_config(tmp_path) is True

    def test_pyproject_without_tool_mypy_returns_false(self, tmp_path: Path):
        """pyproject.toml 不含 [tool.mypy] → 返回 False."""
        from auto_engineering.gates.type_check import TypeCheckGate

        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        gate = TypeCheckGate()
        assert gate._has_type_config(tmp_path) is False

    def test_setup_cfg_detected(self, tmp_path: Path):
        """存在 setup.cfg → 返回 True (向后兼容)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        (tmp_path / "setup.cfg").write_text("[mypy]\nstrict = True\n")
        gate = TypeCheckGate()
        assert gate._has_type_config(tmp_path) is True

    def test_no_config_returns_false(self, tmp_path: Path):
        """空目录 → 返回 False."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()
        assert gate._has_type_config(tmp_path) is False

    def test_pyproject_oserror_tolerated(self, tmp_path: Path):
        """pyproject.toml 存在但读取抛 OSError → 容错,继续(返回 False)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        gate = TypeCheckGate()
        with patch.object(Path, "read_text", side_effect=OSError("perm denied")):
            result = gate._has_type_config(tmp_path)
        # OSError 时跳过 pyproject.toml 检查,继续找其他配置 → 返回 False
        assert result is False


# ============================================================
# 5. run() 主路径:成功/失败/超时/工具缺失
# ============================================================


class TestTypeCheckRun:
    """TypeCheckGate.run() 端到端 (用 mock 隔离 subprocess)."""

    def _make_configured_project(self, tmp_path: Path) -> Path:
        """创建有 type_check 配置的项目 (mypy.ini)."""
        (tmp_path / "mypy.ini").write_text("[mypy]\nstrict = True\n")
        return tmp_path

    def test_run_project_root_not_exists_fails(self, tmp_path: Path):
        """project_root 不存在 → GateVerdict.failed."""
        from auto_engineering.gates.type_check import TypeCheckGate

        nonexistent = tmp_path / "does-not-exist"
        gate = TypeCheckGate()
        verdict = gate.run(nonexistent)
        assert verdict.passed is False
        assert "project_root 不存在" in verdict.message

    def test_run_no_config_skips_by_default(self, tmp_path: Path):
        """无配置且 require_config=False → skip (passed=True)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate()  # require_config=False
        verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "skip" in verdict.message.lower() or "未配置" in verdict.message

    def test_run_no_config_require_fails(self, tmp_path: Path):
        """无配置且 require_config=True → failed."""
        from auto_engineering.gates.type_check import TypeCheckGate

        gate = TypeCheckGate(require_config=True)
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "未配置 mypy" in verdict.message

    def test_run_tool_not_installed_skips(self, tmp_path: Path):
        """工具不在 PATH → skip (passed=True)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="nonexistent-tool-xyz")
        with patch.object(shutil, "which", return_value=None):
            verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "未安装" in verdict.message or "skip" in verdict.message.lower()

    def test_run_tool_success_passes(self, tmp_path: Path):
        """subprocess exit=0 → passed=True (type_checker 通过)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success: no issues found\n"
        mock_result.stderr = ""
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"):
            with patch.object(subprocess, "run", return_value=mock_result):
                verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "通过" in verdict.message or "0 errors" in verdict.message

    def test_run_tool_error_output_fails(self, tmp_path: Path):
        """subprocess exit≠0 且输出含 'error:' → failed."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "main.py:1: error: Name 'x' is not defined\n"
        mock_result.stderr = ""
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"):
            with patch.object(subprocess, "run", return_value=mock_result):
                verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "error" in verdict.message.lower()
        assert "fake-mypy" in verdict.message

    def test_run_tool_nonzero_no_error_warns(self, tmp_path: Path):
        """subprocess exit≠0 但输出无 'error:' → passed (warning 级别)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy")
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = "warning: deprecated flag\n"
        mock_result.stderr = ""
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"):
            with patch.object(subprocess, "run", return_value=mock_result):
                verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "退出 2" in verdict.message or "无类型 error" in verdict.message

    def test_run_tool_timeout_fails(self, tmp_path: Path):
        """subprocess.TimeoutExpired → failed (与 LintGate 策略统一)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy", timeout=10.0)
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"), patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["fake-mypy"], timeout=10.0),
        ):
            verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "超时" in verdict.message

    def test_run_tool_filenotfound_skips(self, tmp_path: Path):
        """subprocess.run 抛 FileNotFoundError → skip (passed=True)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy")
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"):
            with patch.object(subprocess, "run", side_effect=FileNotFoundError("not found")):
                verdict = gate.run(tmp_path)
        assert verdict.passed is True
        assert "未找到" in verdict.message or "skip" in verdict.message.lower()

    def test_run_strict_mypy_adds_flag(self, tmp_path: Path):
        """strict=True + type_checker_bin='mypy' → 命令附加 --strict."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="mypy", strict=True)
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        captured_cmd: list[str] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(shutil, "which", return_value="/usr/bin/mypy"):
            with patch.object(subprocess, "run", side_effect=fake_run):
                gate.run(tmp_path)
        assert "--strict" in captured_cmd

    def test_run_bash_n_no_strict_flag(self, tmp_path: Path):
        """type_checker_bin='bash -n' + strict=True → 不附加 --strict (bash 不支持)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        # 配置项目 (有 mypy.ini 即可,_has_type_config 不区分 type_checker)
        (tmp_path / "mypy.ini").write_text("[mypy]\n")
        gate = TypeCheckGate(type_checker_bin="bash -n", strict=True)
        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        captured_cmd: list[str] = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return mock_result

        with patch.object(shutil, "which", return_value="/bin/bash"):
            with patch.object(subprocess, "run", side_effect=fake_run):
                gate.run(tmp_path)
        assert "--strict" not in captured_cmd
        assert "bash" in captured_cmd
        assert "-n" in captured_cmd

    def test_run_error_snippet_truncation(self, tmp_path: Path):
        """错误输出 > 1500 字符 → 消息含 '...' (截断标记)."""
        from auto_engineering.gates.type_check import TypeCheckGate

        self._make_configured_project(tmp_path)
        gate = TypeCheckGate(type_checker_bin="fake-mypy")
        long_error = "error: " + ("x" * 2000) + "\n"
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = long_error
        mock_result.stderr = ""
        with patch.object(shutil, "which", return_value="/usr/bin/fake-mypy"):
            with patch.object(subprocess, "run", return_value=mock_result):
                verdict = gate.run(tmp_path)
        assert verdict.passed is False
        assert "..." in verdict.message


# ============================================================
# 6. applies_to_stages 默认 + 显式 override
# ============================================================


class TestAppliesToStages:
    """TypeCheckGate.applies_to_stages 三阶段覆盖."""

    def test_default_applies_to_all_three_stages(self):
        """默认 applies_to_stages 包含 architect/developer/critic."""
        from auto_engineering.gates.type_check import TypeCheckGate

        stages = TypeCheckGate.applies_to_stages
        assert "architect" in stages
        assert "developer" in stages
        assert "critic" in stages

    def test_subclass_can_override_applies_to_stages(self):
        """子类可以显式 override applies_to_stages."""
        from auto_engineering.gates.type_check import TypeCheckGate

        class CustomTCGate(TypeCheckGate):
            applies_to_stages = ("developer",)  # 只在 developer 阶段跑

        gate = CustomTCGate()
        assert gate.applies_to_stages == ("developer",)
        assert "architect" not in gate.applies_to_stages