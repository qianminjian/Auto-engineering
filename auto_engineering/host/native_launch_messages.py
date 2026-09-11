"""原生宿主 Guard 的错误类型与可执行拒绝反馈。"""

from __future__ import annotations


class NativeLaunchGuardError(ValueError):
    """原生 Worker 工具调用没有消费当前 Action 的固定字段。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def guard_system_message(code: str) -> str:
    """返回宿主能直接执行的拒绝反馈，避免模型沿错误路径继续探查。"""

    messages = {
        "NATIVE_WORKER_PROMPT_READ_FORBIDDEN": (
            "已阻止读取 Worker prompt 正文；Coordinator 必须直接消费当前 Action 的 "
            "action.host_execution.workers[].native_launch_prompt，Worker 才能在 fresh context "
            "内读取 prompt_ref。"
        ),
        "NATIVE_LAUNCH_PROMPT_MISMATCH": (
            "已阻止原生 Worker 启动，但当前 Action 仍可继续：不要报告能力缺失，"
            "请从当前 compact Action 重新读取 action.host_execution.workers[]."
            "native_launch_prompt，并将该字段原样传入同一个 Agent 重试；禁止把 "
            "stage prompt 或 prompt_ref 正文作为 Agent 参数。"
        ),
        "NATIVE_WORKER_STOP_FORBIDDEN": (
            "已阻止停止当前 Worker；必须继续对同一个 Agent handle 调用 TaskOutput，"
            "直到 Worker 进入终态。"
        ),
        "NATIVE_WAIT_TIMEOUT_MISMATCH": (
            "已阻止短等待：必须使用当前 Action 声明的原生 wait timeout；"
            "普通 wait 到期只能记录心跳，不能让出 CONTINUE Action。"
        ),
        "NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN": (
            "已阻止 Coordinator 直接写入 Worker 私有 outcome；必须使用原生 Agent/Task"
            "返回和固定 record-worker-outcome 回写边界，不能手工伪造 Worker 事实。"
        ),
        "NATIVE_WORKER_OUTCOME_PATH_MISMATCH": (
            "已阻止 Worker 写入不属于当前 Action 的 outcome 路径；只能写入当前"
            " invocation 绑定的私有业务产物。"
        ),
        "NATIVE_RECORD_ARGUMENTS_MISSING": (
            "已阻止 Worker 回写命令：请原样使用当前 Action 的 record-worker-outcome "
            "argv_template，并把所有占位符替换为字面量；不得用 $VAR、$(...) 或 pwd。"
        ),
        "NATIVE_RESULT_PATH_MISMATCH": (
            "已阻止 Worker 回写命令：--native-result-file 必须逐字使用当前 Action "
            "绑定的路径；只修正这一参数后重试，不得手写 worker-outcomes。"
        ),
        "NATIVE_PROJECT_ROOT_INVALID": (
            "已阻止 Worker 回写命令：--project-root 必须是当前 Action 给出的字面量绝对路径，"
            "不得使用环境变量或命令替换；修正后重试同一命令。"
        ),
        "NATIVE_PROJECT_ROOT_MISMATCH": (
            "已阻止 Worker 回写命令：--project-root 必须逐字匹配当前项目根的字面量绝对路径，"
            "不得使用环境变量或命令替换；修正后重试同一命令。"
        ),
        "NATIVE_WORKER_TEMPLATE_UNAVAILABLE": (
            "已阻止未由当前 Action 声明的原生 Worker；当前 Action 没有可消费的"
            " workers[] 合同。若存在 host_execution.recovery 且 spawn_permitted=false，"
            "必须直接执行 recovery 的 finalize/validate/submit，不能自行发起 Worker；"
            "不得复用上一 Action 的 worker_id、handle、path 或 prompt。"
        ),
        "BINDING_DESIGN_READ_ONLY": (
            "已阻止修改当前 Loop 绑定的设计文档；该文档是只读设计权威。若确需变更，"
            "只能提交 design_change_requests[]，等待 Core 发出用户 Gate 后再执行。"
        ),
        "NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN": (
            "已阻止宿主直接写入 Core/Assembler 管理的 outcomes.json 或 result.json；"
            "只能写入当前 Action 的 coordinator-result.json，再按绑定的 "
            "finalize → validate → submit 操作生成完整 Result。"
        ),
    }
    return messages.get(
        code,
        "原生 Worker 调用未消费当前 Action 合同，已阻止执行。",
    )


__all__ = ["NativeLaunchGuardError", "guard_system_message"]
