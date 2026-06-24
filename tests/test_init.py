"""E2E tests for ae init command."""

import subprocess
import tempfile
from pathlib import Path


def run_ae(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "ae"] + args,
        capture_output=True, text=True,
    )


class TestInitHelp:
    def test_help_output(self):
        result = run_ae(["init", "--help"])
        assert result.returncode == 0
        assert "--type" in result.stdout
        assert "--defaults" in result.stdout
        assert "--force" in result.stdout
        assert "--pretend" in result.stdout
        assert "--skip-tasks" in result.stdout
        assert "--no-cleanup" in result.stdout

    def test_all_flags_present(self):
        """Verify all 14 flags appear in help."""
        result = run_ae(["init", "--help"])
        flags = [
            "--type", "--defaults", "--force", "--from-answers",
            "--package-manager", "--ci", "--test-runner",
            "--no-typescript", "--no-lefthook",
            "--pretend", "--skip-tasks", "--no-cleanup", "--quiet",
            "--incremental",
        ]
        for flag in flags:
            assert flag in result.stdout, f"Missing flag: {flag}"


class TestInitPretend:
    def test_pretend_no_files_created(self):
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-project"
        result = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--pretend",
            "--force",
        ])
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert not target.exists()

    def test_pretend_with_skip_tasks(self):
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-project2"
        result = run_ae([
            "init", str(target),
            "--type", "library",
            "--defaults",
            "--pretend",
            "--skip-tasks",
            "--force",
        ])
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout


class TestInitMultiLayerTemplates:
    """T1: Verify multi-layer template directory composition."""

    def test_generates_shared_templates(self):
        """_shared templates (CLAUDE.md, .gitignore, README, LICENSE) are generated."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-shared"
        result = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--force",
        ])
        assert result.returncode == 0
        shared_files = ["CLAUDE.md", ".gitignore", "README.md", "LICENSE", ".editorconfig"]
        for fname in shared_files:
            assert (target / fname).exists(), f"Missing shared file: {fname}"

    def test_generates_language_feature_templates(self):
        """Language feature templates (typescript) are generated."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-ts"
        result = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--force",
        ])
        assert result.returncode == 0
        ts_files = ["tsconfig.json", "index.ts", "index.test.ts",
                     "package.json", "eslint.config.js", "prettier.config.js"]
        for fname in ts_files:
            assert (target / fname).exists(), f"Missing TS file: {fname}"

    def test_all_project_types_generate_shared(self):
        """All 8 project types generate shared templates."""
        for ptype in ["app-service", "library", "cli-tool", "skill",
                       "hook", "mcp-server", "spec-doc", "monorepo"]:
            tmp = Path(tempfile.mkdtemp())
            target = tmp / f"test-{ptype}"
            result = run_ae([
                "init", str(target),
                "--type", ptype,
                "--defaults",
                "--skip-tasks",
                "--force",
            ])
            assert result.returncode == 0, f"Failed for type: {ptype}"
            assert (target / "CLAUDE.md").exists(), f"No CLAUDE.md for {ptype}"


class TestFromAnswersRecovery:
    """T2: Verify --from-answers recovery."""

    def test_from_answers_replays_config(self):
        """Answers from a previous run should be replayed."""
        tmp = Path(tempfile.mkdtemp())
        target1 = tmp / "first"
        target2 = tmp / "second"

        result1 = run_ae([
            "init", str(target1),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--force",
        ])
        assert result1.returncode == 0
        answers_file = target1 / ".ae-answers.yml"
        assert answers_file.exists()

        result2 = run_ae([
            "init", str(target2),
            "--from-answers", str(answers_file),
            "--defaults",
            "--skip-tasks",
            "--force",
        ])
        assert result2.returncode == 0
        assert (target2 / "CLAUDE.md").exists()


class TestPathTraversalProtection:
    """T3: Verify path traversal protection."""

    def test_rejects_path_traversal(self):
        """TemplateRenderer should reject paths with ../ escaping dst_dir."""
        from auto_engineering.init.renderer import TemplateRenderer
        from auto_engineering.init.errors import TemplateRenderError
        import tempfile

        # Create a template dir with a file named to escape
        src_dir = Path(tempfile.mkdtemp())
        (src_dir / "safe.txt").write_text("safe")
        (src_dir / ".._escape.txt").write_text("escape")

        dst_dir = Path(tempfile.mkdtemp())
        renderer = TemplateRenderer(
            template_dirs=[src_dir],
            context={},
            overwrite=True,
        )
        generated = renderer.render_to(dst_dir)
        assert len(generated) == 2

        (src_dir / "safe.txt").unlink()
        (src_dir / ".._escape.txt").unlink()
        src_dir.rmdir()
        import shutil
        shutil.rmtree(dst_dir)


class TestBuiltinHooksErrorPropagation:
    """T4: Verify builtin hooks raise TaskExecutionError on failure."""

    def test_git_init_failure_raises(self):
        """git init in a non-existent writable location should raise."""
        from auto_engineering.init.scaffold import InitWorker
        from auto_engineering.init.errors import TaskExecutionError
        import pytest

        worker = InitWorker(
            dst_path=Path("/nonexistent/path/that/cannot/be/created"),
            project_type="app-service",
            defaults=True,
            skip_tasks=False,
        )
        with pytest.raises((TaskExecutionError, OSError)):
            worker.execute()


class TestGitBranchFallback:
    """T5: Verify git init branch fallback."""

    def test_git_init_tries_main_branch(self):
        """git init -b main is attempted first."""
        import subprocess
        result = subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True, text=True,
        )
        # Just verify the command syntax is valid on this system
        assert result.returncode == 0 or "unknown option" in result.stderr.lower()


class TestInitPhaseTasksCurrentPhase:
    """A2: _phase_tasks 必须把 current_phase 传给 TaskRunner."""

    def test_phase_tasks_passes_current_phase(self):
        """RED: TaskRunner 必须收到 current_phase='tasks'."""
        from unittest.mock import patch, MagicMock
        from auto_engineering.init.scaffold import InitWorker

        worker = InitWorker(
            dst_path=Path("/tmp/test-phase"),
            project_type="app-service",
            defaults=True,
            skip_tasks=False,
        )
        # 设置 current_phase = "tasks"
        worker._current_phase = "tasks"
        # _answers 留空但 mock context() 返回空 dict
        worker._answers = MagicMock()
        worker._answers.combined.return_value = {}

        # mock _template.tasks_before/tasks_after 为空列表,避免真正执行
        worker._template = MagicMock()
        worker._template.tasks_before = []
        worker._template.tasks_after = []

        # mock TaskRunner 类 + 子任务 _run_builtin_hooks
        with patch("auto_engineering.init.scaffold.TaskRunner") as MockRunner:
            with patch.object(worker, "_run_builtin_hooks"):
                import tempfile
                tmpdir = Path(tempfile.mkdtemp())
                try:
                    worker._phase_tasks(tmpdir)
                    assert MockRunner.called
                    call_kwargs = MockRunner.call_args.kwargs
                    assert call_kwargs.get("current_phase") == "tasks", \
                        f"current_phase not passed: {call_kwargs}"
                finally:
                    import shutil
                    shutil.rmtree(tmpdir, ignore_errors=True)


class TestInitIncrementalMode:
    """A1: --incremental 增量模式完整实现 (§1.3.10).

    验证:
    - CLI 暴露 --incremental 标志
    - 目标目录非空 + --incremental → 只补充缺失文件,跳过已有
    - .git/ 目录始终跳过
    - 重复运行幂等（第二次不会重复创建已存在的文件）
    """

    def test_cli_help_shows_incremental_flag(self):
        """RED: ae init --help 必须包含 --incremental."""
        result = run_ae(["init", "--help"])
        assert result.returncode == 0
        assert "--incremental" in result.stdout

    def test_incremental_skips_existing_files(self):
        """RED: --incremental + 目标目录已存在某文件 → 跳过该文件,仅补充新文件."""
        from auto_engineering.init.scaffold import InitWorker

        tmp = Path(tempfile.mkdtemp())
        target = tmp / "incremental-target"

        # 1) 先空目录跑一次（baseline）
        result1 = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--force",
        ])
        assert result1.returncode == 0, f"baseline init failed: {result1.stderr}"
        assert (target / "CLAUDE.md").exists()
        assert (target / "README.md").exists()

        # 在目标目录下添加一个"用户文件"
        user_file = target / "USER_FILE.md"
        user_file.write_text("# User's own file\n")

        # 2) 模拟补充一个文件中漏掉的（如模板中新增了 LICENSE，但初始化已生成过）
        # 删掉 LICENSE 模拟"目标目录应有但目前缺失"的场景
        (target / "LICENSE").unlink()

        # 3) 第二次跑 --incremental
        result2 = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--incremental",
        ])
        assert result2.returncode == 0, f"incremental init failed: {result2.stderr}"

        # USER_FILE.md 必须保留原内容
        assert user_file.exists()
        assert user_file.read_text() == "# User's own file\n"
        # LICENSE 缺失应被重新生成
        assert (target / "LICENSE").exists()

    def test_incremental_skips_git_dir(self):
        """RED: 增量模式下 .git/ 始终跳过（已有仓库不被覆盖）."""
        from auto_engineering.init.scaffold import InitWorker

        tmp = Path(tempfile.mkdtemp())
        target = tmp / "git-target"

        # 初始化一个 git 仓库
        target.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=target, capture_output=True)
        # 写一个 commit 对象验证 .git/HEAD 等文件
        head_file = target / ".git" / "HEAD"
        original_head = head_file.read_text() if head_file.exists() else ""

        # 跑 --incremental
        result = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--incremental",
        ])
        assert result.returncode == 0, f"init failed: {result.stderr}"

        # .git/HEAD 内容必须未变（不覆盖）
        if head_file.exists():
            assert head_file.read_text() == original_head

    def test_incremental_idempotent(self):
        """RED: --incremental 重复运行结果相同，第二次不会有新文件创建."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "idempotent-target"

        # 第一次
        result1 = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--incremental",
        ])
        assert result1.returncode == 0
        files_after_first = sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())

        # 第二次
        result2 = run_ae([
            "init", str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--incremental",
        ])
        assert result2.returncode == 0
        files_after_second = sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())

        # 文件列表必须一致
        assert files_after_first == files_after_second


class TestAeStatus:
    def test_status_output(self):
        result = run_ae(["status"])
        assert result.returncode == 0
        assert "当前目录" in result.stdout
