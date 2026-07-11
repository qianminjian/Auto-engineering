"""Tool authorization matrix + authz_check (v5.0 §B12.1 + §B2.9c; v5.6 §B12 六新角色).

设计要点:
- 10 工具 × 9 角色 (v5.5 三角色 + v5.6 §B12 分层验证/Phase0 六角色, T16b)
- architect: 只读 3 工具 (read_file / search_code / list_dir) + git_status
- developer: 全部 10 工具 (写入 + git + tests)
- critic:   只读 3 + git_status + git_diff
- v5.6 六角色 (均只读, 无写/无 shell/无 commit, 锚定各 prompts/roles/*.md 工具集):
  - component_verifier / system_verifier / gap_scan / research: 只读 3 + git_status
  - plate_deep_audit: 只读 3 + git_status + git_diff
  - system_deep_audit: 只读 3 + git_status + git_diff + run_tests
- 未授权 / 未注册工具 → 返回 error tool_result 而非抛异常
  (v5.0 §B4.4 step 3b: 授权失败降级为可观察错误)

注 (v5.6 tick 模型): 六新角色由 Agent 路径执行, authz 是 in-process 路径
(base.py 工具循环) 的 role→tool 权威契约。补全 9 role 消除"矩阵缺行→静默全拒"
的隐式漏洞, 使授权矩阵与 tick 角色词汇表一致。research role 的**工具级内存护栏**
(S-10: 拒绝无过滤递归列举 / ReadFile ≤200 行 / SearchCode 结果封顶) 属参数级
enforcement, 见 design §B10.6 —— 布尔矩阵只做工具粒度授权, 参数级护栏待接线。

借鉴:
- LangGraph graph/state.py:150-180 节点权限元数据
- CrewAI agent.py:80-130 role-based tool filtering
"""

from __future__ import annotations

__all__ = ["AUTHZ_MATRIX", "authz_check"]

# 只读 10 工具基线 (read 3 + git_status, 其余禁) — v5.6 只读角色共享.
_READONLY_10: dict[str, bool] = {
    "read_file": True,
    "search_code": True,
    "list_dir": True,
    "write_file": False,
    "edit_file": False,
    "run_bash": False,
    "git_status": True,
    "git_commit": False,
    "git_diff": False,
    "run_tests": False,
}

# v5.0 §B12.1 + v5.6 §B12: AUTHZ_MATRIX 10 工具 × 9 角色
# role -> {tool_name: allowed}
# 2026-07-04 修复 (v5.0 深度审计 P1-S-03): 加 git_status 权限 (只读, 全角色允许).
# 旧版缺 git_status 导致 authz_check("any_role", "git_status") 永远 False,
# GitStatusTool 工具注册但永远不可用.
AUTHZ_MATRIX: dict[str, dict[str, bool]] = {
    "architect": {
        "read_file": True,
        "search_code": True,
        "list_dir": True,
        "write_file": False,
        "edit_file": False,
        "run_bash": False,
        "git_status": True,   # P1-S-03: 只读, 3 角色都允许
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
        "git_status": True,   # P1-S-03: 只读, 3 角色都允许
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
        "git_status": True,   # P1-S-03: 只读, 3 角色都允许
        "git_commit": False,
        "git_diff": True,
        "run_tests": False,
    },
    # ── v5.6 §B12 分层验证 + Phase0 角色 (T16b, 均只读) ──
    "component_verifier": dict(_READONLY_10),
    "system_verifier": dict(_READONLY_10),
    "gap_scan": dict(_READONLY_10),
    "research": dict(_READONLY_10),
    # plate/system deep audit: 只读 + git_diff (审 diff); system 另加 run_tests.
    "plate_deep_audit": {**_READONLY_10, "git_diff": True},
    "system_deep_audit": {**_READONLY_10, "git_diff": True, "run_tests": True},
}


def authz_check(role: str, tool_name: str) -> bool:
    """检查 role 是否被允许使用 tool_name (v5.0 §B2.9c).

    Args:
        role: 角色名 (architect/developer/critic + v5.6 六验证/Phase0 角色)
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
