"""TaskRunner — pre/post 钩子执行.

来源：
- copier/_main.py:383-427 — _execute_tasks() Jinja2 渲染 + shell/list 双模式
- cookiecutter/hooks.py:80-128 — run_script_with_context()
"""

import subprocess
import os as subprocess_os
from pathlib import Path

import jinja2

from .config import Task
from .errors import TaskExecutionError


class TaskRunner:
    """执行钩子任务列表。来源：Copier _execute_tasks 模式。"""

    def __init__(self, project_dir: Path, current_phase: str = ""):
        self.project_dir = project_dir
        self._current_phase = current_phase

    def run(
        self,
        tasks: list[Task],
        context: dict,
        jinja_env: jinja2.Environment | None = None,
    ) -> None:
        if not tasks:
            return
        if jinja_env is None:
            jinja_env = jinja2.Environment()

        for task in tasks:
            # 1. 检查 when 条件
            if isinstance(task.when, str):
                tpl = jinja_env.from_string(task.when)
                should_run = tpl.render(**context).strip().lower() not in ("false", "no", "0", "")
            else:
                should_run = bool(task.when)
            if not should_run:
                continue

            # 2. 渲染 working_directory
            wd = self.project_dir
            if task.working_directory:
                tpl = jinja_env.from_string(task.working_directory)
                wd = wd / tpl.render(**context)
            wd = wd.resolve()
            wd.mkdir(parents=True, exist_ok=True)

            # 3. extra_vars 双注入（Jinja 渲染层 + 环境变量层）
            extra_context = {f"_{k}": v for k, v in task.extra_vars.items()}
            extra_context["_ae_phase"] = self._current_phase
            extra_env = {k.upper(): str(v) for k, v in task.extra_vars.items()}
            extra_env["AE_PHASE"] = self._current_phase
            render_context = {**context, **extra_context}

            # 4. 渲染命令
            if isinstance(task.cmd, list):
                cmd = [jinja_env.from_string(s).render(**render_context) for s in task.cmd]
                use_shell = False
            else:
                cmd = jinja_env.from_string(task.cmd).render(**render_context)
                use_shell = True

            # 5. 执行
            env = {**subprocess_os.environ, **extra_env}
            result = subprocess.run(
                cmd, shell=use_shell, cwd=str(wd),
                capture_output=True, text=True, timeout=300,
                env=env,
            )
            if result.returncode != 0:
                raise TaskExecutionError(
                    command=str(cmd),
                    returncode=result.returncode,
                    stderr=result.stderr,
                )
