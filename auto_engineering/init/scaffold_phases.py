"""InitWorker — 5 阶段流水线编排器（参考 Copier Worker）。

从 scaffold.py 拆分（v2.2 Phase I, P2.5）。

本模块只含 InitResult dataclass + InitWorker 类（5 阶段方法 + 增量合并 + 顶层函数）。
内置钩子执行逻辑在 scaffold_hooks.py。
"""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import jinja2

from .answers import AnswersMap
from .config import TEMPLATES_ROOT, TemplateConfig
from .detector import ProjectDetector
from .errors import (
    ConfigFileError,
    InitInterruptedError,
    TargetDirectoryError,
    UnsatisfiedPrerequisiteError,
)
from .hooks import TaskRunner
from .prompts import (
    InteractivePrompt,
    prompt_for_nested_template,
    prompt_for_project_type,
)
from .scaffold_hooks import merge_incremental, run_builtin_hooks
from .scaffold_render import render_to as _render_to


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
            with contextlib.suppress(Exception):
                hook()

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
        generated: list[Path] = []

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

            did_create_dst = self._phase_finalize(tmpdir, generated)

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

    def _phase_finalize(self, tmpdir: Path, generated: list[Path]) -> bool:
        """写入 .ae-answers.yml + 增量/全量 copytree。

        拆分自 execute()，保持 InitWorker.execute() < 50 行。

        Returns:
            did_create_dst: 是否本次创建了目标目录（用于错误时清理）
        """
        self._answers.write_to(tmpdir / ".ae-answers.yml")

        # v2.5 P2-C-3: 验证 project_type 防止路径穿越. 攻击者控制的
        # project_type 注入 `../../etc` 会让 replay_dir 写到 ~/.ae-replays/../../etc
        # (mkdir(parents=True) 会创建任意路径).
        raw_type = self.project_type or "unknown"
        if not re.match(r"^[A-Za-z0-9_-]+$", raw_type):
            raise ValueError(
                f"project_type '{raw_type}' 含非法字符. "
                f"只允许字母/数字/下划线/连字符 (防路径穿越)."
            )
        replay_dir = Path.home() / ".ae-replays" / raw_type
        replay_dir.mkdir(parents=True, exist_ok=True)
        replay_file = replay_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.yml"
        self._answers.write_to(replay_file)

        self._current_phase = "finalize"
        if self._mode == "incremental":
            # A1: v2.0.5 — 增量合并
            created, skipped = merge_incremental(tmpdir, self.dst_path, self._created_files)
            if not self.quiet:
                print(
                    f"\n✓ 增量模式：已补充 {len(created)} 个文件，"
                    f"跳过 {len(skipped)} 个已有文件"
                )
            return False
        else:
            did_create_dst = not self.dst_path.exists()
            if did_create_dst:
                self.dst_path.mkdir(parents=True)
            shutil.copytree(tmpdir, self.dst_path, dirs_exist_ok=True)
            if not self.quiet:
                print(f"\n✓ 项目已生成: {self.dst_path}")
                print(f"  文件数: {len(generated)}")
                print(f"  下一步: cd {self.dst_path.name} && git log")
            return did_create_dst

    def _check_template_version(self) -> None:
        """检查 ae 版本是否满足模板要求的最小版本。"""
        from packaging.version import parse

        from auto_engineering import __version__

        installed = parse(__version__)
        if self._template.min_ae_version:
            required = parse(self._template.min_ae_version)
            if installed < required:
                raise ConfigFileError(
                    f"模板要求 ae >= {self._template.min_ae_version}，当前版本 {__version__}"
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
                available = [
                    d.name
                    for d in TEMPLATES_ROOT.iterdir()
                    if d.is_dir() and not d.name.startswith("_")
                ]
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
                self._template.nested_templates,
                no_input=False,
            )
            if chosen:
                self._template.template_dir = self._template.template_dir / chosen
        cli_overrides = {}
        for key in [
            "package_manager",
            "ci_platform",
            "test_runner",
            "use_typescript",
            "use_lefthook",
        ]:
            val = getattr(self, key, None)
            if val is not None:
                cli_overrides[key] = val
        self._answers = AnswersMap(
            defaults={q.var_name: q.default for q in self._template.questions},
            cli_overrides=cli_overrides,
            previous=self._previous_answers.previous if self._previous_answers else {},
            external=self._template.external_data,
            # v2.5 P1-S3: external_data 路径沙箱到 template_dir (realpath 双侧
            # 校验, 防 /etc/passwd 读取). 攻击者控制的模板无法越界.
            external_sandbox_roots=[self._template.template_dir],
        )
        self._answers.builtins["project_type"] = self.project_type or ""
        if not self.defaults:
            prompt = InteractivePrompt(self._template.questions, self._answers)
            try:
                self._answers = prompt.run()
            except KeyboardInterrupt:
                self._answers.save_partial()
                raise InitInterruptedError() from None

    def _phase_render(self, tmpdir: Path) -> list[Path]:
        return _render_to(
            answers=self._answers,
            folder_name=self.dst_path.name,
            template_dir=self._template.template_dir,
            subdirectory=self._template.subdirectory,
            exclude=self._template.exclude,
            skip_if_exists=self._template.skip_if_exists,
            no_render=self._template.no_render,
            envops=self._template.envops,
            overwrite=self.overwrite,
            tmpdir=tmpdir,
            exclude_callback=self._template.exclude_callback,
        )

    def _phase_tasks(self, tmpdir: Path) -> None:
        jinja_env = jinja2.Environment()
        context = self._answers.combined()
        # A2: 把 current_phase 传给 TaskRunner (TaskRunner 内部用于 AE_PHASE)
        runner = TaskRunner(tmpdir, current_phase=self._current_phase)
        runner.run(self._template.tasks_before, context, jinja_env)
        run_builtin_hooks(self._answers, tmpdir)
        runner.run(self._template.tasks_after, context, jinja_env)
