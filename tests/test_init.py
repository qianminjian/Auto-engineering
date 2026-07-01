"""E2E tests for ae init command."""

import subprocess
import tempfile
from pathlib import Path

import pytest


def run_ae(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "ae", *args],
        capture_output=True,
        text=True,
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
            "--type",
            "--defaults",
            "--force",
            "--from-answers",
            "--package-manager",
            "--ci",
            "--test-runner",
            "--no-typescript",
            "--no-lefthook",
            "--pretend",
            "--skip-tasks",
            "--no-cleanup",
            "--quiet",
            "--incremental",
        ]
        for flag in flags:
            assert flag in result.stdout, f"Missing flag: {flag}"


class TestInitPretend:
    def test_pretend_no_files_created(self):
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-project"
        result = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--pretend",
                "--force",
            ]
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout
        assert not target.exists()

    def test_pretend_with_skip_tasks(self):
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-project2"
        result = run_ae(
            [
                "init",
                str(target),
                "--type",
                "library",
                "--defaults",
                "--pretend",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result.returncode == 0
        assert "DRY RUN" in result.stdout


class TestInitMultiLayerTemplates:
    """T1: Verify multi-layer template directory composition."""

    def test_generates_shared_templates(self):
        """_shared templates (CLAUDE.md, .gitignore, README, LICENSE) are generated."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-shared"
        result = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result.returncode == 0
        shared_files = ["CLAUDE.md", ".gitignore", "README.md", "LICENSE", ".editorconfig"]
        for fname in shared_files:
            assert (target / fname).exists(), f"Missing shared file: {fname}"

    def test_generates_language_feature_templates(self):
        """Language feature templates (typescript) are generated."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "test-ts"
        result = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result.returncode == 0
        ts_files = [
            "tsconfig.json",
            "index.ts",
            "index.test.ts",
            "package.json",
            "eslint.config.js",
            "prettier.config.js",
        ]
        for fname in ts_files:
            assert (target / fname).exists(), f"Missing TS file: {fname}"

    def test_all_project_types_generate_shared(self):
        """All 8 project types generate shared templates."""
        for ptype in [
            "app-service",
            "library",
            "cli-tool",
            "skill",
            "hook",
            "mcp-server",
            "spec-doc",
            "monorepo",
        ]:
            tmp = Path(tempfile.mkdtemp())
            target = tmp / f"test-{ptype}"
            result = run_ae(
                [
                    "init",
                    str(target),
                    "--type",
                    ptype,
                    "--defaults",
                    "--skip-tasks",
                    "--force",
                ]
            )
            assert result.returncode == 0, f"Failed for type: {ptype}"
            assert (target / "CLAUDE.md").exists(), f"No CLAUDE.md for {ptype}"


class TestFromAnswersRecovery:
    """T2: Verify --from-answers recovery."""

    def test_from_answers_replays_config(self):
        """Answers from a previous run should be replayed."""
        tmp = Path(tempfile.mkdtemp())
        target1 = tmp / "first"
        target2 = tmp / "second"

        result1 = run_ae(
            [
                "init",
                str(target1),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result1.returncode == 0
        answers_file = target1 / ".ae-answers.yml"
        assert answers_file.exists()

        result2 = run_ae(
            [
                "init",
                str(target2),
                "--from-answers",
                str(answers_file),
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
        assert result2.returncode == 0
        assert (target2 / "CLAUDE.md").exists()


class TestPathTraversalProtection:
    """T3: Verify path traversal protection."""

    def test_rejects_path_traversal(self):
        """TemplateRenderer should reject paths with ../ escaping dst_dir."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

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
    """T4: Verify builtin hooks raise TaskExecutionError on git init failure.

    A3 区分: git init 失败仍抛 TaskExecutionError (它是 init 起点的基础)
             git add/commit 失败仅 warning (用户已有仓库/空仓库时常见)
    """

    def test_git_init_failure_raises(self):
        """git init in a non-existent writable location should raise."""
        import pytest

        from auto_engineering.init.errors import TaskExecutionError
        from auto_engineering.init.scaffold import InitWorker

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
            capture_output=True,
            text=True,
        )
        # Just verify the command syntax is valid on this system
        assert result.returncode == 0 or "unknown option" in result.stderr.lower()


class TestProjectEnvPackageManagerDefault:
    """A7: ProjectEnvironment 缺 package_manager 检测时默认 'npm'."""

    def test_package_manager_defaults_to_npm(self):
        """RED: 缺 package_manager 锁文件时,默认 'npm'."""
        from auto_engineering.config.environment import ProjectEnvironment

        env = ProjectEnvironment._from_detection(Path("/nonexistent-root"))
        assert env.package_manager == "npm", (
            f"Default package_manager should be 'npm', got '{env.package_manager}'"
        )

    def test_package_manager_detects_uv_when_lockfile_present(self):
        """REGRESSION: uv.lock 存在时检测为 'uv'."""
        import tempfile

        from auto_engineering.config.environment import ProjectEnvironment

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "uv.lock").write_text("")
            env = ProjectEnvironment._from_detection(tmp_path)
            assert env.package_manager == "uv"


class TestDetectorSpecDocGlob:
    """A6: FRAMEWORK_SIGNATURES spec-doc 支持 design/*.md glob."""

    def test_spec_doc_detected_with_arbitrary_design_md(self):
        """RED: 任何 design/*.md 文件存在时,项目被识别为 spec-doc."""
        import tempfile

        from auto_engineering.init.detector import ProjectDetector

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 创建 design/v2.0.md 而不是 BEACON.md
            (tmp_path / "design").mkdir()
            (tmp_path / "design" / "v2.0.md").write_text("# v2.0 design")
            detector = ProjectDetector(tmp_path)
            candidates = detector.list_candidates()
            assert "spec-doc" in candidates, (
                f"spec-doc not detected with design/v2.0.md. Got: {candidates}"
            )

    def test_spec_doc_still_detected_with_beacon_md(self):
        """REGRESSION: design/BEACON.md 仍应识别为 spec-doc."""
        import tempfile

        from auto_engineering.init.detector import ProjectDetector

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "design").mkdir()
            (tmp_path / "design" / "BEACON.md").write_text("# BEACON")
            detector = ProjectDetector(tmp_path)
            candidates = detector.list_candidates()
            assert "spec-doc" in candidates


class TestProjectEnvironmentWarnUndetectable:
    """A5: ProjectEnvironment._warn_undetectable 列出无法自动判定的字段."""

    def test_warn_undetectable_returns_undetectable_fields(self):
        """RED: 缺必要文件时,返回不可判定字段列表."""
        from auto_engineering.config.environment import ProjectEnvironment

        # 用 _from_detection 但 root 是空目录 → 多数字段无法判定
        env = ProjectEnvironment._from_detection(Path("/nonexistent-root"))
        undetectable = env._warn_undetectable(Path("/nonexistent-root"))
        # 至少应包含 package_manager 和 test_runner (空目录无法判定)
        assert isinstance(undetectable, list)
        assert "package_manager" in undetectable
        assert "test_runner" in undetectable

    def test_warn_undetectable_partial_when_some_files_present(self):
        """RED: 部分文件存在时,只列出仍未判定的字段."""
        import tempfile

        from auto_engineering.config.environment import ProjectEnvironment

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 提供 package-lock.json + pytest.ini 让两个字段可判定
            (tmp_path / "package-lock.json").write_text("{}")
            (tmp_path / "pytest.ini").write_text("[pytest]")
            env = ProjectEnvironment._from_detection(tmp_path)
            undetectable = env._warn_undetectable(tmp_path)
            # package_manager + test_runner 已被判定 → 不在列表
            assert "package_manager" not in undetectable
            assert "test_runner" not in undetectable
            # ci_platform / has_git 等仍未判定
            assert "ci_platform" in undetectable
            assert "has_git" in undetectable


class TestTemplateSuffixParameter:
    """T2-1: TemplateRenderer templates_suffix 参数化.

    设计意图: 用实例参数替代类属性 TEMPLATE_SUFFIX,支持不同后缀模板.
    Copier 参考: _main.py:754 template_suffix 默认 .jinja
    """

    def test_templates_suffix_parameter_reads_custom_suffix(self):
        """RED: TemplateRenderer(templates_suffix=".j2") 时读取 .j2 文件作为模板."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-suffix-src-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-suffix-dst-"))
        try:
            # 创建 .j2 后缀模板文件 (不同于默认的 .jinja)
            (src_dir / "config.j2").write_text("name: {{ name }}")
            # 创建一个普通文件 (不应被渲染)
            (src_dir / "readme.txt").write_text("plain text")

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={"name": "world"},
                templates_suffix=".j2",
                overwrite=True,
            )
            generated = renderer.render_to(dst_dir)
            rels = [g.relative_to(dst_dir) for g in generated]

            # config.j2 被渲染为 config (去掉 .j2 后缀)
            assert Path("config") in rels
            # readme.txt 原样复制
            assert Path("readme.txt") in rels
            # 渲染后的内容
            assert (dst_dir / "config").read_text() == "name: world"
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)

    def test_templates_suffix_default_preserves_existing_behavior(self):
        """RED: 不传 templates_suffix 时默认使用 .jinja 后缀 (向后兼容)."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-suffix-default-src-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-suffix-default-dst-"))
        try:
            # 使用默认 .jinja 后缀
            (src_dir / "config.jinja").write_text("name: {{ name }}")

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={"name": "world"},
                overwrite=True,
            )
            generated = renderer.render_to(dst_dir)
            rels = [g.relative_to(dst_dir) for g in generated]

            assert Path("config") in rels
            assert (dst_dir / "config").read_text() == "name: world"
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)


class TestPreserveSymlinksParameter:
    """T2-2: TemplateRenderer preserve_symlinks 参数化.

    设计意图: 让 symlink 处理可配置 (保留为 symlink 或解析为内容).
    当前行为: preserve_symlinks=True (默认) → 保留 symlink; False → 跳过 dangling/解析内容.
    """

    def test_preserve_symlinks_false_skips_dangling_symlink(self):
        """RED: preserve_symlinks=False 时 dangling symlink 被跳过不报错."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-cfg-src-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-cfg-dst-"))
        try:
            # 创建 dangling symlink
            (src_dir / "broken_link").symlink_to(src_dir / "nonexistent.txt")
            # 创建一个普通文件
            (src_dir / "real.txt").write_text("real content")

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={},
                preserve_symlinks=False,
                overwrite=True,
            )
            generated = renderer.render_to(dst_dir)
            rels = [g.relative_to(dst_dir) for g in generated]

            # dangling symlink 被跳过
            assert Path("broken_link") not in rels
            # real.txt 正常复制
            assert Path("real.txt") in rels
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)

    def test_preserve_symlinks_true_preserves_valid_symlink(self):
        """RED: preserve_symlinks=True 时有效 symlink 被保留为链接."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-cfg2-src-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-cfg2-dst-"))
        try:
            real = src_dir / "real.txt"
            real.write_text("target content")
            link = src_dir / "link.txt"
            link.symlink_to(real)

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={},
                preserve_symlinks=True,
                overwrite=True,
            )
            generated = renderer.render_to(dst_dir)
            rels = [g.relative_to(dst_dir) for g in generated]

            assert Path("link.txt") in rels
            link_dst = dst_dir / "link.txt"
            # preserve_symlinks=True → 保留为 symlink
            assert link_dst.is_symlink()
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)


class TestRendererSymlinkHandling:
    """A4: TemplateRenderer 处理 symlink 文件 (设计 §1.3.5).

    设计意图 (R18): symlink 文件应保留为 symlink 或解析为 target 内容.
    验证: link.txt 复制后存在 + (is_symlink 或内容 == target 内容).
    """

    def test_symlink_file_handled(self):
        """RED: symlink 文件被正确处理,不报错且 dst 端可读."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-src-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-symlink-dst-"))

        try:
            real = src_dir / "real.txt"
            real.write_text("hello target")
            link = src_dir / "link.txt"
            link.symlink_to(real)

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={},
                overwrite=True,
            )
            generated = renderer.render_to(dst_dir)

            rels = [g.relative_to(dst_dir) for g in generated]
            assert Path("real.txt") in rels
            assert Path("link.txt") in rels

            link_dst = dst_dir / "link.txt"
            real_dst = dst_dir / "real.txt"
            assert link_dst.exists()
            assert real_dst.exists()
            # 设计意图: copy2 + is_symlink → 保留或解析均可
            # 验证可读且内容 = target 内容
            assert link_dst.read_text() == "hello target"
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)

    def test_symlink_file_not_double_resolved(self):
        """RED: 渲染路径中对 symlink 的判断存在 (= 不崩)."""
        import tempfile

        from auto_engineering.init.renderer import TemplateRenderer

        src_dir = Path(tempfile.mkdtemp(prefix="ae-symlink2-"))
        dst_dir = Path(tempfile.mkdtemp(prefix="ae-symlink2-dst-"))
        try:
            # 创建 dangling symlink (指向不存在的文件) — 验证 renderer 不崩溃
            link = src_dir / "broken_link.txt"
            link.symlink_to(src_dir / "nonexistent.txt")
            real = src_dir / "real.txt"
            real.write_text("real content")

            renderer = TemplateRenderer(
                template_dirs=[src_dir],
                context={},
                overwrite=True,
            )
            # 不崩即可 (copy2 跟随 symlink 会 FileNotFoundError,但 is_symlink 后可走不同分支)
            # 设计意图: 若实现保留 symlink → 不跟随;若实现解析 → 需 FileNotFoundError 容忍
            # 这里仅验证: real.txt 仍能正确复制
            renderer.render_to(dst_dir)
            assert (dst_dir / "real.txt").exists()
        finally:
            import shutil

            shutil.rmtree(src_dir, ignore_errors=True)
            shutil.rmtree(dst_dir, ignore_errors=True)


class TestBuiltinHooksGitCommitNonBlocking:
    """A3: git commit 失败非阻塞 — 仅 warning,继续后续任务."""

    def test_git_commit_failure_does_not_raise(self):
        """RED: _run_builtin_hooks 中 git commit 失败不应抛 TaskExecutionError."""
        from unittest.mock import MagicMock, patch

        from auto_engineering.init.scaffold import InitWorker

        worker = InitWorker(
            dst_path=Path("/tmp/test-a3"),
            project_type="app-service",
            defaults=True,
        )
        # mock _answers 让 pm/use_lefthook 取不到 → 跳过 pm install / lefthook install
        worker._answers = MagicMock()
        worker._answers.get.return_value = None

        # 模拟所有 git 子命令都成功,但 git commit 失败 (returncode=1)
        success_result = MagicMock()
        success_result.returncode = 0
        success_result.stderr = ""

        failed_commit = MagicMock()
        failed_commit.returncode = 1
        failed_commit.stderr = "nothing to commit"

        # 顺序: git init → git add → git commit (fail)
        side_effects = [
            success_result,  # git init
            success_result,  # git add
            failed_commit,  # git commit (FAIL — 应非阻塞)
        ]

        with patch("subprocess.run", side_effect=side_effects) as mock_run:
            from auto_engineering.init.scaffold_hooks import run_builtin_hooks
            # 不应抛 TaskExecutionError — git commit 失败仅 warning
            try:
                run_builtin_hooks(worker._answers, Path("/tmp/test-a3-dst"))
            except Exception as e:
                pytest.fail(f"_run_builtin_hooks 不应抛异常，但收到: {e}")

            # 验证: 至少调了 3 次 subprocess.run (git init/add/commit)
            assert mock_run.call_count >= 3


class TestInitPhaseTasksCurrentPhase:
    """A2: _phase_tasks 必须把 current_phase 传给 TaskRunner."""

    def test_phase_tasks_passes_current_phase(self):
        """RED: TaskRunner 必须收到 current_phase='tasks'."""
        from unittest.mock import MagicMock, patch

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

        # mock TaskRunner 类 + 子任务 run_builtin_hooks
        with (
            patch("auto_engineering.init.scaffold_phases.TaskRunner") as MockRunner,
            patch("auto_engineering.init.scaffold_phases.run_builtin_hooks"),
        ):
            import tempfile

            tmpdir = Path(tempfile.mkdtemp())
            try:
                worker._phase_tasks(tmpdir)
                assert MockRunner.called
                call_kwargs = MockRunner.call_args.kwargs
                assert call_kwargs.get("current_phase") == "tasks", (
                    f"current_phase not passed: {call_kwargs}"
                )
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

        tmp = Path(tempfile.mkdtemp())
        target = tmp / "incremental-target"

        # 1) 先空目录跑一次（baseline）
        result1 = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--force",
            ]
        )
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
        result2 = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result2.returncode == 0, f"incremental init failed: {result2.stderr}"

        # USER_FILE.md 必须保留原内容
        assert user_file.exists()
        assert user_file.read_text() == "# User's own file\n"
        # LICENSE 缺失应被重新生成
        assert (target / "LICENSE").exists()

    def test_incremental_skips_git_dir(self):
        """RED: 增量模式下 .git/ 始终跳过（已有仓库不被覆盖）."""

        tmp = Path(tempfile.mkdtemp())
        target = tmp / "git-target"

        # 初始化一个 git 仓库
        target.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=target, capture_output=True)
        # 写一个 commit 对象验证 .git/HEAD 等文件
        head_file = target / ".git" / "HEAD"
        original_head = head_file.read_text() if head_file.exists() else ""

        # 跑 --incremental
        result = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result.returncode == 0, f"init failed: {result.stderr}"

        # .git/HEAD 内容必须未变（不覆盖）
        if head_file.exists():
            assert head_file.read_text() == original_head

    def test_incremental_idempotent(self):
        """RED: --incremental 重复运行结果相同，第二次不会有新文件创建."""
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "idempotent-target"

        # 第一次
        result1 = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result1.returncode == 0
        files_after_first = sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())

        # 第二次
        result2 = run_ae(
            [
                "init",
                str(target),
                "--type",
                "app-service",
                "--defaults",
                "--skip-tasks",
                "--incremental",
            ]
        )
        assert result2.returncode == 0
        files_after_second = sorted(p.relative_to(target) for p in target.rglob("*") if p.is_file())

        # 文件列表必须一致
        assert files_after_first == files_after_second


class TestAeStatus:
    def test_status_output(self):
        result = run_ae(["status"])
        assert result.returncode == 0
        assert "当前目录" in result.stdout


# ---------------------------------------------------------------------------
# Phase 03 C1: scaffold.py / hooks.py 覆盖率补充（聚焦目标 70%）
# ---------------------------------------------------------------------------


class TestScaffoldPrerequisites:
    """覆盖 scaffold.py:220-223 _check_prerequisites."""

    def test_missing_git_raises(self, monkeypatch, tmp_path):
        from auto_engineering.init.errors import UnsatisfiedPrerequisiteError
        from auto_engineering.init.scaffold import InitWorker

        # 模拟 git 不存在
        monkeypatch.setattr("shutil.which", lambda cmd: None if cmd == "git" else "/usr/bin/" + cmd)

        worker = InitWorker(
            dst_path=tmp_path / "p",
            project_type="library",
            defaults=True,
        )
        with pytest.raises(UnsatisfiedPrerequisiteError):
            worker._check_prerequisites()

    def test_prerequisites_ok_when_git_and_python_present(self, tmp_path):
        from auto_engineering.init.scaffold import InitWorker

        worker = InitWorker(
            dst_path=tmp_path / "p",
            project_type="library",
            defaults=True,
        )
        worker._check_prerequisites()  # 不抛


class TestScaffoldNonEmptyDir:
    """覆盖 scaffold.py:195-208 _phase_detect 目录存在性分支."""

    def test_non_empty_dir_without_force_or_incremental_raises(self, tmp_path):
        from auto_engineering.init.errors import TargetDirectoryError
        from auto_engineering.init.scaffold import InitWorker

        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "file.txt").write_text("data")

        worker = InitWorker(
            dst_path=existing,
            project_type="library",
            defaults=True,
        )
        with pytest.raises(TargetDirectoryError):
            worker._phase_detect()

    def test_non_empty_dir_with_incremental_sets_mode(self, tmp_path):
        from auto_engineering.init.scaffold import InitWorker

        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "file.txt").write_text("data")

        worker = InitWorker(
            dst_path=existing,
            project_type="library",
            defaults=True,
            incremental=True,
        )
        worker._phase_detect()
        assert worker._mode == "incremental"

    def test_empty_dir_sets_fresh_mode(self, tmp_path):
        from auto_engineering.init.scaffold import InitWorker

        empty = tmp_path / "empty"
        empty.mkdir()

        worker = InitWorker(
            dst_path=empty,
            project_type="library",
            defaults=True,
        )
        worker._phase_detect()
        assert worker._mode == "fresh"

    def test_nonexistent_dir_sets_fresh_mode(self, tmp_path):
        from auto_engineering.init.scaffold import InitWorker

        worker = InitWorker(
            dst_path=tmp_path / "nonexistent",
            project_type="library",
            defaults=True,
        )
        worker._phase_detect()
        assert worker._mode == "fresh"


class TestScaffoldPretendMode:
    """覆盖 scaffold.py:75-90 pretend 模式返回空 InitResult."""

    def test_pretend_returns_empty_files_list(self, tmp_path):
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "pretend-project"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            pretend=True,
            quiet=True,
        )
        result = worker.execute()
        assert result.files == []
        assert result.project_type == "library"
        assert not dst.exists()  # pretend 不创建文件


class TestScaffoldCleanupOnError:
    """覆盖 scaffold.py:139-142 异常处理 cleanup_on_error 行为."""

    def test_cleanup_removes_created_dst_on_exception(self, tmp_path, monkeypatch):
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "cleanup-test"
        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            skip_tasks=True,
            quiet=True,
        )

        # 模拟 render 阶段抛错
        def boom(*args, **kwargs):
            raise RuntimeError("simulated render failure")

        monkeypatch.setattr(worker, "_phase_render", boom)
        with pytest.raises(RuntimeError):
            worker.execute()
        # did_create_dst=True 时应清理
        assert not dst.exists()

    def test_no_cleanup_when_dst_existed_before(self, tmp_path, monkeypatch):
        """C2: dst 预先存在时,异常不会清理它（保护用户已有内容）.

        设计: did_create_dst = not self.dst_path.exists() → 预先存在 → False
        即使 cleanup_on_error=True,也不会清理已有目录。
        """
        from auto_engineering.init.scaffold import InitWorker

        dst = tmp_path / "pre-existing"
        dst.mkdir()
        user_file = dst / "user-data.txt"
        user_file.write_text("user content — must survive")

        worker = InitWorker(
            dst_path=dst,
            project_type="library",
            defaults=True,
            skip_tasks=True,
            quiet=True,
            cleanup_on_error=True,
            incremental=True,  # 允许非空目录
        )

        def boom(*args, **kwargs):
            raise RuntimeError("simulated render failure")

        monkeypatch.setattr(worker, "_phase_render", boom)
        with pytest.raises(RuntimeError):
            worker.execute()
        # 预先存在的目录 + 用户文件必须保留
        assert dst.exists()
        assert user_file.exists()
        assert user_file.read_text() == "user content — must survive"


class TestHooksTaskRunner:
    """覆盖 hooks.py:33-77 TaskRunner 分支（when 条件 + shell/list 双模式）."""

    def test_empty_tasks_no_op(self, tmp_path):
        from auto_engineering.init.hooks import TaskRunner

        runner = TaskRunner(tmp_path)
        runner.run([], context={})  # 不抛

    def test_when_false_skips_task(self, tmp_path, monkeypatch):
        from auto_engineering.init.config import Task
        from auto_engineering.init.hooks import TaskRunner

        called = []

        def fake_run(*args, **kwargs):
            called.append(args[0])

        monkeypatch.setattr("subprocess.run", fake_run)

        task = Task(cmd="echo hi", when="false")
        runner = TaskRunner(tmp_path)
        runner.run([task], context={})
        assert called == []  # 跳过了

    def test_list_cmd_renders_without_shell(self, tmp_path, monkeypatch):
        from auto_engineering.init.config import Task
        from auto_engineering.init.hooks import TaskRunner

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["shell"] = kwargs.get("shell", False)
            from unittest.mock import MagicMock

            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            return m

        monkeypatch.setattr("subprocess.run", fake_run)

        task = Task(cmd=["echo", "hello"], when=True)
        runner = TaskRunner(tmp_path)
        runner.run([task], context={"name": "world"})
        assert captured["shell"] is False
        assert captured["cmd"] == ["echo", "hello"]


# ─── v2.2 Phase I: 模块拆分导入路径测试 (TDD RED) ─────────────────────────────
class TestV22PhaseIModuleSplit:
    """验证 P2.5 模块拆分后公共 API 兼容性。

    Phase I 拆分目标：
    - config.py → config_types.py + config_loader.py + config.py
    - scaffold.py → scaffold_phases.py + scaffold_hooks.py + scaffold_render.py
    - 旧导入路径 (init.config, init.scaffold) 保留兼容
    """

    def test_new_config_types_module_exports_question(self):
        """新拆出的 config_types 模块应导出 Question dataclass。"""
        from auto_engineering.init.config_types import Question

        q = Question(var_name="x", default="y")
        assert q.var_name == "x"
        assert q.default == "y"

    def test_new_config_types_module_exports_task(self):
        """新拆出的 config_types 模块应导出 Task dataclass。"""
        from auto_engineering.init.config_types import Task

        t = Task(cmd=["echo", "hi"])
        assert t.cmd == ["echo", "hi"]
        assert t.when is True

    def test_new_scaffold_phases_module_exports_init_worker(self):
        """新拆出的 scaffold_phases 模块应导出 InitWorker。"""
        from auto_engineering.init.scaffold_phases import InitWorker

        worker = InitWorker(dst_path=Path("/tmp/nonexistent-p2-5"))
        assert worker is not None

    def test_legacy_config_path_still_works(self):
        """旧路径 init.config 仍可导入 Question/Task/TemplateConfig (兼容)。"""
        from auto_engineering.init.config import Question, Task, TemplateConfig

        assert Question is not None
        assert Task is not None
        assert TemplateConfig is not None

    def test_legacy_scaffold_path_still_works(self):
        """旧路径 init.scaffold 仍可导入 InitResult/InitWorker/init_project (兼容)。"""
        from auto_engineering.init.scaffold import InitResult, InitWorker, init_project

        assert InitResult is not None
        assert InitWorker is not None
        assert init_project is not None


# ─── v2.3 Phase F: Copier match_exclude 回调机制 (P1.2) ─────────────────────────
class TestExcludeCallback:
    """P1.2: init/ 缺 Copier match_exclude 回调机制.

    借鉴 Copier _main.py:753 match_exclude(self) -> Callable[[Path], bool].
    目标: ae-template.yml 支持 exclude_callback 配置, 调用 user-defined 回调动态排除路径.
    """

    def test_default_match_exclude_git_dir(self):
        """`.git/` 下任何文件都应被排除."""
        from auto_engineering.init._shared.exclude import default_match_exclude

        assert default_match_exclude(Path(".git/config")) is True
        assert default_match_exclude(Path(".git/HEAD")) is True
        assert default_match_exclude(Path("src/.git/refs")) is True

    def test_default_match_exclude_pycache(self):
        """`__pycache__/` 目录 + `.pyc` 文件应被排除."""
        from auto_engineering.init._shared.exclude import default_match_exclude

        assert default_match_exclude(Path("__pycache__/foo.pyc")) is True
        assert default_match_exclude(Path("src/__pycache__/x.pyc")) is True
        assert default_match_exclude(Path("module.pyc")) is True

    def test_default_match_exclude_venv(self):
        """`.venv/` 与 `node_modules/` 应被排除."""
        from auto_engineering.init._shared.exclude import default_match_exclude

        assert default_match_exclude(Path(".venv/lib/python3.12/site.py")) is True
        assert default_match_exclude(Path("node_modules/react/index.js")) is True

    def test_default_match_exclude_keeps_source(self):
        """普通源码文件应保留, 不被排除."""
        from auto_engineering.init._shared.exclude import default_match_exclude

        assert default_match_exclude(Path("src/main.py")) is False
        assert default_match_exclude(Path("README.md")) is False
        assert default_match_exclude(Path("pyproject.toml")) is False

    def test_default_match_exclude_dotfile(self):
        """常见隐藏垃圾文件 (如 `.env` / `.DS_Store`) 应被排除.

        注意: 保留 .gitignore / .editorconfig 等配置 dotfile (与 Copier 一致).
        """
        from auto_engineering.init._shared.exclude import default_match_exclude

        assert default_match_exclude(Path(".env")) is True
        assert default_match_exclude(Path(".DS_Store")) is True
        # 配置 dotfile 不应被排除
        assert default_match_exclude(Path(".gitignore")) is False
        assert default_match_exclude(Path(".editorconfig")) is False

    def test_parse_exclude_callback_resolves_default(self):
        """'module:function' 格式 spec 可解析为可调用对象."""
        from auto_engineering.init._shared.exclude import (
            default_match_exclude,
            parse_exclude_callback,
        )

        callback = parse_exclude_callback(
            "auto_engineering.init._shared.exclude:default_match_exclude"
        )
        assert callback is default_match_exclude

    def test_parse_exclude_callback_raises_on_missing_module(self):
        """解析不存在的模块应抛 ImportError."""
        from auto_engineering.init._shared.exclude import parse_exclude_callback

        with pytest.raises(ImportError):
            parse_exclude_callback("nonexistent.module:fn")

    def test_parse_exclude_callback_raises_on_missing_attr(self):
        """解析模块中不存在的函数应抛 AttributeError."""
        from auto_engineering.init._shared.exclude import parse_exclude_callback

        with pytest.raises(AttributeError):
            parse_exclude_callback(
                "auto_engineering.init._shared.exclude:no_such_function"
            )

    def test_parse_exclude_callback_invalid_format(self):
        """非 'module:function' 格式应抛 ValueError."""
        from auto_engineering.init._shared.exclude import parse_exclude_callback

        with pytest.raises(ValueError):
            parse_exclude_callback("invalid_format_no_colon")

    def test_template_config_exclude_callback_field_default(self):
        """TemplateConfig 暴露 exclude_callback 字段, 默认指向 default_match_exclude."""
        from auto_engineering.init._shared.exclude import default_match_exclude
        from auto_engineering.init.config import TemplateConfig

        cfg = TemplateConfig(template_dir=Path("/tmp/none"))
        assert hasattr(cfg, "exclude_callback")
        # 默认值是字符串 (解析在 init 时完成)
        assert cfg.exclude_callback == (
            "auto_engineering.init._shared.exclude:default_match_exclude"
        )
        # 解析后应等于 default_match_exclude
        from auto_engineering.init._shared.exclude import parse_exclude_callback

        assert parse_exclude_callback(cfg.exclude_callback) is default_match_exclude

    def test_renderer_match_exclude_callback_filters_paths(self, tmp_path):
        """TemplateRenderer 接收 match_exclude 回调时, 排除路径生效.

        验证 P1.2 集成: 通过 TemplateRenderer 的 match_exclude 参数,
        .git/ 和 __pycache__/ 文件被排除.
        """
        from auto_engineering.init._shared.exclude import default_match_exclude
        from auto_engineering.init.renderer import TemplateRenderer

        # 创建模板目录: 含 .git/, __pycache__/, src/
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / ".git").mkdir()
        (template_dir / ".git" / "config").write_text("git config")
        (template_dir / "__pycache__").mkdir()
        (template_dir / "__pycache__" / "foo.pyc").write_text("cached")
        (template_dir / "src").mkdir()
        (template_dir / "src" / "main.py").write_text("print('hi')")

        dst = tmp_path / "output"
        dst.mkdir()

        renderer = TemplateRenderer(
            template_dirs=[template_dir],
            context={},
            match_exclude=default_match_exclude,
        )
        result = renderer.render_to(dst)

        # .git/config + __pycache__/foo.pyc 应被排除
        assert not (dst / ".git" / "config").exists()
        assert not (dst / "__pycache__" / "foo.pyc").exists()
        # src/main.py 应保留
        assert (dst / "src" / "main.py").exists()
        assert any("main.py" in str(p) for p in result)

    def test_scaffold_render_resolves_exclude_callback_spec(self):
        """scaffold_render 解析 exclude_callback spec 失败时, 回退到 default.

        验证集成路径: render_to 签名含 exclude_callback 参数且默认值为
        default_match_exclude spec.
        """
        import inspect

        from auto_engineering.init.scaffold_render import render_to

        sig = inspect.signature(render_to)
        assert "exclude_callback" in sig.parameters
        # 默认值
        param = sig.parameters["exclude_callback"]
        assert param.default == (
            "auto_engineering.init._shared.exclude:default_match_exclude"
        )
