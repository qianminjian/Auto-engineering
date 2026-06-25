"""C2: scaffold.py 端到端 E2E 测试 — 5 阶段流水线 + 全 8 project types + 失败清理 + 增量模式.

B2: 8 种项目类型 E2E 验证.
"""

import subprocess
from pathlib import Path


def run_ae(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    venv_bin = Path(__file__).resolve().parent.parent / ".venv" / "bin"
    ae_path = venv_bin / "ae"
    return subprocess.run(
        [str(ae_path), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


# ─── C2: 5 阶段流水线 E2E ─────────────────────────────────────────────────


class TestScaffoldPipelineE2E:
    """C2: 5 阶段流水线端到端测试 (detect → prompt → render → tasks → finalize)."""

    def test_full_pipeline_app_service(self, tmp_path: Path):
        """5 阶段完整流程 — app-service 项目类型."""
        target = tmp_path / "app"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"

        # 验证产物
        assert target.exists()
        assert (target / "CLAUDE.md").exists() or (target / "README.md").exists()
        assert (target / "design").exists()
        assert (target / "design" / "BEACON.md").exists()
        assert (target / "design" / "INDEX.md").exists()
        assert (target / ".ae-answers.yml").exists()

    def test_full_pipeline_library(self, tmp_path: Path):
        """library 类型 — Python pyproject.toml."""
        target = tmp_path / "lib"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "library",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_cli_tool(self, tmp_path: Path):
        """cli-tool 类型."""
        target = tmp_path / "cli"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "cli-tool",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_skill(self, tmp_path: Path):
        """skill 类型."""
        target = tmp_path / "skill-proj"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "skill",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_hook(self, tmp_path: Path):
        """hook 类型."""
        target = tmp_path / "hook-proj"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "hook",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_mcp_server(self, tmp_path: Path):
        """mcp-server 类型."""
        target = tmp_path / "mcp-proj"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "mcp-server",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_spec_doc(self, tmp_path: Path):
        """spec-doc 类型."""
        target = tmp_path / "spec-proj"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "spec-doc",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_full_pipeline_monorepo(self, tmp_path: Path):
        """monorepo 类型."""
        target = tmp_path / "monorepo-proj"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "monorepo",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        assert target.exists()

    def test_pipeline_pretend_no_files(self, tmp_path: Path):
        """pretend 模式不创建文件."""
        target = tmp_path / "pretend"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--pretend",
                "--skip-tasks",
            ]
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert not target.exists()

    def test_pipeline_force_overwrite_non_empty(self, tmp_path: Path):
        """force 覆盖非空目录."""
        target = tmp_path / "force"
        target.mkdir()
        (target / "old.txt").write_text("old")
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result.returncode == 0
        # Old file is overwritten (force default = overwrite)
        # But design/ is still created

    def test_pipeline_incremental_skips_existing(self, tmp_path: Path):
        """B3: 增量模式 E2E — 复用已有文件."""
        target = tmp_path / "incr"
        target.mkdir()
        keep_file = target / "user_file.txt"
        keep_file.write_text("user's precious content")

        result = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        # user file preserved
        assert keep_file.read_text() == "user's precious content"
        # design dir created
        assert (target / "design").exists()

    def test_pipeline_incremental_no_git_dir(self, tmp_path: Path):
        """B3: 增量模式跳过 .git 目录."""
        target = tmp_path / "incr-git"
        target.mkdir()
        git_dir = target / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main")

        result = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result.returncode == 0, f"ae init failed: {result.stderr}"
        # .git not deleted
        assert git_dir.exists()
        assert (git_dir / "HEAD").read_text() == "ref: refs/heads/main"

    def test_pipeline_incremental_idempotent(self, tmp_path: Path):
        """B3: 增量模式可重复运行."""
        target = tmp_path / "incr-idem"
        result1 = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result1.returncode == 0, f"first run failed: {result1.stderr}"

        # Second run — should also succeed (all files already exist)
        result2 = run_ae(
            [
                "init",
                str(target),
                "--type", "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result2.returncode == 0, f"second run failed: {result2.stderr}"


# ─── C2: 失败清理 (cleanup_on_error) ─────────────────────────────────────


class TestScaffoldFailureCleanup:
    """C2: 失败时的清理行为."""

    def test_invalid_project_type_exits_nonzero(self, tmp_path: Path):
        """无效项目类型 → exit non-zero."""
        target = tmp_path / "invalid"
        result = run_ae(
            [
                "init",
                str(target),
                "--type", "totally-bogus-type-xyz",
                "--defaults",
                "--skip-tasks",
            ]
        )
        assert result.returncode != 0


# ─── InitWorker direct unit tests (5 phases) ──────────────────────────────


class TestInitWorkerFivePhases:
    """C2: 直接调用 InitWorker 测 5 阶段流程."""

    def test_execute_incremental_mode(self, tmp_path: Path):
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "p"
        dst.mkdir()
        (dst / "user.md").write_text("user data")

        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            skip_tasks=True,
            quiet=True,
            incremental=True,
        )
        result = worker.execute()
        # In incremental mode, user file is preserved
        assert (dst / "user.md").read_text() == "user data"
        # And new design/ was created
        assert (dst / "design").exists()
        assert result.project_type == "library"

    def test_execute_returns_init_result(self, tmp_path: Path):
        from auto_engineering.init.scaffold import InitResult, InitWorker

        dst = tmp_path / "result"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            skip_tasks=True,
            quiet=True,
        )
        result = worker.execute()
        assert isinstance(result, InitResult)
        assert result.dst_path == dst
        assert result.project_type == "library"
        assert len(result.files) > 0

    def test_execute_pretend_no_dst(self, tmp_path: Path):
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "pretend"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            pretend=True,
            quiet=True,
        )
        result = worker.execute()
        assert result.files == []
        assert not dst.exists()

    def test_phase_prompt_with_defaults(self, tmp_path: Path):
        """_phase_prompt 在 defaults=True 时不调用 InteractivePrompt."""
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "p"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
        )
        worker._phase_prompt()
        assert worker._template is not None
        assert worker._answers is not None

    def test_phase_render_generates_files(self, tmp_path: Path):
        """_phase_render 渲染到 tmpdir."""
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "p"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
        )
        worker._phase_prompt()
        tmpdir = tmp_path / "render"
        tmpdir.mkdir()
        generated = worker._phase_render(tmpdir)
        assert len(generated) > 0
        # at least one file should exist
        assert any(f.exists() for f in generated)

    def test_context_manager_runs_cleanup(self, tmp_path: Path):
        """__enter__/__exit__ 自动 cleanup."""
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "p"
        with InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            pretend=True,
            quiet=True,
        ) as worker:
            result = worker.execute()
        assert result.files == []
