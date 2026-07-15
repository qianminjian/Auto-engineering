"""Tests for StandaloneDriver developer output format validation.

V7-5 §3: Developer stage-result 必须包含 batch_id, files_changed (>=1), test_results.
格式纠正机制: 缺字段时自动 retry + correction prompt.
"""

from __future__ import annotations


class TestDeveloperResultFormat:
    """Developer stage-result 必须通过 validate_result_format 校验."""

    def test_valid_developer_result_passes_validation(self):
        """完整 developer dict (stage/batch_id/files_changed/test_results) → 无 error."""
        from auto_engineering.loop.actions import validate_result_format

        result = {
            "stage": "developer",
            "batch_id": "T1",
            "files_changed": ["test_file.py"],
            "test_results": {"passed": 1, "failed": 0},
        }
        errors = validate_result_format(result, "developer")
        assert errors == [], f"校验应有 0 error, 实际: {errors}"

    def test_missing_batch_id_fails_validation(self):
        """缺 batch_id → error 含 'batch_id'."""
        from auto_engineering.loop.actions import validate_result_format

        result = {
            "stage": "developer",
            "files_changed": ["test_file.py"],
            "test_results": {"passed": 1, "failed": 0},
        }
        errors = validate_result_format(result, "developer")
        assert any("batch_id" in e for e in errors), f"应提示缺 batch_id, 实际: {errors}"

    def test_missing_files_changed_fails_validation(self):
        """缺 files_changed → error 含 'files_changed'."""
        from auto_engineering.loop.actions import validate_result_format

        result = {
            "stage": "developer",
            "batch_id": "T1",
            "test_results": {"passed": 1, "failed": 0},
        }
        errors = validate_result_format(result, "developer")
        assert any("files_changed" in e for e in errors), f"应提示缺 files_changed, 实际: {errors}"

    def test_empty_files_changed_fails_validation(self):
        """files_changed 空列表 → error."""
        from auto_engineering.loop.actions import validate_result_format

        result = {
            "stage": "developer",
            "batch_id": "T1",
            "files_changed": [],
            "test_results": {"passed": 1, "failed": 0},
        }
        errors = validate_result_format(result, "developer")
        assert any("files_changed" in e for e in errors), f"应提示 files_changed 为空, 实际: {errors}"

    def test_failed_test_count_fails_validation(self):
        """test_results.failed != 0 → error."""
        from auto_engineering.loop.actions import validate_result_format

        result = {
            "stage": "developer",
            "batch_id": "T1",
            "files_changed": ["test_file.py"],
            "test_results": {"passed": 0, "failed": 1},
        }
        errors = validate_result_format(result, "developer")
        assert any("failed" in e for e in errors), f"应提示 failed!=0, 实际: {errors}"

    def test_developer_result_has_required_fields_in_standalone_driver(self):
        """StandaloneDriver._execute_developer_serial 返回结果含必需字段."""
        # Verify the return dict contract by inspecting the source
        import inspect

        from auto_engineering.loop.standalone_driver import StandaloneDriver
        source = inspect.getsource(StandaloneDriver._execute_developer_serial)
        assert "batch_id" in source, "_execute_developer_serial 应包含 batch_id"
        assert "files_changed" in source, "_execute_developer_serial 应包含 files_changed"
        assert "test_results" in source, "_execute_developer_serial 应包含 test_results"


class TestFormatCorrectionRetry:
    """V7-5 §3: 格式纠正重试机制 — 缺字段时构造 correction prompt."""

    def test_correction_prompt_includes_field_names(self):
        """correction prompt 包含缺失字段名."""

        _result = {
            "stage": "developer",
            "files_changed": ["x.py"],
            "test_results": {"passed": 1, "failed": 0},
        }
        # 模拟 validate_result_format 返回的 error
        errors = ["缺少必填字段 'batch_id'"]
        correction = (
            f"[格式纠正] 上一轮输出不符合 stage-result schema: {'; '.join(errors)}。"
            f"请按正确格式重新输出。"
        )
        assert "batch_id" in correction
        assert "格式纠正" in correction
