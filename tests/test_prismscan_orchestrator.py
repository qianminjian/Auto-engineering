"""Tests for PrismScan orchestrator.py — PrismScanOrchestrator."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock


class TestPrismScanOrchestrator:
    """PrismScanOrchestrator 核心功能测试."""

    def test_init_creates_orchestrator(self):
        import os

        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            orch = PrismScanOrchestrator(project_root=tmp)
            assert orch.project_root == os.path.realpath(tmp)
            assert orch._stage == "init"

    def test_run_discover_extract_on_python_project(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'")
            (root / "src" / "core").mkdir(parents=True)
            (root / "src" / "core" / "main.py").write_text("print('hello')")

            orch = PrismScanOrchestrator(project_root=str(root))
            result = orch.run_discover_extract()
            assert result["action"] == "analyze"
            assert "context" in result
            assert "project_shape" in result["context"]
            assert result["context"]["project_shape"]["project_name"] == root.name

    def test_run_outputs_action_json(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("print('hello')")

            orch = PrismScanOrchestrator(project_root=str(root))
            action = orch.run_discover_extract()
            assert isinstance(action, dict)
            assert "action" in action
            assert "stage" in action
            assert "thread_id" in action

    def test_check_result_validates_analysis_result(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            orch.run_discover_extract()

            valid_result = {
                "architecture": {"pattern": "layered", "description": "test"},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            result_path = Path(tmp) / "analysis_result.json"
            result_path.write_text(json.dumps(valid_result))
            validated = orch.check_result(str(result_path))
            assert validated["stage"] == "analyze"

    def test_check_result_rejects_invalid_result(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            orch.run_discover_extract()

            invalid_result = {"wrong": "format"}
            result_path = Path(tmp) / "bad_result.json"
            result_path.write_text(json.dumps(invalid_result))
            validated = orch.check_result(str(result_path))
            assert validated.get("action") == "error"


class TestOrchestratorErrorHandling:
    """异常处理测试."""

    def test_nonexistent_directory_raises(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        orch = PrismScanOrchestrator(project_root="/nonexistent/path/xyz")
        result = orch.run_discover_extract()
        assert result["action"] == "error"


class TestOrchestratorStateMachine:
    """S5.1: _stage 状态转换 init → analyze → complete."""

    def test_stage_transitions_within_single_instance(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='state-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            assert orch._stage == "init"

            result = orch.run_discover_extract()
            assert result["action"] == "analyze"
            assert orch._stage == "analyze"

            valid = {
                "architecture": {"pattern": "script", "description": "test", "layers": []},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            rpath = root / "result.json"
            rpath.write_text(json.dumps(valid))
            validated = orch.check_result(str(rpath))
            assert validated["status"] == "valid"
            assert orch._stage == "complete"

    def test_stage_stays_init_on_error(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        orch = PrismScanOrchestrator(project_root="/nonexistent/path/xyz")
        assert orch._stage == "init"
        result = orch.run_discover_extract()
        assert result["action"] == "error"
        assert orch._stage == "init"

    def test_stage_stays_current_on_check_result_error(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='stage-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            orch.run_discover_extract()
            assert orch._stage == "analyze"

            # check-result with invalid data — stage stays at "analyze"
            bad_path = root / "bad.json"
            bad_path.write_text('{"wrong": "format"}')
            result = orch.check_result(str(bad_path))
            assert result["action"] == "error"
            assert orch._stage == "analyze"


class TestOrchestratorParseError:
    """S3.5: Schema 通过但 from_dict 解析失败 → PARSE_ERROR."""

    def test_schema_passes_but_from_dict_fails(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='parse-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            orch.run_discover_extract()

            # mock jsonschema_validate 绕过 Schema 层, 直接测 from_dict
            # architecture 缺 "pattern" → ArchitectureInfo.from_dict 会 KeyError
            broken = {
                "architecture": {"description": "test", "layers": ["x"]},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            rpath = root / "broken.json"
            rpath.write_text(json.dumps(broken))

            with mock.patch(
                "auto_engineering.prismscan.orchestrator.jsonschema_validate",
                return_value=True,
            ):
                result = orch.check_result(str(rpath))
                assert result["action"] == "error"
                assert result["error_code"] == "PARSE_ERROR"


class TestOrchestratorInternalException:
    """S1.4: discover/extract 内部异常 → INTERNAL_ERROR."""

    def test_discover_extract_internal_exception(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='exception-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            with mock.patch(
                "auto_engineering.prismscan.orchestrator.discover",
                side_effect=RuntimeError("simulated crash"),
            ):
                result = orch.run_discover_extract()
                assert result["action"] == "error"
                assert result["error_code"] == "INTERNAL_ERROR"
                assert "simulated crash" in result["message"]

    def test_check_result_internal_exception(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='exception-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch = PrismScanOrchestrator(project_root=str(root))
            orch.run_discover_extract()

            valid = {
                "architecture": {"pattern": "script", "description": "test", "layers": []},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            rpath = root / "result.json"
            rpath.write_text(json.dumps(valid))

            with mock.patch(
                "auto_engineering.prismscan.orchestrator.AnalysisResult.from_dict",
                side_effect=Exception("unexpected crash"),
            ):
                result = orch.check_result(str(rpath))
                assert result["action"] == "error"
                assert result["error_code"] == "INTERNAL_ERROR"
                assert "unexpected crash" in result["message"]


class TestOrchestratorIndependentCheckResult:
    """S3.7: check-result 无前置 discover-extract 独立调用."""

    def test_check_result_without_discover_extract(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='independent-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            # 不调 discover-extract, 直接调 check-result
            orch = PrismScanOrchestrator(project_root=str(root))
            assert orch._stage == "init"

            valid = {
                "architecture": {"pattern": "script", "description": "test", "layers": []},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            rpath = root / "result.json"
            rpath.write_text(json.dumps(valid))

            result = orch.check_result(str(rpath))
            assert result["status"] == "valid"
            assert orch._stage == "complete"

    def test_two_instances_independent_check(self):
        """验证两个独立 Orchestrator 实例各自工作."""
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='two-inst-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            # Instance 1: run discover-extract
            orch1 = PrismScanOrchestrator(project_root=str(root))
            r1 = orch1.run_discover_extract()
            assert r1["action"] == "analyze"
            assert orch1._stage == "analyze"

            # Instance 2: only check-result (simulates separate CLI process)
            orch2 = PrismScanOrchestrator(project_root=str(root))
            assert orch2._stage == "init"  # fresh state
            assert orch2._thread_id != orch1._thread_id

            valid = {
                "architecture": {"pattern": "script", "description": "test", "layers": []},
                "business_domains": [],
                "api_surface": {"total_endpoints": 0},
                "data_models": [],
                "security": {},
                "scheduled_tasks": [],
                "deployment": {},
            }
            rpath = root / "result.json"
            rpath.write_text(json.dumps(valid))

            r2 = orch2.check_result(str(rpath))
            assert r2["status"] == "valid"
            assert orch2._stage == "complete"
            # orch1 unchanged
            assert orch1._stage == "analyze"


class TestOrchestratorRepeatDiscoverExtract:
    """S5.3: 重复 discover-extract — thread_id 唯一 + data_file 覆盖."""

    def test_repeat_discover_extract_unique_thread_ids(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='repeat-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch1 = PrismScanOrchestrator(project_root=str(root))
            r1 = orch1.run_discover_extract()
            tid1 = r1["thread_id"]

            orch2 = PrismScanOrchestrator(project_root=str(root))
            r2 = orch2.run_discover_extract()
            tid2 = r2["thread_id"]

            assert tid1 != tid2

    def test_repeat_discover_extract_overwrites_data_file(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='overwrite-test'")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("pass")

            orch1 = PrismScanOrchestrator(project_root=str(root))
            r1 = orch1.run_discover_extract()
            df1 = Path(r1["data_file"])
            mtime1 = df1.stat().st_mtime

            orch2 = PrismScanOrchestrator(project_root=str(root))
            r2 = orch2.run_discover_extract()
            df2 = Path(r2["data_file"])
            mtime2 = df2.stat().st_mtime

            # 同一路径
            assert df1 == df2
            # 第二次写入更新了 mtime
            assert mtime2 >= mtime1


class TestOrchestratorConstructorInjection:
    """构造参数注入: db_path / guardrail / gate_runner."""

    def test_custom_db_path(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        with tempfile.TemporaryDirectory() as tmp:
            orch = PrismScanOrchestrator(project_root=tmp, db_path="/custom/path/db.sqlite")
            assert orch._db_path == "/custom/path/db.sqlite"

    def test_guardrail_and_gate_runner_injection(self):
        from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator

        guardrail = object()
        gate_runner = object()

        with tempfile.TemporaryDirectory() as tmp:
            orch = PrismScanOrchestrator(
                project_root=tmp,
                guardrail=guardrail,
                gate_runner=gate_runner,
            )
            assert orch._guardrail is guardrail
            assert orch._gate_runner is gate_runner
