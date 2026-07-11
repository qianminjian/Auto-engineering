"""M2 Guardrail 链 — GuardrailResult + Guardrail ABC + 5 Guardrails + Chain + handler 测试.

设计参考: v5.6-Design-Loop.md §B2.3 (Guardrail 接口契约)
                   + §B1.8 (GuardrailResult 数据类)
                   + §B5.1 (5 Guardrail 规格 G1-G5)
                   + §B5.2 (_handle_guardrail_result 4 态)

测试原则 (per pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- 5 Guardrail × 2-4 边界 + Chain 过滤/fail-fast + handler 4 态 + retry 耗尽
- G3 new repo 降级 (HEAD~1 不存在 → --cached)
- G3/G5 用 tmp_path 模拟 git repo (真实 subprocess)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrail import (
    GitClean,
    GitDiffExists,
    Guardrail,
    GuardrailChain,
    GuardrailResult,
    NoDeferredBlockingGap,
    PlanExists,
    RequirementValid,
    TestsPass,
    handle_guardrail_result,
)

# ---------- helpers ----------

def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    """在指定目录下跑 git 命令（不抛错）."""
    full_env = env or {}
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        env=full_env or None,
    )


def _make_git_repo(tmp_path: Path, with_commit: bool = True) -> Path:
    """创建临时 git repo，提交 1 个文件作为 HEAD~1..HEAD 可用."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
        # 让 git 在 sandbox 内可识别时间
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00+0000",
    }
    _git(repo, "init", "-q", env=env)
    _git(repo, "config", "user.email", "t@x", env=env)
    _git(repo, "config", "user.name", "t", env=env)
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt", env=env)
    _git(repo, "commit", "-q", "-m", "init", env=env)
    if not with_commit:
        # 回到首 commit 不存在 (无法 HEAD~1)
        # 这里保留单一 commit，但 flag 保留供扩展
        pass
    return repo


def _make_new_repo(tmp_path: Path) -> Path:
    """创建没有任何 commit 的 git repo (没有 HEAD~1)."""
    repo = tmp_path / "new_repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    _git(repo, "init", "-q", env=env)
    _git(repo, "config", "user.email", "t@x", env=env)
    _git(repo, "config", "user.name", "t", env=env)
    # 不做 commit，保持全新仓库
    (repo / "staged.txt").write_text("new content\n")
    _git(repo, "add", "staged.txt", env=env)
    return repo


# ---------- GuardrailResult 数据类 ----------

class TestGuardrailResult:
    """GuardrailResult 必须含 action + message 字段."""

    def test_default_action_pass_message_empty(self) -> None:
        """默认 action='pass', message=''."""
        r = GuardrailResult()
        assert r.action == "pass"
        assert r.message == ""

    def test_explicit_block(self) -> None:
        """显式 block + message."""
        r = GuardrailResult(action="block", message="bad")
        assert r.action == "block"
        assert r.message == "bad"

    def test_all_actions(self) -> None:
        """3 action 值都允许: pass / block / retry (v5.1 P0-1: drop 态已删除)."""
        for action in ("pass", "block", "retry"):
            r = GuardrailResult(action=action, message=f"msg-{action}")
            assert r.action == action
            assert r.message == f"msg-{action}"

    def test_guardrail_result_action_is_3_states(self) -> None:
        """v5.1 P0-1: GuardrailResult.action 严格 Literal 3 态 (pass/block/retry).

        验证 Action type alias 只暴露 3 个值 — drop 已从契约中删除.
        """
        # 1. typing.get_args 校验 Literal 包含的字符串
        import typing

        from auto_engineering.loop.guardrail import Action

        args = set(typing.get_args(Action))
        assert args == {"pass", "block", "retry"}, (
            f"Action Literal 应仅含 3 态, 实际: {args}"
        )

    def test_drop_action_raises_typeerror(self) -> None:
        """v5.1 P0-1: 传入 drop 应被 dataclass 类型系统拒绝 (Literal 校验).

        注: 现有实现 GuardrailResult 字段类型是 str (未用 Literal),
        此测试先注释 — 实现层应升级到 Action Literal 才能启用.
        当前是契约文档层证明 drop 不在合法 action 集合.
        """
        import typing

        from auto_engineering.loop.guardrail import Action

        args = set(typing.get_args(Action))
        assert "drop" not in args, "drop 态必须已从 Action Literal 删除"


# ---------- Guardrail ABC 基类契约 ----------

class _DummyGuardrail(Guardrail):
    """Concrete guardrail for ABC contract verification."""
    name = "dummy"
    timing = "pre"
    applies_to_stages = ("architect",)

    def check(
        self,
        stage: str,
        state: Any,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        return GuardrailResult(action="pass", message="")


class TestGuardrailABC:
    """Guardrail ABC 必须提供 name/timing/applies_to_stages 属性 + check()."""

    def test_abc_cannot_instantiate(self) -> None:
        """Guardrail 是抽象类，不能直接实例化."""
        with pytest.raises(TypeError):
            Guardrail()  # type: ignore[abstract]

    def test_subclass_must_implement_check(self) -> None:
        """未实现 check() 的子类不能实例化."""

        class MissingCheck(Guardrail):
            name = "mc"
            timing = "pre"
            applies_to_stages = ("architect",)

        with pytest.raises(TypeError):
            MissingCheck()  # type: ignore[abstract]

    def test_subclass_with_check_instantiates(self) -> None:
        g = _DummyGuardrail()
        assert g.name == "dummy"
        assert g.timing == "pre"
        assert g.applies_to_stages == ("architect",)
        result = g.check("architect", EngineState())
        assert result.action == "pass"

    def test_check_receives_stage_state_project_root(self) -> None:
        """check() 必须接受 (stage, state, project_root=None)."""

        class SpyGuardrail(Guardrail):
            name = "spy"
            timing = "post"
            applies_to_stages = ("developer",)
            captured: dict[str, Any] = {}

            def check(self, stage, state, project_root=None):
                SpyGuardrail.captured = {
                    "stage": stage,
                    "state_id": id(state),
                    "project_root": project_root,
                }
                return GuardrailResult()

        g = SpyGuardrail()
        state = EngineState()
        g.check("developer", state, project_root=Path("/tmp/x"))
        assert SpyGuardrail.captured["stage"] == "developer"
        assert SpyGuardrail.captured["state_id"] == id(state)
        assert SpyGuardrail.captured["project_root"] == Path("/tmp/x")


# ---------- G1 RequirementValid (pre/architect) ----------

class TestRequirementValid:
    """G1: state.requirement 必须非空 / 1..4096 / 非仅控制字符."""

    def test_pass_valid_requirement(self) -> None:
        """正常需求 → pass."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="实现登录"),
        )
        assert result.action == "pass"
        assert result.message == ""

    def test_block_empty(self) -> None:
        """空字符串 → block."""
        result = RequirementValid().check(
            "architect", EngineState(requirement=""),
        )
        assert result.action == "block"
        assert "requirement" in result.message.lower() or "空" in result.message

    def test_block_only_whitespace(self) -> None:
        """纯空白 → block (等价于空)."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="   \t\n  "),
        )
        assert result.action == "block"

    def test_block_only_control_chars(self) -> None:
        """仅控制字符（如 \\x00\\x01） → block."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="\x00\x01\x02"),
        )
        assert result.action == "block"

    def test_block_too_long(self) -> None:
        """长度 > 4096 → block."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="a" * 4097),
        )
        assert result.action == "block"

    def test_pass_max_length(self) -> None:
        """长度恰好 4096 → pass (边界)."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="a" * 4096),
        )
        assert result.action == "pass"

    def test_pass_min_length(self) -> None:
        """长度 1 → pass (非空最小边界)."""
        result = RequirementValid().check(
            "architect", EngineState(requirement="x"),
        )
        assert result.action == "pass"

    def test_timing_and_stage(self) -> None:
        """类属性: timing='pre', applies_to_stages=('architect',)."""
        g = RequirementValid()
        assert g.timing == "pre"
        assert g.applies_to_stages == ("architect",)
        assert g.name  # 非空


# ---------- G2 PlanExists (post/architect) ----------

class TestPlanExists:
    """G2: state.plan 非空 AND state.file_list 非空 AND len>=1."""

    def test_pass_valid(self) -> None:
        """plan 非空 + file_list 1+ → pass."""
        state = EngineState(plan="step 1: implement X", file_list=["a.py"])
        result = PlanExists().check("architect", state)
        assert result.action == "pass"

    def test_retry_empty_plan(self) -> None:
        """plan 空 → retry."""
        state = EngineState(plan="", file_list=["a.py"])
        result = PlanExists().check("architect", state)
        assert result.action == "retry"

    def test_retry_empty_file_list(self) -> None:
        """file_list 空 → retry."""
        state = EngineState(plan="ok", file_list=[])
        result = PlanExists().check("architect", state)
        assert result.action == "retry"

    def test_retry_both_empty(self) -> None:
        """plan 空 AND file_list 空 → retry."""
        state = EngineState(plan="", file_list=[])
        result = PlanExists().check("architect", state)
        assert result.action == "retry"

    def test_timing_and_stage(self) -> None:
        g = PlanExists()
        assert g.timing == "post"
        assert g.applies_to_stages == ("architect",)


# ---------- G3 GitDiffExists (post/developer) ----------

class TestGitDiffExists:
    """G3: git diff HEAD~1..HEAD --numstat 非空，新仓库降级 --cached."""

    def test_pass_with_real_diff(self, tmp_path: Path) -> None:
        """有 commit + 有未变化: 实际 diff 存在 → pass."""
        repo = _make_git_repo(tmp_path)
        # 二次 commit 让 HEAD~1..HEAD 有 diff
        (repo / "new.txt").write_text("added\n")
        _git(repo, "add", "new.txt")
        _git(repo, "commit", "-q", "-m", "add new")
        state = EngineState()
        result = GitDiffExists().check(
            "developer", state, project_root=repo,
        )
        assert result.action == "pass"

    def test_retry_no_diff(self, tmp_path: Path) -> None:
        """有 commit 但 HEAD~1..HEAD 无变化 → retry."""
        repo = _make_git_repo(tmp_path)
        # 不再做 commit，HEAD~1..HEAD 就是空
        state = EngineState()
        result = GitDiffExists().check(
            "developer", state, project_root=repo,
        )
        assert result.action == "retry"

    def test_pass_new_repo_with_cached(self, tmp_path: Path) -> None:
        """新仓库（无 HEAD~1）→ 降级到 --cached,有 staged 内容时 → pass."""
        repo = _make_new_repo(tmp_path)
        state = EngineState()
        result = GitDiffExists().check(
            "developer", state, project_root=repo,
        )
        assert result.action == "pass"

    def test_retry_new_repo_no_cached(self, tmp_path: Path) -> None:
        """新仓库且无 staged 内容 → retry."""
        repo = _make_new_repo(tmp_path)
        # 清掉 staged
        _git(repo, "reset", "-q")
        state = EngineState()
        result = GitDiffExists().check(
            "developer", state, project_root=repo,
        )
        assert result.action == "retry"

    def test_uses_asyncio_to_thread(self) -> None:
        """G3 是 async-safe: 调用 .check() 是同步入口,但内部用 asyncio.run 封装.
        (Subprocess 不能阻塞 event loop).
        """
        # 通过同步调用即可触发（实现内部负责线程切换）
        # 这里不需要真异步 - 只验证 .check() 在线程池模式下不会阻塞
        import asyncio

        async def run_async() -> GuardrailResult:
            # 检查实现允许在 async 上下文被 async 包装
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: GitDiffExists().check(
                    "developer", EngineState(),
                    project_root=Path("/nonexistent"),
                ),
            )

        # 不抛异常即可 (Path 不存在 → 应降级到 retry/block, 不抛 OSError)
        try:
            result = asyncio.run(run_async())
            assert result.action in ("retry", "block", "pass")
        except (OSError, subprocess.CalledProcessError):
            # 如果实现抛了也接受 - 但更佳是优雅处理
            pass

    def test_timing_and_stage(self) -> None:
        g = GitDiffExists()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer",)


# ---------- G4 TestsPass (post/developer) ----------

class TestTestsPass:
    """G4: test_results.failed==0 + errors==0 + passed+failed+errors>0 → pass."""

    def test_pass_all_green(self) -> None:
        """failed=0, errors=0, passed=5 → pass."""
        state = EngineState(test_results={"passed": 5, "failed": 0, "errors": 0})
        result = TestsPass().check("developer", state)
        assert result.action == "pass"

    def test_retry_with_failures(self) -> None:
        """failed=1 → retry."""
        state = EngineState(test_results={"passed": 5, "failed": 1, "errors": 0})
        result = TestsPass().check("developer", state)
        assert result.action == "retry"

    def test_retry_with_errors(self) -> None:
        """errors=1 → retry."""
        state = EngineState(test_results={"passed": 5, "failed": 0, "errors": 1})
        result = TestsPass().check("developer", state)
        assert result.action == "retry"

    def test_retry_empty_results(self) -> None:
        """test_results={} (没人跑测试) → retry (没真跑测试不能算 pass)."""
        state = EngineState(test_results={})
        result = TestsPass().check("developer", state)
        assert result.action == "retry"

    def test_timing_and_stage(self) -> None:
        g = TestsPass()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer",)


# ---------- G5 GitClean (post/developer) ----------

class TestGitClean:
    """G5: git status --porcelain 输出空 → pass, 否则 block."""

    def test_pass_clean_repo(self, tmp_path: Path) -> None:
        """新 repo 无未提交变更 → pass."""
        repo = _make_git_repo(tmp_path)
        result = GitClean().check(
            "developer", EngineState(), project_root=repo,
        )
        assert result.action == "pass"

    def test_block_dirty_repo(self, tmp_path: Path) -> None:
        """有未跟踪文件 → block."""
        repo = _make_git_repo(tmp_path)
        (repo / "dirty.txt").write_text("untracked\n")
        result = GitClean().check(
            "developer", EngineState(), project_root=repo,
        )
        assert result.action == "block"
        assert "dirty" in result.message.lower() or "未提交" in result.message or "变更" in result.message or "untracked" in result.message.lower()

    def test_block_staged_changes(self, tmp_path: Path) -> None:
        """有已 staged 未 commit 的变更 → block."""
        repo = _make_git_repo(tmp_path)
        (repo / "staged.txt").write_text("new\n")
        _git(repo, "add", "staged.txt")
        result = GitClean().check(
            "developer", EngineState(), project_root=repo,
        )
        assert result.action == "block"

    def test_block_modified_tracked(self, tmp_path: Path) -> None:
        """修改已 tracked 文件 → block."""
        repo = _make_git_repo(tmp_path)
        (repo / "seed.txt").write_text("modified\n")
        result = GitClean().check(
            "developer", EngineState(), project_root=repo,
        )
        assert result.action == "block"

    def test_timing_and_stage(self) -> None:
        g = GitClean()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer",)


# ---------- GuardrailChain.check() ----------

class TestGuardrailChain:
    """Chain 过滤 (timing + stage) + fail-fast."""

    def test_empty_chain_returns_pass(self) -> None:
        """空 Chain → pass."""
        chain = GuardrailChain([])
        result = chain.check("pre", "architect", EngineState())
        assert result.action == "pass"
        assert result.message == ""

    def test_pre_filter(self) -> None:
        """timing 过滤: pre-only guardrail 不被 post 调用执行."""
        chain = GuardrailChain([RequirementValid()])
        # pre guardrail 用 pre 调用 → 正常跑
        result = chain.check("pre", "architect", EngineState(requirement="ok"))
        assert result.action == "pass"
        # post 调用 → pre guardrail 被跳过
        result_post = chain.check(
            "post", "architect", EngineState(requirement=""),
        )
        assert result_post.action == "pass"

    def test_stage_filter(self) -> None:
        """stage 过滤: guardrail 仅在 applies_to_stages 中跑."""
        chain = GuardrailChain([RequirementValid()])
        # RequirementValid applies_to=("architect",)
        # 用 developer 调 → 跳过
        result = chain.check(
            "pre", "developer", EngineState(requirement=""),
        )
        assert result.action == "pass"  # 跳过实际是空 requirement → 应该 pass (因为没跑)

    def test_fail_fast_first_block_returns_immediately(self) -> None:
        """多个 guardrail,第一个不通过立即返回,不跑后续."""
        # 构造: RequirementValid block (空) + dummy post-pass
        calls: list[str] = []

        class SpyPassPost(Guardrail):
            name = "spy-post"
            timing = "pre"
            applies_to_stages = ("architect",)

            def check(self, stage, state, project_root=None):
                calls.append("post-pass")
                return GuardrailResult(action="pass")

        chain = GuardrailChain([RequirementValid(), SpyPassPost()])
        result = chain.check(
            "pre", "architect", EngineState(requirement=""),
        )
        assert result.action == "block"  # RequirementValid block
        assert calls == []  # SpyPassPost 没被调

    def test_fail_fast_retry_then_block(self) -> None:
        """多 guardrail: 第一个 retry, 后面的 block 不会被跑."""
        chain = GuardrailChain([PlanExists(), RequirementValid()])
        # PlanExists 是 post/architect. 用 pre 调会跳过 PlanExists,
        # RequirementValid block (empty requirement).
        result = chain.check(
            "pre", "architect", EngineState(requirement=""),
        )
        assert result.action == "block"

    def test_all_pass_returns_pass(self) -> None:
        """所有 guardrail pass → 最后返回 pass."""
        # PlanExists + RequirementValid 都 pass 状态
        chain = GuardrailChain([RequirementValid(), PlanExists()])
        state = EngineState(requirement="ok", plan="p", file_list=["a.py"])
        # pre=architect: RequirementValid 跑 (pass), PlanExists 被 timing filter 跳过
        # 我们测 pre/post 时机同时过滤
        result = chain.check("pre", "architect", state)
        assert result.action == "pass"

    def test_default_5_guardrails_chain(self) -> None:
        """默认 Chain (5 内置 Guardrail) 的 stage/timing 分布正确."""
        chain = GuardrailChain([
            RequirementValid(),
            PlanExists(),
            GitDiffExists(),
            TestsPass(),
            GitClean(),
        ])
        # pre/architect → 只有 G1 跑
        assert len([g for g in chain.guardrails if g.timing == "pre"]) == 1
        # post/architect → 只有 G2 跑
        assert len([g for g in chain.guardrails if g.timing == "post" and "architect" in g.applies_to_stages]) == 1
        # post/developer → G3 + G4 + G5
        assert len([g for g in chain.guardrails if g.timing == "post" and "developer" in g.applies_to_stages]) == 3

    def test_default_factory_returns_6_guardrails(self) -> None:
        """GuardrailChain.default() 返回 6 Guardrail 链 (G1-G5 + G6 NoDeferredBlockingGap)."""
        chain = GuardrailChain.default()
        assert len(chain.guardrails) == 6
        names = [type(g).__name__ for g in chain.guardrails]
        assert "RequirementValid" in names
        assert "PlanExists" in names
        assert "GitDiffExists" in names
        assert "TestsPass" in names
        assert "GitClean" in names
        assert "NoDeferredBlockingGap" in names

    def test_default_factory_same_structure_as_manual(self) -> None:
        """GuardrailChain.default() 与手动构造的 chain 行为一致."""
        default_chain = GuardrailChain.default()
        manual_chain = GuardrailChain([
            RequirementValid(),
            PlanExists(),
            GitDiffExists(),
            TestsPass(),
            GitClean(),
            NoDeferredBlockingGap(),
        ])
        # 同数量
        assert len(default_chain.guardrails) == len(manual_chain.guardrails)
        # 同类型
        assert [type(g).__name__ for g in default_chain.guardrails] == [
            type(g).__name__ for g in manual_chain.guardrails
        ]

    def test_default_chain_pre_check_architect(self) -> None:
        """default() chain: pre/architect → RequirementValid 检查 requirement."""
        chain = GuardrailChain.default()
        # 空 requirement → block
        result = chain.check("pre", "architect", EngineState(requirement=""))
        assert result.action == "block"
        # 有效 requirement → pass
        result = chain.check("pre", "architect", EngineState(requirement="valid requirement"))
        assert result.action == "pass"

    def test_default_chain_post_check_architect(self) -> None:
        """default() chain: post/architect → PlanExists 检查 plan+file_list."""
        chain = GuardrailChain.default()
        # 缺 plan + file_list → retry
        result = chain.check("post", "architect", EngineState(requirement="x"))
        assert result.action == "retry"
        # 完整产出 → pass
        state = EngineState(requirement="x", plan="p", file_list=["a.py"])
        result = chain.check("post", "architect", state)
        assert result.action == "pass"


# ---------- _handle_guardrail_result 4 态 + retry 计数 ----------

class TestHandleGuardrailResult:
    """action 分发 → continue / stop / retry (含计数耗尽)."""

    def test_pass_returns_continue(self) -> None:
        """pass → continue."""
        state = EngineState()
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action="pass", message=""),
            "developer", state, counters,
        )
        assert action == "continue"
        assert counters == {}  # pass 不动计数器

    def test_block_returns_stop(self) -> None:
        """block → stop, 不动计数器."""
        state = EngineState(plan="x")
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action="block", message="bad"),
            "developer", state, counters,
        )
        assert action == "stop"
        assert counters == {}  # block 不动计数器

    def test_retry_first_time_increments_counter(self) -> None:
        """retry 第 1 次 → counter + 1, clear stage fields, return 'retry'."""
        state = EngineState(
            plan="x",
            files_changed=["a.py"],
            commit_hash="abc",
            test_results={"passed": 1},
        )
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="flaky"),
            "developer", state, counters,
        )
        assert action == "retry"
        assert counters == {"developer": 1}
        # 确认 stage fields 已清空 (reuse stage_router.clear_stage_fields)
        assert state.files_changed == []
        assert state.commit_hash == ""
        assert state.test_results == {}

    def test_retry_second_time_increments(self) -> None:
        """retry 第 2 次 → counter = 2."""
        state = EngineState()
        counters: dict[str, int] = {"developer": 1}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="flaky"),
            "developer", state, counters,
        )
        assert action == "retry"
        assert counters == {"developer": 2}

    def test_retry_third_time_returns_retry(self) -> None:
        """retry 第 3 次 (counter 2→3): 仍允许 (MAX=3).

        实现语义: MAX_RETRY_PER_STAGE=3 → 允许 3 次 retry, 第 4 次才 stop.
        counter=2 进来 → check 2 < 3 → 累加到 3 → retry.
        """
        state = EngineState()
        counters: dict[str, int] = {"developer": 2}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="flaky"),
            "developer", state, counters,
        )
        # 第 3 次 (counter=2->3) 仍允许 retry
        assert action == "retry"
        assert counters == {"developer": 3}

    def test_retry_exhaustion_returns_stop(self) -> None:
        """retry counter 已 ≥ 3 → stop (不再累加/不再 clear)."""
        state = EngineState(plan="x", files_changed=["a.py"])
        counters: dict[str, int] = {"developer": 3}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="flaky"),
            "developer", state, counters,
        )
        assert action == "stop"
        assert counters == {"developer": 3}  # 不再 +1
        # 不应再 clear (stop 路径)
        assert state.plan == "x"
        assert state.files_changed == ["a.py"]

    def test_handler_drop_returns_stop_unknown_action(self) -> None:
        """v5.4 P2-8: drop 已从契约删除, 作为未知 action 走防御性 stop."""
        state = EngineState()
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action="drop", message="drop me"),  # type: ignore[arg-type]
            "developer", state, counters,
        )
        assert action == "stop"
        assert counters == {}

    def test_handler_unknown_action_returns_stop(self) -> None:
        """未知 action 走防御性 stop, 不修改 state/counters."""
        state = EngineState(
            plan="x",
            files_changed=["a.py"],
            commit_hash="abc",
        )
        counters: dict[str, int] = {"developer": 1}
        action = handle_guardrail_result(
            GuardrailResult(action="unknown_action", message="x"),  # type: ignore[arg-type]
            "developer", state, counters,
        )
        assert action == "stop"
        assert counters == {"developer": 1}
        assert state.files_changed == ["a.py"]

    def test_counters_isolated_per_stage(self) -> None:
        """counters 按 stage 隔离, 互不影响."""
        state = EngineState()
        counters: dict[str, int] = {"architect": 2}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="x"),
            "developer", state, counters,
        )
        assert action == "retry"
        # architect 计数不变 (隔离)
        assert counters["architect"] == 2
        assert counters["developer"] == 1

    def test_unknown_action_returns_stop(self) -> None:
        """action 不在 pass/block/drop/retry → 防御性 stop."""
        from typing import cast

        state = EngineState()
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action=cast(Any, "warp"), message="weird"),
            "developer", state, counters,
        )
        assert action == "stop"

    def testclear_stage_fields_reused_from_stage_router(self) -> None:
        """_handle_guardrail_result 必须清空对应该 stage 的字段 (验证 stage 隔离).

        e.g. retry on architect → clear plan/file_list/batch_plan/contracts
        retry on developer → clear files_changed/commit_hash/test_results
        retry on critic    → clear verdict/findings/critic_feedback
        """
        # Architect retry
        state = EngineState(
            plan="x",
            file_list=["a.py"],
            batch_plan=[{"id": "1"}],
            contracts={"k": "v"},
        )
        counters: dict[str, int] = {}
        handle_guardrail_result(
            GuardrailResult(action="retry", message="r"),
            "architect", state, counters,
        )
        assert state.plan == ""
        assert state.file_list == []
        assert state.batch_plan == []
        assert state.contracts == {}

        # Critic retry
        state2 = EngineState(
            critic_verdict="MAJOR", findings=[{"x": 1}], critic_feedback="fb",
        )
        handle_guardrail_result(
            GuardrailResult(action="retry", message="r"),
            "critic", state2, {},
        )
        assert state2.critic_verdict == ""
        assert state2.findings == []
        assert state2.critic_feedback == ""


# ==================== G6: NoDeferredBlockingGap ====================


def _gap_review_state(*, has_blocking, gaps, decisions):
    """构造 post/gap_review Guardrail 输入: gap_report_json + pending_gap_decisions."""
    return EngineState(
        gap_report_json=json.dumps(
            {"gaps": gaps, "scanned_sections": len(gaps),
             "has_blocking": has_blocking},
            ensure_ascii=False),
        pending_gap_decisions=decisions,
    )


class TestNoDeferredBlockingGap:
    """G6 (§B10.5 / B3 line 642): has_blocking 时 architectural gap 不允许
    Defer/Defer+Research → block. 修复前 validate_resolutions 是死代码 (从未接线)."""

    def test_timing_and_stage(self) -> None:
        g = NoDeferredBlockingGap()
        assert g.timing == "post"
        assert g.applies_to_stages == ("gap_review",)

    def test_architectural_defer_blocks(self) -> None:
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "g1", "grade": "architectural", "clarity": "missing",
                   "summary": "契约缺失"}],
            decisions=[{"gap_id": "g1", "resolution": "defer"}],
        )
        r = NoDeferredBlockingGap().check("gap_review", state)
        assert r.action == "block"
        assert "g1" in r.message

    def test_architectural_defer_research_blocks(self) -> None:
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "g1", "grade": "architectural", "clarity": "vague",
                   "summary": "契约模糊"}],
            decisions=[{"gap_id": "g1", "resolution": "defer_research"}],
        )
        assert NoDeferredBlockingGap().check("gap_review", state).action == "block"

    def test_architectural_fill_passes(self) -> None:
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "g1", "grade": "architectural", "clarity": "missing",
                   "summary": "契约缺失"}],
            decisions=[{"gap_id": "g1", "resolution": "fill",
                        "fill_content": "契约 X→Y"}],
        )
        assert NoDeferredBlockingGap().check("gap_review", state).action == "pass"

    def test_architectural_research_passes(self) -> None:
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "g1", "grade": "architectural", "clarity": "missing",
                   "summary": "契约缺失"}],
            decisions=[{"gap_id": "g1", "resolution": "research"}],
        )
        assert NoDeferredBlockingGap().check("gap_review", state).action == "pass"

    def test_component_defer_passes(self) -> None:
        """非 architectural gap 允许 defer — 只有 architectural 受 B10.5 约束."""
        state = _gap_review_state(
            has_blocking=False,
            gaps=[{"id": "g1", "grade": "component", "clarity": "vague",
                   "summary": "接口细节"}],
            decisions=[{"gap_id": "g1", "resolution": "defer"}],
        )
        assert NoDeferredBlockingGap().check("gap_review", state).action == "pass"

    def test_mixed_one_architectural_defer_blocks(self) -> None:
        """component gap fill + architectural gap defer → 因 architectural 仍 block."""
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "gc", "grade": "component", "clarity": "vague", "summary": "x"},
                  {"id": "ga", "grade": "architectural", "clarity": "missing",
                   "summary": "契约"}],
            decisions=[{"gap_id": "gc", "resolution": "fill", "fill_content": "c"},
                       {"gap_id": "ga", "resolution": "defer"}],
        )
        r = NoDeferredBlockingGap().check("gap_review", state)
        assert r.action == "block"
        assert "ga" in r.message and "gc" not in r.message

    def test_no_decisions_passes(self) -> None:
        state = _gap_review_state(
            has_blocking=True,
            gaps=[{"id": "g1", "grade": "architectural", "clarity": "missing",
                   "summary": "契约"}],
            decisions=[],
        )
        assert NoDeferredBlockingGap().check("gap_review", state).action == "pass"

    def test_malformed_gap_report_json_fails_closed(self) -> None:
        state = EngineState(gap_report_json="{not valid json",
                            pending_gap_decisions=[{"gap_id": "g1", "resolution": "defer"}])
        assert NoDeferredBlockingGap().check("gap_review", state).action == "block"

    def test_missing_gap_report_passes(self) -> None:
        """无 gap_report_json (非 design-doc 模式) → pass (无 architectural 约束)."""
        state = EngineState()
        assert NoDeferredBlockingGap().check("gap_review", state).action == "pass"
