"""InitWorker — 5 阶段流水线编排器（参考 Copier Worker）."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from .config import TemplateConfig, TEMPLATES_ROOT
from .answers import AnswersMap
from .prompts import (
    InteractivePrompt, prompt_for_project_type, prompt_for_nested_template,
)
from .renderer import TemplateRenderer
from .hooks import TaskRunner
from .detector import ProjectDetector
from .errors import (
    InitError, TargetDirectoryError, ConfigFileError,
    UnsatisfiedPrerequisiteError, InitInterruptedError,
    TaskExecutionError,
)
from ..config.environment import ProjectEnvironment


@dataclass
class InitResult:
    dst_path: Path
    files: list[Path] = field(default_factory=list)
    answers: dict = field(default_factory=dict)
    project_type: str = ""


@dataclass
class InitWorker:
    dst_path: Path
    project_type: str | None = None
    package_manager: str | None = None
    ci_platform: str | None = None
    test_runner: str | None = None
    use_typescript: bool | None = None
    use_lefthook: bool | None = None
    force: bool = False
    defaults: bool = False
    overwrite: bool = False
    quiet: bool = False
    pretend: bool = False
    skip_tasks: bool = False
    cleanup_on_error: bool = True
    incremental: bool = False

    _current_phase: str = field(init=False, default="")
    _template: TemplateConfig = field(init=False, default=None)
    _answers: AnswersMap = field(init=False, default_factory=AnswersMap)
    _cleanup_hooks: list = field(default_factory=list, init=False)
    _previous_answers: AnswersMap | None = field(init=False, default=None)
    _created_files: set[str] = field(default_factory=set, init=False)
    _mode: str = field(init=False, default="fresh")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()
        return False

    def _cleanup(self) -> None:
        for hook in self._cleanup_hooks:
            try:
                hook()
            except Exception:
                pass

    def execute(self) -> InitResult:
        if self.pretend and not self.quiet:
            print("[DRY RUN] 模拟执行，不产生文件")

        self._current_phase = "detect"
        self._phase_detect()

        self._current_phase = "prompt"
        self._phase_prompt()
        self._check_template_version()

        if self.pretend:
            return InitResult(
                dst_path=self.dst_path,
                project_type=self.project_type or "",
            )

        tmpdir = Path(tempfile.mkdtemp(prefix="ae-init-"))
        self._cleanup_hooks.append(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        did_create_dst = False

        try:
            self._current_phase = "render"
            if self._template.message_before and not self.quiet:
                print(self._template.message_before)
            generated = self._phase_render(tmpdir)

            self._current_phase = "tasks"
            if not self.skip_tasks:
                self._phase_tasks(tmpdir)
                if self._template.message_after and not self.quiet:
                    print(self._template.message_after)

            self._answers.write_to(tmpdir / ".ae-answers.yml")

            replay_dir = Path.home() / ".ae-replays" / (self.project_type or "unknown")
            replay_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            replay_file = replay_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.yml"
            self._answers.write_to(replay_file)

            self._current_phase = "finalize"
            if self._mode == "incremental":
                # A1: Phase 3.5 — 增量合并
                created, skipped = self._phase_merge(tmpdir, generated)
                if not self.quiet:
                    print(f"\n✓ 增量模式：已补充 {len(created)} 个文件，跳过 {len(skipped)} 个已有文件")
            else:
                did_create_dst = not self.dst_path.exists()
                if did_create_dst:
                    self.dst_path.mkdir(parents=True)
                shutil.copytree(tmpdir, self.dst_path, dirs_exist_ok=True)
                if not self.quiet:
                    print(f"\n✓ 项目已生成: {self.dst_path}")
                    print(f"  文件数: {len(generated)}")
                    print(f"  下一步: cd {self.dst_path.name} && git log")

        except InitInterruptedError:
            partial_path = self._answers.save_partial()
            if not self.quiet:
                print(f"\n已中断。部分答案已保存到: {partial_path}")
                print(f"恢复: ae init --from-answers {partial_path}")
            raise

        except Exception:
            if self.cleanup_on_error and did_create_dst and self.dst_path.exists():
                shutil.rmtree(self.dst_path)
            raise

        return InitResult(
            dst_path=self.dst_path,
            files=generated,
            answers=self._answers.to_answers_file(),
            project_type=self.project_type or "",
        )

    def _phase_merge(
        self, tmpdir: Path, generated: list[Path],
    ) -> tuple[list[Path], list[Path]]:
        """A1: 增量模式合并 — 逐文件复制,跳过已存在 + .git/.

        Returns:
            (created_files, skipped_files)
        """
        created: list[Path] = []
        skipped: list[Path] = []
        for src_file in tmpdir.rglob("*"):
            if src_file.is_dir():
                continue
            rel = src_file.relative_to(tmpdir)
            # A1: 跳过 .git/ 目录
            if any(part == ".git" for part in rel.parts):
                continue
            dst_file = self.dst_path / rel
            if dst_file.exists():
                skipped.append(dst_file)
                continue
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            shutil.copymode(src_file, dst_file)
            self._created_files.add(str(rel))
            created.append(dst_file)
        return created, skipped

    def _check_template_version(self) -> None:
        """检查 ae 版本是否满足模板要求的最小版本。"""
        from auto_engineering import __version__
        from packaging.version import Version, parse

        installed = parse(__version__)
        if self._template.min_ae_version:
            required = parse(self._template.min_ae_version)
            if installed < required:
                raise ConfigFileError(
                    f"模板要求 ae >= {self._template.min_ae_version}，"
                    f"当前版本 {__version__}"
                )

    def _phase_detect(self) -> None:
        # A1: 增量模式检测
        if self.dst_path.exists() and not self.force:
            if any(self.dst_path.iterdir()):
                if self.incremental:
                    self._mode = "incremental"
                else:
                    raise TargetDirectoryError(
                        f"目录 {self.dst_path} 非空。使用 --force 强制覆盖，"
                        f"--incremental 增量补充缺失文件，"
                        f"或在空目录/新目录中运行 ae init"
                    )
            else:
                self._mode = "fresh"
        else:
            self._mode = "fresh"
        if not self.project_type:
            detector = ProjectDetector(self.dst_path)
            self.project_type = detector.detect()
            if not self.project_type:
                if self.defaults:
                    raise ConfigFileError("无法自动检测项目类型，请用 --type 指定")
                available = [d.name for d in TEMPLATES_ROOT.iterdir()
                           if d.is_dir() and not d.name.startswith("_")]
                self.project_type = prompt_for_project_type(available)
        self._check_prerequisites()

    def _check_prerequisites(self) -> None:
        for cmd, name in [("git", "Git"), ("python3", "Python 3")]:
            if shutil.which(cmd) is None:
                raise UnsatisfiedPrerequisiteError(f"未找到 {name}。请先安装。")

    def _phase_prompt(self) -> None:
        self._template = TemplateConfig.load(self.project_type or "")
        if self._template.nested_templates and not self.defaults:
            chosen = prompt_for_nested_template(
                self._template.nested_templates, no_input=False,
            )
            if chosen:
                self._template.template_dir = self._template.template_dir / chosen
        cli_overrides = {}
        for key in ["package_manager", "ci_platform", "test_runner",
                     "use_typescript", "use_lefthook"]:
            val = getattr(self, key, None)
            if val is not None:
                cli_overrides[key] = val
        self._answers = AnswersMap(
            defaults={q.var_name: q.default for q in self._template.questions},
            cli_overrides=cli_overrides,
            previous=self._previous_answers.previous if self._previous_answers else {},
            external=self._template.external_data,
        )
        self._answers.builtins["project_type"] = self.project_type or ""
        if not self.defaults:
            prompt = InteractivePrompt(self._template.questions, self._answers)
            try:
                self._answers = prompt.run()
            except KeyboardInterrupt:
                self._answers.save_partial()
                raise InitInterruptedError()

    def _phase_render(self, tmpdir: Path) -> list[Path]:
        self._answers.builtins["_folder_name"] = self.dst_path.name
        str_vars = ["project_name", "project_description", "language",
                     "package_manager", "test_runner", "ci_platform", "project_type"]
        for var in str_vars:
            if var not in self._answers:
                self._answers.builtins[var] = ""
        if "use_typescript" not in self._answers:
            self._answers.builtins["use_typescript"] = ""
        if "use_lefthook" not in self._answers:
            self._answers.builtins["use_lefthook"] = ""
        context = self._answers.combined()
        template_dirs = [TEMPLATES_ROOT / "_shared"]

        language = context.get("language", "typescript")
        lang_feature_map = {
            "typescript": "typescript", "python": "python",
            "go": "go", "rust": "rust", "bash": "bash",
        }
        if lang_feat := lang_feature_map.get(language):
            feat_dir = TEMPLATES_ROOT / "_features" / lang_feat
            if feat_dir.exists():
                template_dirs.append(feat_dir)

        feature_map = {"use_lefthook": "lefthook"}
        ci_feature_map = {"github": "github-actions", "gitlab": "gitlab-ci"}
        if ci_platform := context.get("ci_platform"):
            feature_map[ci_platform] = ci_feature_map.get(ci_platform, "")
        if context.get("use_docker"):
            feature_map["use_docker"] = "docker"
        if context.get("project_type") == "monorepo":
            feature_map["monorepo"] = "monorepo"

        for answer_key, feature_name in feature_map.items():
            if not feature_name:
                continue
            if answer_key == "monorepo" or context.get(answer_key):
                feat_dir = TEMPLATES_ROOT / "_features" / feature_name
                if feat_dir.exists():
                    template_dirs.append(feat_dir)

        subdir = self._template.subdirectory
        type_dir = self._template.template_dir
        if subdir:
            type_dir = type_dir / subdir
        template_dirs.append(type_dir)

        renderer = TemplateRenderer(
            template_dirs=template_dirs,
            context=context,
            exclude=self._template.exclude,
            skip_if_exists=self._template.skip_if_exists,
            no_render=self._template.no_render,
            envops=self._template.envops,
            overwrite=self.overwrite,
        )
        return renderer.render_to(tmpdir)

    def _phase_tasks(self, tmpdir: Path) -> None:
        jinja_env = jinja2.Environment()
        context = self._answers.combined()
        # A2: 把 current_phase 传给 TaskRunner (TaskRunner 内部用于 AE_PHASE)
        runner = TaskRunner(tmpdir, current_phase=self._current_phase)
        runner.run(self._template.tasks_before, context, jinja_env)
        self._run_builtin_hooks(tmpdir)
        runner.run(self._template.tasks_after, context, jinja_env)

    def _run_builtin_hooks(self, tmpdir: Path) -> None:
        # git init with branch fallback (git < 2.28 compatibility)
        result = subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmpdir,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            if "unknown option" in result.stderr.lower() or "unknown switch" in result.stderr.lower():
                result = subprocess.run(
                    ["git", "init"], cwd=tmpdir,
                    capture_output=True, text=True,
                )
            if result.returncode != 0:
                raise TaskExecutionError("git init", result.returncode, result.stderr)

        pm = self._answers.get("package_manager")
        if pm:
            result = subprocess.run([pm, "install"], cwd=tmpdir,
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise TaskExecutionError(
                    f"{pm} install", result.returncode, result.stderr,
                )

        if self._answers.get("use_lefthook"):
            result = subprocess.run(["lefthook", "install"], cwd=tmpdir,
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise TaskExecutionError(
                    "lefthook install", result.returncode, result.stderr,
                )

        result = subprocess.run(
            ["git", "add", "-A"], cwd=tmpdir,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise TaskExecutionError("git add", result.returncode, result.stderr)

        result = subprocess.run(
            ["git", "commit", "-m", "chore(init): scaffolded by ae init"],
            cwd=tmpdir, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise TaskExecutionError(
                "git commit", result.returncode, result.stderr,
            )


def init_project(dst_path: str | Path, project_type: str | None = None, **kwargs) -> InitResult:
    with InitWorker(dst_path=Path(dst_path), project_type=project_type, **kwargs) as w:
        return w.execute()
