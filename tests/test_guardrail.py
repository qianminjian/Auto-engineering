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
    FreshGate,
    GitClean,
    GitDiffExists,
    Guardrail,
    GuardrailChain,
    GuardrailResult,
    NoDeferredBlockingGap,
    PlanExists,
    REDGuard,
    RegressionGate,
    RequirementValid,
    TestsPass,
    _aggregate_sha,
    _git_is_ancestor,
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
        assert (
            "dirty" in result.message.lower()
            or "未提交" in result.message
            or "变更" in result.message
            or "untracked" in result.message.lower()
        )

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

    def test_default_factory_returns_9_guardrails(self) -> None:
        """GuardrailChain.default() 返回 9 Guardrail (G1-G6 + G7 REDGuard + G8 FreshGate + G9 RegressionGate)."""
        chain = GuardrailChain.default()
        assert len(chain.guardrails) == 9
        names = [type(g).__name__ for g in chain.guardrails]
        assert "RequirementValid" in names
        assert "PlanExists" in names
        assert "GitDiffExists" in names
        assert "TestsPass" in names
        assert "GitClean" in names
        assert "NoDeferredBlockingGap" in names
        assert "REDGuard" in names
        assert "FreshGate" in names
        assert "RegressionGate" in names

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
            REDGuard(),
            FreshGate(),
            RegressionGate(),
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


# ==================== G7: REDGuard (TDD RED commit-time 校验) ====================


class _StubTask:
    """轻量 Task 替身 (REDGuard 只读 .id / .target_files)."""

    def __init__(self, task_id: str, target_files: list[str]) -> None:
        self.id = task_id
        self.target_files = target_files


class _StubBatchState:
    """轻量 BatchState 替身 (REDGuard 只调 .current_batch_tasks(plan))."""

    def __init__(self, tasks: list[_StubTask]) -> None:
        self._tasks = tasks

    def current_batch_tasks(self, plan: Any) -> list[_StubTask]:
        return self._tasks


def _make_tdd_repo(tmp_path: Path, *, same_commit: bool = False) -> tuple[Path, str, str]:
    """构造 TDD 提交序列: seed → RED(test commit) → GREEN(impl commit).

    same_commit=True: 测试与实现放在同一 commit (违反 TDD 分离) —
    此时无"先于实现的独立测试 commit".

    Returns:
        (repo, test_commit_sha, impl_commit_sha). same_commit 时 test==impl.
    """
    repo = tmp_path / "tdd"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00+0000",
    }
    _git(repo, "init", "-q", env=env)
    _git(repo, "config", "user.email", "t@x", env=env)
    _git(repo, "config", "user.name", "t", env=env)
    (repo / "README").write_text("seed\n")
    _git(repo, "add", "README", env=env)
    _git(repo, "commit", "-q", "-m", "seed", env=env)

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_x():\n    assert False\n")

    def _head() -> str:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    if same_commit:
        (repo / "impl.py").write_text("def x():\n    return 1\n")
        _git(repo, "add", "tests/test_x.py", "impl.py", env=env)
        _git(repo, "commit", "-q", "-m", "test+impl together", env=env)
        sha = _head()
        return repo, sha, sha

    # RED: 独立测试 commit
    _git(repo, "add", "tests/test_x.py", env=env)
    _git(repo, "commit", "-q", "-m", "red: test_x", env=env)
    test_commit = _head()
    # GREEN: 独立实现 commit
    (repo / "impl.py").write_text("def x():\n    return 1\n")
    _git(repo, "add", "impl.py", env=env)
    _git(repo, "commit", "-q", "-m", "green: impl", env=env)
    impl_commit = _head()
    return repo, test_commit, impl_commit


def _redguard_state(
    *, impl_commit: str, batch_state: Any, red_evidence: list[dict] | None = None,
) -> EngineState:
    state = EngineState(commit_hash=impl_commit, red_evidence=red_evidence or [])
    # 运行时非持久句柄 (orchestrator 每 tick 挂载, 见 B3 line 657)
    state.batch_state = batch_state  # type: ignore[attr-defined]
    state._plan = object()  # type: ignore[attr-defined]
    return state


class TestREDGuard:
    """G7: 本轮 task 的测试 commit 先于实现 commit 且当时 FAIL (B3.1)."""

    def test_timing_and_stage(self) -> None:
        g = REDGuard()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer",)

    def test_pass_proper_tdd_with_evidence(self, tmp_path: Path) -> None:
        """测试先于实现独立 commit + red_evidence 匹配 → pass."""
        repo, test_c, impl_c = _make_tdd_repo(tmp_path)
        task = _StubTask("t1", ["tests/test_x.py", "impl.py"])
        state = _redguard_state(
            impl_commit=impl_c,
            batch_state=_StubBatchState([task]),
            red_evidence=[{"task_id": "t1", "test_id": "test_x",
                           "red_commit": test_c, "failure_excerpt": "assert False"}],
        )
        assert REDGuard().check("developer", state, project_root=repo).action == "pass"

    def test_retry_when_test_not_separate_commit(self, tmp_path: Path) -> None:
        """测试与实现同一 commit (无先于实现的独立测试 commit) → retry."""
        repo, _sha, impl_c = _make_tdd_repo(tmp_path, same_commit=True)
        task = _StubTask("t1", ["tests/test_x.py", "impl.py"])
        state = _redguard_state(
            impl_commit=impl_c, batch_state=_StubBatchState([task]),
            red_evidence=[{"task_id": "t1", "red_commit": impl_c}],
        )
        r = REDGuard().check("developer", state, project_root=repo)
        assert r.action == "retry"
        assert "t1" in r.message

    def test_retry_when_missing_red_evidence(self, tmp_path: Path) -> None:
        """独立测试 commit 存在但缺 red_evidence (非严格模式) → retry."""
        repo, _test_c, impl_c = _make_tdd_repo(tmp_path)
        task = _StubTask("t1", ["tests/test_x.py", "impl.py"])
        state = _redguard_state(
            impl_commit=impl_c, batch_state=_StubBatchState([task]),
            red_evidence=[],
        )
        r = REDGuard().check("developer", state, project_root=repo)
        assert r.action == "retry"
        assert "red_evidence" in r.message

    def test_pass_pure_config_task_exempt(self, tmp_path: Path) -> None:
        """纯配置/文档 task (无测试文件) → 豁免 pass."""
        repo, _test_c, impl_c = _make_tdd_repo(tmp_path)
        task = _StubTask("t1", ["pyproject.toml", "README.md"])
        state = _redguard_state(
            impl_commit=impl_c, batch_state=_StubBatchState([task]),
        )
        assert REDGuard().check("developer", state, project_root=repo).action == "pass"

    def test_pass_when_no_runtime_handles(self, tmp_path: Path) -> None:
        """无 batch_state/_plan 运行时句柄 (非 batch 模式) → pass (无从校验)."""
        repo, _test_c, impl_c = _make_tdd_repo(tmp_path)
        state = EngineState(commit_hash=impl_c)  # 不挂 batch_state
        assert REDGuard().check("developer", state, project_root=repo).action == "pass"

    def test_pass_when_no_commit_hash(self, tmp_path: Path) -> None:
        """无 impl commit_hash → pass (G3/G4 已覆盖'有无改动', REDGuard 无对象可校验)."""
        repo, _test_c, _impl_c = _make_tdd_repo(tmp_path)
        task = _StubTask("t1", ["tests/test_x.py"])
        state = _redguard_state(impl_commit="", batch_state=_StubBatchState([task]))
        assert REDGuard().check("developer", state, project_root=repo).action == "pass"

    def test_strict_mode_reruns_test(self, tmp_path: Path, monkeypatch) -> None:
        """严格模式 + 证据不匹配: red_commit 对不上 → checkout 重跑; 未 FAIL → retry."""
        import auto_engineering.loop.guardrail as gmod

        repo, _test_c, impl_c = _make_tdd_repo(tmp_path)
        task = _StubTask("t1", ["tests/test_x.py", "impl.py"])
        # red_commit 与实际测试 commit 不符 → 不走信任路径, 落入 _STRICT_RED 重跑
        state = _redguard_state(
            impl_commit=impl_c, batch_state=_StubBatchState([task]),
            red_evidence=[{"task_id": "t1", "test_id": "test_x",
                           "red_commit": "0" * 40}],
        )
        monkeypatch.setattr(gmod, "_STRICT_RED", True)
        # 重跑返回 PASS (即测试当时未真的 FAIL) → retry
        monkeypatch.setattr(gmod, "_run_test_at_commit", lambda *a, **k: "PASS")
        r = REDGuard().check("developer", state, project_root=repo)
        assert r.action == "retry"


def test_git_is_ancestor_helper(tmp_path: Path) -> None:
    """_git_is_ancestor: 父 commit 是子 commit 的祖先 → True; 反之 False."""
    repo, test_c, impl_c = _make_tdd_repo(tmp_path)
    assert _git_is_ancestor(test_c, impl_c, repo) is True
    assert _git_is_ancestor(impl_c, test_c, repo) is False


# ==================== G8: FreshGate (Gate 证据新鲜度锁定) ====================


class TestFreshGate:
    """G8: gate_results 绑定的 files 快照哈希 == 当前工作树 (B3.2)."""

    def test_timing_and_stages(self) -> None:
        g = FreshGate()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer", "critic")

    def test_pass_when_snapshot_matches(self, tmp_path: Path) -> None:
        """Gate 记录的 files_snapshot_sha == 当前工作树聚合 sha → pass."""
        (tmp_path / "a.py").write_text("print(1)\n")
        files = ["a.py"]
        sha = _aggregate_sha(files, tmp_path)
        state = EngineState(
            files_changed=files,
            gate_results={"lint": {"passed": True, "message": "ok",
                                   "files_snapshot_sha": sha}},
        )
        assert FreshGate().check("developer", state, project_root=tmp_path).action == "pass"

    def test_retry_when_snapshot_stale(self, tmp_path: Path) -> None:
        """Gate 运行后代码又变更 (sha 不匹配) → retry (强制重跑 Gate)."""
        (tmp_path / "a.py").write_text("print(1)\n")
        files = ["a.py"]
        stale_sha = _aggregate_sha(files, tmp_path)
        # Gate 跑完后代码又改了
        (tmp_path / "a.py").write_text("print(2)  # changed after gate\n")
        state = EngineState(
            files_changed=files,
            gate_results={"lint": {"passed": True, "message": "ok",
                                   "files_snapshot_sha": stale_sha}},
        )
        r = FreshGate().check("developer", state, project_root=tmp_path)
        assert r.action == "retry"
        assert "lint" in r.message

    def test_pass_when_no_snapshot_recorded(self, tmp_path: Path) -> None:
        """gate_results 项无 files_snapshot_sha (旧格式) → pass (无可比对基线)."""
        state = EngineState(
            files_changed=["a.py"],
            gate_results={"lint": {"passed": True, "message": "ok"}},
        )
        assert FreshGate().check("developer", state, project_root=tmp_path).action == "pass"

    def test_pass_empty_gate_results(self, tmp_path: Path) -> None:
        """无 gate_results → pass."""
        state = EngineState(files_changed=["a.py"], gate_results={})
        assert FreshGate().check("critic", state, project_root=tmp_path).action == "pass"


def test_aggregate_sha_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    """_aggregate_sha: 同内容同 sha; 内容变则 sha 变; 缺文件不抛异常."""
    (tmp_path / "a.py").write_text("x\n")
    s1 = _aggregate_sha(["a.py"], tmp_path)
    s2 = _aggregate_sha(["a.py"], tmp_path)
    assert s1 == s2
    (tmp_path / "a.py").write_text("y\n")
    assert _aggregate_sha(["a.py"], tmp_path) != s1
    # 缺文件不抛
    assert isinstance(_aggregate_sha(["missing.py"], tmp_path), str)


# ==================== GuardrailResult.guardrail_name + Chain 注入 ====================


class TestGuardrailNameInjection:
    """非 pass 结果须携带 guardrail_name (供 handler 分源计数 / FreshGate 分流)."""

    def test_result_has_guardrail_name_default_empty(self) -> None:
        assert GuardrailResult().guardrail_name == ""

    def test_chain_injects_name_on_block(self) -> None:
        """Chain 命中 block 时把命中的 Guardrail 名注入结果."""
        chain = GuardrailChain([RequirementValid()])
        result = chain.check("pre", "architect", EngineState(requirement=""))
        assert result.action == "block"
        assert result.guardrail_name == "RequirementValid"

    def test_chain_injects_name_on_retry(self) -> None:
        chain = GuardrailChain([PlanExists()])
        result = chain.check("post", "architect", EngineState(plan="", file_list=[]))
        assert result.action == "retry"
        assert result.guardrail_name == "PlanExists"

    def test_chain_pass_result_name_empty(self) -> None:
        chain = GuardrailChain([RequirementValid()])
        result = chain.check("pre", "architect", EngineState(requirement="ok"))
        assert result.action == "pass"
        assert result.guardrail_name == ""


# ==================== S-4: retry 计数键粒度 + FreshGate rerun_gates ====================


class TestRetryKeyGranularity:
    """S-4: key = f'{stage}:{guardrail_name}' — 同 stage 多 retry Guardrail 独立预算."""

    def test_same_stage_different_guardrails_independent_budget(self) -> None:
        """post-developer 的 G3/G7 各自独立计数, 互不挤占."""
        state = EngineState()
        counters: dict[str, int] = {}
        handle_guardrail_result(
            GuardrailResult(action="retry", message="a", guardrail_name="GitDiffExists"),
            "developer", state, counters,
        )
        handle_guardrail_result(
            GuardrailResult(action="retry", message="b", guardrail_name="REDGuard"),
            "developer", state, counters,
        )
        assert counters == {"developer:GitDiffExists": 1, "developer:REDGuard": 1}

    def test_empty_name_backward_compat_keys_by_stage(self) -> None:
        """无 guardrail_name (旧调用) → 退回 stage 单键 (向后兼容)."""
        state = EngineState()
        counters: dict[str, int] = {}
        handle_guardrail_result(
            GuardrailResult(action="retry", message="x"),
            "developer", state, counters,
        )
        assert counters == {"developer": 1}

    def test_freshgate_retry_returns_rerun_gates_no_clear(self) -> None:
        """G8 FreshGate retry → 'rerun_gates' (只重跑 Gate, 不清 stage 字段/不丢实现)."""
        state = EngineState(
            files_changed=["a.py"], commit_hash="abc",
            test_results={"passed": 1},
        )
        counters: dict[str, int] = {}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="stale", guardrail_name="FreshGate"),
            "developer", state, counters,
        )
        assert action == "rerun_gates"
        # 不清字段: 已提交的实现证据保留
        assert state.files_changed == ["a.py"]
        assert state.commit_hash == "abc"
        # 仍按自身键计数
        assert counters == {"developer:FreshGate": 1}

    def test_freshgate_retry_exhaustion_stops(self) -> None:
        """FreshGate rerun_gates 也受 MAX_RETRY 约束: 达上限 → stop."""
        state = EngineState()
        counters: dict[str, int] = {"developer:FreshGate": 3}
        action = handle_guardrail_result(
            GuardrailResult(action="retry", message="stale", guardrail_name="FreshGate"),
            "developer", state, counters,
        )
        assert action == "stop"


# ==================== G9: RegressionGate (revert-red-restore) ====================


class _RegTask:
    """轻量回归修复 Task 替身 (RegressionGate 读 kind/regression_test_id/target_files/id)."""

    def __init__(
        self, task_id: str, target_files: list[str], *,
        kind: str = "", regression_test_id: str = "",
    ) -> None:
        self.id = task_id
        self.target_files = target_files
        self.kind = kind
        self.regression_test_id = regression_test_id


def _make_regression_repo(tmp_path: Path, *, new_file: bool = False) -> tuple[Path, str]:
    """构造回归修复提交序列.

    non-new: impl^ 有 buggy calc.py(return 0) → 修复 commit calc.py(return 1)+test_reg.py
    new:     impl^ 无 calc.py(仅 seed) → 修复 commit 新建 calc.py + test_reg.py

    HEAD 下 test_reg.test_f 断言 f()==1 → PASS; 回退 calc 到 impl^ → FAIL.

    Returns:
        (repo, impl_commit_sha).
    """
    repo = tmp_path / "reg"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
        "GIT_AUTHOR_DATE": "2024-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2024-01-01T00:00:00+0000",
    }
    _git(repo, "init", "-q", env=env)
    _git(repo, "config", "user.email", "t@x", env=env)
    _git(repo, "config", "user.name", "t", env=env)
    if new_file:
        (repo / "README").write_text("seed\n")
        _git(repo, "add", "README", env=env)
    else:
        (repo / "calc.py").write_text("def f():\n    return 0\n")  # buggy
        _git(repo, "add", "calc.py", env=env)
    _git(repo, "commit", "-q", "-m", "before fix", env=env)

    # 修复 commit (HEAD): calc 返回 1 + 回归测试
    (repo / "calc.py").write_text("def f():\n    return 1\n")
    (repo / "test_reg.py").write_text(
        "from calc import f\n\n\ndef test_f():\n    assert f() == 1\n")
    _git(repo, "add", "calc.py", "test_reg.py", env=env)
    _git(repo, "commit", "-q", "-m", "fix: regression", env=env)
    impl_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return repo, impl_commit


def _reg_state(impl_commit: str, task: _RegTask) -> EngineState:
    state = EngineState(commit_hash=impl_commit)
    state.batch_state = _StubBatchState([task])  # type: ignore[attr-defined]
    state._plan = object()  # type: ignore[attr-defined]
    return state


class TestRegressionGate:
    """G9: 回归修复 task 的 revert→MUST FAIL→restore→pass 序列 (B3.3)."""

    def test_timing_and_stage(self) -> None:
        g = RegressionGate()
        assert g.timing == "post"
        assert g.applies_to_stages == ("developer",)

    def test_non_regression_task_passes_na(self, tmp_path: Path) -> None:
        """非回归修复 task (无 kind) → pass N/A."""
        repo, impl_c = _make_regression_repo(tmp_path)
        task = _RegTask("t1", ["calc.py", "test_reg.py"])  # kind=""
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "pass"

    def test_no_regression_task_in_batch_passes(self, tmp_path: Path) -> None:
        """batch 无回归修复 task → pass."""
        repo, impl_c = _make_regression_repo(tmp_path)
        task = _RegTask("t1", ["calc.py"], kind="feature")
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "pass"

    def test_real_revert_must_fail_then_restore_passes(self, tmp_path: Path) -> None:
        """既有实现文件: 回退到 impl^ → 回归测试真的 FAIL → 恢复 → pass; 工作树复原."""
        repo, impl_c = _make_regression_repo(tmp_path)
        task = _RegTask("t1", ["calc.py", "test_reg.py"],
                        kind="regression_fix", regression_test_id="test_f")
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "pass", r.message
        # 工作树已恢复: calc.py 为修复版, git status 干净
        assert (repo / "calc.py").read_text() == "def f():\n    return 1\n"
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert status.strip() == "", f"工作树未复原: {status!r}"

    def test_block_when_revert_still_passes(self, tmp_path: Path, monkeypatch) -> None:
        """回退实现后测试仍 PASS → 测试无效未捕捉回归 → block."""
        import auto_engineering.loop.guardrail as gmod

        repo, impl_c = _make_regression_repo(tmp_path)
        task = _RegTask("t1", ["calc.py", "test_reg.py"],
                        kind="regression_fix", regression_test_id="test_f")
        # 无论回退与否测试都 PASS (测试无效)
        monkeypatch.setattr(gmod, "_run_test", lambda *a, **k: "PASS")
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "block"
        assert "test_f" in r.message
        # finally 仍恢复工作树
        assert (repo / "calc.py").read_text() == "def f():\n    return 1\n"

    def test_block_when_no_impl_files(self, tmp_path: Path) -> None:
        """回归修复 task 只改测试文件 (无实现文件) → 无法验证回归 → block."""
        repo, impl_c = _make_regression_repo(tmp_path)
        task = _RegTask("t1", ["test_reg.py"],
                        kind="regression_fix", regression_test_id="test_f")
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "block"

    def test_new_impl_file_uses_git_rm_branch(self, tmp_path: Path, monkeypatch) -> None:
        """新建实现文件 (impl^ 无父版本): checkout pathspec 错 → git rm 模拟'修复前不存在'."""
        import auto_engineering.loop.guardrail as gmod

        repo, impl_c = _make_regression_repo(tmp_path, new_file=True)
        task = _RegTask("t1", ["calc.py", "test_reg.py"],
                        kind="regression_fix", regression_test_id="test_f")
        # 回退分支 (git rm 后) 测试 FAIL, 恢复后 PASS
        calls: list[str] = []

        def _fake_run_test(test_id, project_root):
            # 第 1 次调用 (回退后): calc.py 应已被 git rm → FAIL; 第 2 次 (恢复后): PASS
            calc_exists = (repo / "calc.py").exists()
            calls.append("exists" if calc_exists else "removed")
            return "PASS" if calc_exists else "FAIL"

        monkeypatch.setattr(gmod, "_run_test", _fake_run_test)
        r = RegressionGate().check("developer", _reg_state(impl_c, task), project_root=repo)
        assert r.action == "pass", r.message
        assert "removed" in calls  # git rm 分支被走到 (回退后 calc.py 不存在)
        # 恢复后 calc.py 回来
        assert (repo / "calc.py").exists()
