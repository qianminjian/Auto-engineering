"""test_pr_backend.py — T10c: PR 后端抽象层 (B13.9 #8 / B14).

覆盖 PRBackend ABC + GitHubBackend(gh) + GitLabBackend(glab):
  - ci_platform 驱动后端选型 (github/gitlab/none-auto-detect)
  - create_pr 命令参数构造 (gh pr create / glab mr create)
  - 后端不可用 / 非零退出 → PRResult 错误 (不硬编码 gh, 不静默假成功)
  - available_backends 供 doctor 预检

注入 fake runner + monkeypatch shutil.which → 不跑真实 gh/glab/网络.
"""

from __future__ import annotations

from types import SimpleNamespace

from auto_engineering.tools import pr_backend as prb


def _ok_runner(captured: list):
    def run(args, cwd=None, timeout=60):
        captured.append({"args": args, "cwd": cwd})
        return SimpleNamespace(returncode=0, stdout="https://pr/url\n", stderr="")
    return run


def _fail_runner(args, cwd=None, timeout=60):
    return SimpleNamespace(returncode=1, stdout="", stderr="boom\n")


def _which_only(monkeypatch, present: set[str]) -> None:
    monkeypatch.setattr(
        prb.shutil, "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in present else None,
    )


class TestSelection:
    def test_select_github_by_platform(self) -> None:
        b = prb.select_backend("github")
        assert isinstance(b, prb.GitHubBackend)

    def test_select_gitlab_by_platform(self) -> None:
        b = prb.select_backend("gitlab")
        assert isinstance(b, prb.GitLabBackend)

    def test_none_auto_detect_prefers_available(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"glab"})  # 只有 glab 可用
        b = prb.select_backend("none")
        assert isinstance(b, prb.GitLabBackend)

    def test_none_auto_detect_prefers_github_first(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"gh", "glab"})  # 两者都在 → 优先 github
        b = prb.select_backend(None)
        assert isinstance(b, prb.GitHubBackend)

    def test_select_returns_none_when_no_cli(self, monkeypatch) -> None:
        _which_only(monkeypatch, set())
        assert prb.select_backend(None) is None


class TestCreatePR:
    def test_github_builds_gh_args(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"gh"})
        captured: list = []
        backend = prb.GitHubBackend(runner=_ok_runner(captured))
        res = backend.create_pr(title="T", body="B", base="main", head="feat/x")
        assert res.success
        assert res.url == "https://pr/url"
        args = captured[0]["args"]
        assert args[:3] == ["gh", "pr", "create"]
        assert "--title" in args and "T" in args
        assert "--body" in args and "B" in args
        assert "--base" in args and "main" in args
        assert "--head" in args and "feat/x" in args

    def test_gitlab_builds_glab_args(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"glab"})
        captured: list = []
        backend = prb.GitLabBackend(runner=_ok_runner(captured))
        res = backend.create_pr(title="T", body="B", base="main", head="feat/x")
        assert res.success
        args = captured[0]["args"]
        assert args[:3] == ["glab", "mr", "create"]
        assert "--title" in args
        assert "--description" in args
        assert "--target-branch" in args and "main" in args
        assert "--source-branch" in args and "feat/x" in args

    def test_unavailable_returns_error(self, monkeypatch) -> None:
        _which_only(monkeypatch, set())  # gh 不在 PATH
        backend = prb.GitHubBackend(runner=_ok_runner([]))
        res = backend.create_pr(title="T", body="B")
        assert not res.success
        assert "gh" in res.error

    def test_nonzero_exit_returns_error(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"gh"})
        backend = prb.GitHubBackend(runner=_fail_runner)
        res = backend.create_pr(title="T", body="B")
        assert not res.success
        assert "boom" in res.error


class TestDoctorPreflight:
    def test_available_backends_lists_present(self, monkeypatch) -> None:
        _which_only(monkeypatch, {"gh"})
        assert prb.available_backends() == ["github"]

    def test_available_backends_empty_when_none(self, monkeypatch) -> None:
        _which_only(monkeypatch, set())
        assert prb.available_backends() == []


class TestDoctorWiring:
    def test_doctor_includes_pr_backend_line(self, tmp_path) -> None:
        """doctor 有 PR 后端检查行 (B13.9 #8), 非致命 (ok=True)."""
        from auto_engineering.cli.doctor import run_doctor_checks

        _, results = run_doctor_checks(tmp_path)
        pr_lines = [(ok, line) for ok, line in results if "PR 后端" in line]
        assert pr_lines, "doctor 应含 'PR 后端' 检查行"
        assert pr_lines[0][0] is True, "PR 后端检查应为非致命 (ok=True)"

