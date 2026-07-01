"""Tool authorization matrix + authz_check (v5.0 §B12.1 + §B2.9c).

设计要点:
- 9 工具 × 3 角色 = 27 组合 (v5.0 §B14.4 R-21 全覆盖)
- architect: 只读 3 工具 (read_file / search_code / list_dir)
- developer: 全部 9 工具 (写入 + git + tests)
- critic:   4 工具 (只读 3 + git_diff)
- 未授权 / 未注册工具 → 返回 error tool_result 而非抛异常
  (v5.0 §B4.4 step 3b: 授权失败降级为可观察错误)

借鉴:
- LangGraph graph/state.py:150-180 节点权限元数据
- CrewAI agent.py:80-130 role-based tool filtering
"""

from __future__ import annotations

# v5.0 §B12.1: AUTHZ_MATRIX 9 工具 × 3 角色
# role -> {tool_name: allowed}
AUTHZ_MATRIX: dict[str, dict[str, bool]] = {
    "architect": {
        "read_file": True,
        "search_code": True,
        "list_dir": True,
        "write_file": False,
        "edit_file": False,
        "run_bash": False,
        "git_commit": False,
        "git_diff": False,
        "run_tests": False,
    },
    "developer": {
        "read_file": True,
        "search_code": True,
        "list_dir": True,
        "write_file": True,
        "edit_file": True,
        "run_bash": True,
        "git_commit": True,
        "git_diff": True,
        "run_tests": True,
    },
    "critic": {
        "read_file": True,
        "search_code": True,
        "list_dir": True,
        "write_file": False,
        "edit_file": False,
        "run_bash": False,
        "git_commit": False,
        "git_diff": True,
        "run_tests": False,
    },
}


def authz_check(role: str, tool_name: str) -> bool:
    """检查 role 是否被允许使用 tool_name (v5.0 §B2.9c).

    Args:
        role: 角色名 ('architect' / 'developer' / 'critic')
        tool_name: 工具名 ('read_file' / 'write_file' / ...)

    Returns:
        True  - 授权通过
        False - 未授权 / 未知 role / 未知 tool (默认拒绝)

    行为:
        - 未知 role → False (拒绝)
        - 未知 tool → False (拒绝)
        - 不抛异常 (调用方据此生成 error tool_result)
    """
    role_perms = AUTHZ_MATRIX.get(role)
    if role_perms is None:
        return False
    return role_perms.get(tool_name, False)
