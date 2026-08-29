"""浏览器 E2E 能力预检：只读、确定性、不会下载或启动浏览器。"""

from pathlib import Path

from auto_engineering.project_profile.providers import (
    LocalProbeProvider,
    detect_browser_capability,
)


def test_browser_preflight_reports_alternative_system_runtime(tmp_path: Path) -> None:
    result = detect_browser_capability(
        tmp_path,
        command=("npm", "run", "e2e"),
        which=lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
    )

    assert result["declared"] is True
    assert result["status"] == "available"
    assert result["providers"] == ["system_chrome"]
    assert result["reason_code"] is None


def test_browser_preflight_distinguishes_missing_runtime(tmp_path: Path) -> None:
    result = detect_browser_capability(
        tmp_path,
        command=("pnpm", "run", "e2e"),
        which=lambda _name: None,
        gui_candidates=(),
    )

    assert result == {
        "declared": True,
        "status": "missing",
        "providers": [],
        "executable_count": 0,
        "reason_code": "BROWSER_RUNTIME_MISSING",
    }


def test_local_probe_declares_browser_e2e_without_treating_it_as_unit_test(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest run","e2e":"playwright test"}}',
        encoding="utf-8",
    )

    contribution = LocalProbeProvider().inspect(tmp_path)

    assert contribution.commands["test"] == ("npm", "run", "test")
    assert contribution.commands["browser_e2e"] == ("npm", "run", "e2e")
