"""InitError 体系 — 所有 init 子系统异常的基类。

参考来源：copier/errors.py:54-175 — CopierError → UserMessageError 三层继承。

接口约定：所有异常必须有 exit_code: int 属性，Click 入口据此设置 sys.exit(code)。
"""


class InitError(Exception):
    """基类，所有 init 异常继承此。

    exit_code 由 Click 入口读取并设置为进程退出码。
    """

    exit_code: int = 1


class ConfigFileError(InitError):
    """ae-template.yml 不存在、格式错误、版本不兼容。"""

    exit_code = 2


class UnsatisfiedPrerequisiteError(InitError):
    """git/node/python 等必需工具未安装。"""

    exit_code = 3


class TargetDirectoryError(InitError):
    """目标目录不可写 / 非空且无 --force。"""

    exit_code = 4


class ValidationError(InitError):
    """用户输入校验失败（validator 返回非空）。"""

    exit_code = 5


class TaskExecutionError(InitError):
    """钩子命令执行失败。携带 process.returncode + stderr。"""

    exit_code = 6

    def __init__(self, command: str, returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Task '{command}' failed (exit={returncode}): {stderr}")


class TemplateRenderError(InitError):
    """Jinja2 渲染异常。携带源文件路径。"""

    exit_code = 7

    def __init__(self, src_path: str, jinja_error: Exception):
        self.src_path = src_path
        self.jinja_error = jinja_error
        super().__init__(f"Template render error in {src_path}: {jinja_error}")


class InitInterruptedError(InitError):
    """用户 Ctrl-C 中断。部分答案已保存到 ~/.ae-partial-answers.yml。"""

    exit_code = 130
