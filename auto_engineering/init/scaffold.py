"""InitWorker — 5 阶段流水线编排器（参考 Copier Worker）."""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from .config import TemplateConfig, TEMPLATES_ROOT
from .answers import AnswersMap
from .prompts import InteractivePrompt, prompt_for_project_type
from .renderer import TemplateRenderer
from .hooks import TaskRunner
from .detector import ProjectDetector
from .errors import (
    InitError, TargetDirectoryError, ConfigFileError,
    UnsatisfiedPrerequisiteError, InitInterruptedError,
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

    _current_phase: str = field(init=False, default="")
    _template: TemplateConfig = field(init=False, default=None)
    _answers: AnswersMap = field(init=False, default_factory=AnswersMap)
    _cleanup_hooks: list = field(default_factory=list, init=False)
    _previous_answers: AnswersMap | None = field(init=False, default=None)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
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
            generated = self._phase_render(tmpdir)

            self._current_phase = "tasks"
            if not self.skip_tasks:
                self._phase_tasks(tmpdir)

            self._answers.write_to(tmpdir / ".ae-answers.yml")

            self._current_phase = "finalize"
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
        if self.dst_path.exists() and not self.force:
            if any(self.dst_path.iterdir()):
                raise TargetDirectoryError(
                    f"目录 {self.dst_path} 非空。使用 --force 强制覆盖，"
                    f"或在空目录/新目录中运行 ae init"
                )
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
            if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
                raise UnsatisfiedPrerequisiteError(f"未找到 {name}。请先安装。")

    def _phase_prompt(self) -> None:
        self._template = TemplateConfig.load(self.project_type or "")
        cli_overrides = {}
        for key in ["package_manager", "ci_platform", "test_runner",
                     "use_typescript", "use_lefthook"]:
            val = getattr(self, key, None)
            if val is not None:
                cli_overrides[key] = val
        self._answers = AnswersMap(
            defaults={q.var_name: q.default for q in self._template.questions},
            cli_overrides=cli_overrides,
        )
        if not self.defaults:
            prompt = InteractivePrompt(self._template.questions, self._answers)
            try:
                self._answers = prompt.run()
            except KeyboardInterrupt:
                self._answers.save_partial()
                raise InitInterruptedError()

    def _phase_render(self, tmpdir: Path) -> list[Path]:
        renderer = TemplateRenderer(
            template_dirs=[self._template.template_dir],
            context=self._answers.combined(),
            exclude=self._template.exclude,
            skip_if_exists=self._template.skip_if_exists,
            overwrite=self.overwrite,
        )
        return renderer.render_to(tmpdir)

    def _phase_tasks(self, tmpdir: Path) -> None:
        jinja_env = jinja2.Environment()
        context = self._answers.combined()
        runner = TaskRunner(tmpdir)
        runner.run(self._template.tasks_before, context, jinja_env)
        self._run_builtin_hooks(tmpdir)
        runner.run(self._template.tasks_after, context, jinja_env)

    def _run_builtin_hooks(self, tmpdir: Path) -> None:
        subprocess.run(["git", "init", "-b", "main"], cwd=tmpdir,
                       capture_output=True, check=False)
        pm = self._answers.get("package_manager")
        if pm:
            subprocess.run([pm, "install"], cwd=tmpdir,
                           capture_output=True, check=False)
        if self._answers.get("use_lefthook"):
            subprocess.run(["lefthook", "install"], cwd=tmpdir,
                           capture_output=True, check=False)
        subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore(init): scaffolded by ae init"],
            cwd=tmpdir, capture_output=True, check=False,
        )


def init_project(dst_path: str | Path, project_type: str | None = None, **kwargs) -> InitResult:
    with InitWorker(dst_path=Path(dst_path), project_type=project_type, **kwargs) as w:
        return w.execute()
