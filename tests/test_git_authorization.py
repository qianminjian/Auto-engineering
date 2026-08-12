"""Git 能力、用户授权与 checkpoint 边界契约。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrail import GitDiffExists, GuardrailChain

ROOT = Path(__file__).parents[1]
CODE_REVIEW = ROOT / "commands" / "code-review.md"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "tracked.txt").write_text("before\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "initial")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "clean baseline")
    return repo


def test_git_authorization_requires_capability_and_explicit_operation() -> None:
    from auto_engineering.host import GitAuthorization, GitOperation

    unavailable = GitAuthorization(capability=False)
    unapproved = GitAuthorization(capability=True)
    commit_only = GitAuthorization(
        capability=True,
        authorized=frozenset({GitOperation.COMMIT}),
    )

    assert unavailable.allows(GitOperation.COMMIT) is False
    assert unapproved.allows(GitOperation.COMMIT) is False
    assert commit_only.allows(GitOperation.COMMIT) is True
    assert commit_only.allows(GitOperation.PUSH) is False
    assert commit_only.allows(GitOperation.CREATE_PR) is False


def test_uncommitted_tracked_change_satisfies_developer_diff_guardrail(
    tmp_path: Path,
) -> None:
    repo = _committed_repo(tmp_path)
    (repo / "tracked.txt").write_text("after\n")

    result = GitDiffExists().check(
        "developer",
        EngineState(),
        project_root=repo,
    )

    assert result.action == "pass"


def test_declared_untracked_file_satisfies_developer_diff_guardrail(
    tmp_path: Path,
) -> None:
    repo = _committed_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "new.py").write_text("VALUE = 1\n")

    result = GitDiffExists().check(
        "developer",
        EngineState(files_changed=["src/new.py"]),
        project_root=repo,
    )

    assert result.action == "pass"


def test_unrelated_untracked_file_is_not_developer_evidence(tmp_path: Path) -> None:
    repo = _committed_repo(tmp_path)
    (repo / "unrelated.txt").write_text("not this batch\n")

    result = GitDiffExists().check(
        "developer",
        EngineState(files_changed=["src/expected.py"]),
        project_root=repo,
    )

    assert result.action == "retry"


def test_declared_real_file_is_evidence_without_git_repository(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "new.py").write_text("VALUE = 1\n")

    result = GitDiffExists().check(
        "developer",
        EngineState(files_changed=["src/new.py"]),
        project_root=tmp_path,
    )

    assert result.action == "pass"


def test_default_guardrails_do_not_require_git_commit() -> None:
    names = [guardrail.name for guardrail in GuardrailChain.default().guardrails]

    assert "GitClean" not in names
    assert "GitDiffExists" in names


def test_code_review_requires_current_user_authorization_before_mutation() -> None:
    content = CODE_REVIEW.read_text()
    authorization = content.index("CURRENT_USER_GIT_AUTHORIZATION_REQUIRED")
    push = content.index("git push")
    create_pr = content.index("gh pr create")

    assert authorization < push
    assert authorization < create_pr
    assert "不得从历史消息、宿主能力或 loop 完成状态推断授权" in content


def test_checkpoint_is_the_loop_boundary_without_git_mutation() -> None:
    content = (ROOT / "skills" / "auto-engineering" / "SKILL.md").read_text()

    assert "checkpoint 是循环恢复边界" in content
    assert "checkpoint 不要求 commit" in content
