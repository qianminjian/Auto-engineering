"""Tests for V7-8 fidelity benchmark framework.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


class TestV7_8_BenchmarkDataModel:
    """V7-8: BenchmarkReq + BenchmarkRun + RunMetrics 数据模型."""

    def test_benchmark_data_model_importable(self) -> None:
        """数据模型模块可导入."""
        from auto_engineering.benchmark import BenchmarkReq, BenchmarkRun, RunMetrics

        assert BenchmarkReq is not None
        assert BenchmarkRun is not None
        assert RunMetrics is not None

    def test_benchmark_req_has_required_fields(self) -> None:
        """BenchmarkReq 包含 id/category/requirement/design_doc_path."""
        from auto_engineering.benchmark import BenchmarkReq

        req = BenchmarkReq(
            id="R01",
            category="simple_function",
            requirement="Implement fibonacci",
        )
        assert req.id == "R01"
        assert req.category == "simple_function"
        assert req.requirement == "Implement fibonacci"
        assert req.design_doc_path is None

    def test_run_metrics_has_six_dimensions(self) -> None:
        """RunMetrics 包含 6 维指标."""
        from auto_engineering.benchmark import RunMetrics

        m = RunMetrics(
            convergence="GOAL_ACHIEVED",
            gate_pass_rate=1.0,
            critic_approve=True,
            lint_first_pass=True,
            test_pass_rate=1.0,
            total_ticks=5,
            total_wall_seconds=120.0,
        )
        assert m.convergence == "GOAL_ACHIEVED"
        assert m.gate_pass_rate == 1.0
        assert m.critic_approve is True
        assert m.lint_first_pass is True
        assert m.test_pass_rate == 1.0
        assert m.total_ticks == 5
        assert m.total_wall_seconds == 120.0

    def test_benchmark_run_links_req_and_metrics(self) -> None:
        """BenchmarkRun 关联 requirement + driver + metrics."""
        from auto_engineering.benchmark import BenchmarkReq, BenchmarkRun, RunMetrics

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="Implement fibonacci")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=0.9,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=3, total_wall_seconds=45.0,
        )
        run = BenchmarkRun(
            requirement=req,
            driver="AgentDriver",
            metrics=metrics,
            notes="ran clean",
        )
        assert run.requirement.id == "R01"
        assert run.driver == "AgentDriver"
        assert run.metrics.convergence == "GOAL_ACHIEVED"


class TestV7_8_DefaultRequirements:
    """V7-8: 10 个默认基准需求定义."""

    def test_default_requirements_has_10_items(self) -> None:
        """default_requirements() 返回 10 个需求."""
        from auto_engineering.benchmark import default_requirements

        reqs = default_requirements()
        assert len(reqs) == 10

    def test_default_requirements_covers_four_categories(self) -> None:
        """覆盖全部 4 个类别: simple_function(3) / medium_crud(3) / complex(2) / with_design_doc(2)."""
        from auto_engineering.benchmark import default_requirements

        reqs = default_requirements()
        categories = {r.category for r in reqs}
        expected = {"simple_function", "medium_crud", "complex_multi_module", "with_design_doc"}
        assert categories == expected

    def test_default_requirements_three_simple_functions(self) -> None:
        """simple_function 类别恰好 3 个."""
        from auto_engineering.benchmark import default_requirements

        reqs = default_requirements()
        simple = [r for r in reqs if r.category == "simple_function"]
        assert len(simple) == 3

    def test_default_requirements_has_unique_ids(self) -> None:
        """所有需求 ID 唯一."""
        from auto_engineering.benchmark import default_requirements

        reqs = default_requirements()
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))


class TestV7_8_DiffCalculation:
    """V7-8: 双驱动差异计算."""

    def test_calc_diff_returns_percentage(self) -> None:
        """calc_diff() 返回百分比差异."""
        from auto_engineering.benchmark import calc_diff

        diff = calc_diff(0.9, 0.8)
        assert abs(diff - 0.10) < 1e-9  # floating point: |0.9-0.8| ≈ 0.10

    def test_calc_diff_zero_when_equal(self) -> None:
        """相等时差异为 0."""
        from auto_engineering.benchmark import calc_diff

        assert calc_diff(0.75, 0.75) == 0.0

    def test_dimension_diff_table_all_six_dimensions(self) -> None:
        """dimension_diff_table() 输出含全部 6 维对比."""
        from auto_engineering.benchmark import RunMetrics, dimension_diff_table

        agent = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=4, total_wall_seconds=60.0,
        )
        standalone = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=0.85,
            critic_approve=True, lint_first_pass=False,
            test_pass_rate=0.95, total_ticks=6, total_wall_seconds=90.0,
        )
        rows = dimension_diff_table(agent, standalone)
        assert len(rows) == 6
        # 每行含 dimension/agent/standalone/diff/verdict
        for row in rows:
            assert "dimension" in row
            assert "agent" in row
            assert "standalone" in row
            assert "diff" in row
            assert "verdict" in row


class TestV7_8_ReportGeneration:
    """V7-8: 保真度报告生成."""

    def test_generate_report_creates_file(self, tmp_path) -> None:
        """generate_report() 写文件到指定路径."""
        from auto_engineering.benchmark import (
            BenchmarkReq, BenchmarkRun, RunMetrics,
            generate_report, default_requirements,
        )

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="Implement fibonacci")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=3, total_wall_seconds=30.0,
        )
        runs = [
            BenchmarkRun(requirement=req, driver="AgentDriver",
                         metrics=metrics, notes=""),
            BenchmarkRun(requirement=req, driver="StandaloneDriver",
                         metrics=metrics, notes=""),
        ]

        report_path = tmp_path / "benchmark.md"
        generate_report(runs, report_path)

        assert report_path.is_file()
        content = report_path.read_text()
        assert "v7.0 双驱动保真度基准" in content
        assert "R01" in content
        assert "AgentDriver" in content
        assert "StandaloneDriver" in content

    def test_generate_report_has_summary_table(self, tmp_path) -> None:
        """报告含汇总对比表."""
        from auto_engineering.benchmark import (
            BenchmarkReq, BenchmarkRun, RunMetrics, generate_report,
        )

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="test")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=2, total_wall_seconds=10.0,
        )
        runs = [
            BenchmarkRun(requirement=req, driver="AgentDriver",
                         metrics=metrics, notes=""),
            BenchmarkRun(requirement=req, driver="StandaloneDriver",
                         metrics=metrics, notes=""),
        ]

        report_path = tmp_path / "benchmark.md"
        generate_report(runs, report_path)

        content = report_path.read_text()
        assert "汇总" in content or "Summary" in content

    def test_generate_report_has_recommendations(self, tmp_path) -> None:
        """报告含场景推荐."""
        from auto_engineering.benchmark import (
            BenchmarkReq, BenchmarkRun, RunMetrics, generate_report,
        )

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="test")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=2, total_wall_seconds=10.0,
        )
        runs = [
            BenchmarkRun(requirement=req, driver="AgentDriver",
                         metrics=metrics, notes=""),
            BenchmarkRun(requirement=req, driver="StandaloneDriver",
                         metrics=metrics, notes=""),
        ]

        report_path = tmp_path / "benchmark.md"
        generate_report(runs, report_path)

        content = report_path.read_text()
        assert "建议" in content or "Recommend" in content


class TestV7_8_BenchmarkValidation:
    """V7-8: 基准数据校验规则."""

    def test_validate_runs_detects_missing_driver(self) -> None:
        """缺失一个 driver 时 validate_runs 报错."""
        from auto_engineering.benchmark import (
            BenchmarkReq, BenchmarkRun, RunMetrics, validate_runs,
        )

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="test")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=2, total_wall_seconds=10.0,
        )
        runs = [
            BenchmarkRun(requirement=req, driver="AgentDriver",
                         metrics=metrics, notes=""),
            # missing StandaloneDriver
        ]
        errors = validate_runs(runs)
        assert len(errors) > 0
        assert any("StandaloneDriver" in e for e in errors)

    def test_validate_runs_passes_complete_data(self) -> None:
        """完整双驱动数据通过校验."""
        from auto_engineering.benchmark import (
            BenchmarkReq, BenchmarkRun, RunMetrics, validate_runs,
        )

        req = BenchmarkReq(id="R01", category="simple_function",
                           requirement="test")
        metrics = RunMetrics(
            convergence="GOAL_ACHIEVED", gate_pass_rate=1.0,
            critic_approve=True, lint_first_pass=True,
            test_pass_rate=1.0, total_ticks=2, total_wall_seconds=10.0,
        )
        runs = [
            BenchmarkRun(requirement=req, driver="AgentDriver",
                         metrics=metrics, notes=""),
            BenchmarkRun(requirement=req, driver="StandaloneDriver",
                         metrics=metrics, notes=""),
        ]
        errors = validate_runs(runs)
        assert len(errors) == 0
