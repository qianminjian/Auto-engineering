"""AUTHZ_MATRIX 9 工具 × 3 角色 = 27 组合测试.

v5.0 §B12.1 — 工具授权矩阵单测.
v5.0 §B14.4 test_authz.py 必含 — R-21 风险应对.

授权矩阵设计（v5.0 §B12.1）:
- architect: 只读工具 3 个 (read_file / search_code / list_dir)
- developer: 全部 9 个 (含写入 + git + tests)
- critic:   只读 3 个 + git_diff (read_file / search_code / list_dir / git_diff)

总组合: 9 × 3 = 27 个 (3 architect + 9 developer + 4 critic + 13 未授权)
"""

from __future__ import annotations

import pytest


class TestAuthzCheckArchitect:
    """Architect 只允许 3 个只读工具."""

    @pytest.mark.parametrize(
        "tool_name",
        ["read_file", "search_code", "list_dir"],
    )
    def test_authz_check_architect_allowed_tools(self, tool_name: str) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check("architect", tool_name) is True, (
            f"architect should be allowed to use {tool_name}"
        )

    @pytest.mark.parametrize(
        "tool_name",
        [
            "write_file",
            "edit_file",
            "run_bash",
            "git_commit",
            "git_diff",
            "run_tests",
        ],
    )
    def test_authz_check_architect_denied_tools(self, tool_name: str) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check("architect", tool_name) is False, (
            f"architect should NOT be allowed to use {tool_name}"
        )


class TestAuthzCheckDeveloper:
    """Developer 允许全部 9 个工具."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "read_file",
            "search_code",
            "list_dir",
            "write_file",
            "edit_file",
            "run_bash",
            "git_commit",
            "git_diff",
            "run_tests",
        ],
    )
    def test_authz_check_developer_allowed_tools(self, tool_name: str) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check("developer", tool_name) is True, (
            f"developer should be allowed to use {tool_name}"
        )


class TestAuthzCheckCritic:
    """Critic 允许 4 个工具（3 只读 + git_diff）."""

    @pytest.mark.parametrize(
        "tool_name",
        ["read_file", "search_code", "list_dir", "git_diff"],
    )
    def test_authz_check_critic_allowed_tools(self, tool_name: str) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check("critic", tool_name) is True, (
            f"critic should be allowed to use {tool_name}"
        )

    @pytest.mark.parametrize(
        "tool_name",
        [
            "write_file",
            "edit_file",
            "run_bash",
            "git_commit",
            "run_tests",
        ],
    )
    def test_authz_check_critic_denied_tools(self, tool_name: str) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check("critic", tool_name) is False, (
            f"critic should NOT be allowed to use {tool_name}"
        )


class TestAuthzMatrix27Combinations:
    """完整 9 工具 × 3 角色 = 27 组合覆盖（v5.0 §B14.4 R-21）.

    期望矩阵（v5.0 §B12.1）:
        | tool          | architect | developer | critic |
        |---------------|-----------|-----------|--------|
        | read_file     |     Y     |     Y     |   Y    |
        | search_code   |     Y     |     Y     |   Y    |
        | list_dir      |     Y     |     Y     |   Y    |
        | write_file    |     N     |     Y     |   N    |
        | edit_file     |     N     |     Y     |   N    |
        | run_bash      |     N     |     Y     |   N    |
        | git_commit    |     N     |     Y     |   N    |
        | git_diff      |     N     |     Y     |   Y    |
        | run_tests     |     N     |     Y     |   N    |
    """

    @pytest.mark.parametrize(
        ("tool_name", "role", "expected"),
        [
            # architect: 3 Y + 6 N
            ("read_file", "architect", True),
            ("search_code", "architect", True),
            ("list_dir", "architect", True),
            ("write_file", "architect", False),
            ("edit_file", "architect", False),
            ("run_bash", "architect", False),
            ("git_commit", "architect", False),
            ("git_diff", "architect", False),
            ("run_tests", "architect", False),
            # developer: 9 Y
            ("read_file", "developer", True),
            ("search_code", "developer", True),
            ("list_dir", "developer", True),
            ("write_file", "developer", True),
            ("edit_file", "developer", True),
            ("run_bash", "developer", True),
            ("git_commit", "developer", True),
            ("git_diff", "developer", True),
            ("run_tests", "developer", True),
            # critic: 4 Y + 5 N
            ("read_file", "critic", True),
            ("search_code", "critic", True),
            ("list_dir", "critic", True),
            ("write_file", "critic", False),
            ("edit_file", "critic", False),
            ("run_bash", "critic", False),
            ("git_commit", "critic", False),
            ("git_diff", "critic", True),
            ("run_tests", "critic", False),
        ],
    )
    def test_authz_matrix_27_combinations(
        self, tool_name: str, role: str, expected: bool
    ) -> None:
        from auto_engineering.agents.authz import authz_check

        assert authz_check(role, tool_name) is expected, (
            f"authz_check({role!r}, {tool_name!r}) expected {expected}"
        )


class TestAuthzEdgeCases:
    """边界条件测试."""

    def test_authz_check_unknown_tool_returns_false(self) -> None:
        """未知工具名 → False（拒绝）."""
        from auto_engineering.agents.authz import authz_check

        assert authz_check("developer", "unknown_tool") is False
        assert authz_check("architect", "nonexistent") is False
        assert authz_check("critic", "made_up_tool") is False

    def test_authz_check_unknown_role_returns_false(self) -> None:
        """未知角色 → False（拒绝）."""
        from auto_engineering.agents.authz import authz_check

        assert authz_check("unknown_role", "read_file") is False
        assert authz_check("", "read_file") is False
        assert authz_check("BaseAgent", "read_file") is False

    def test_authz_matrix_is_exposed(self) -> None:
        """AUTHZ_MATRIX 是模块级 dict[str, dict[str, bool]]."""
        from auto_engineering.agents import authz

        assert hasattr(authz, "AUTHZ_MATRIX")
        assert isinstance(authz.AUTHZ_MATRIX, dict)
        # 必须含 3 角色
        assert set(authz.AUTHZ_MATRIX.keys()) == {"architect", "developer", "critic"}
        # developer 必须含全部 9 工具
        assert len(authz.AUTHZ_MATRIX["developer"]) == 9
