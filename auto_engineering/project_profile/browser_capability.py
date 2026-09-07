"""浏览器 E2E 运行时的只读能力预检。"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path


def detect_browser_capability(
    project_root: Path,
    *,
    command: tuple[str, ...] | None,
    which: Callable[[str], str | None] = shutil.which,
    gui_candidates: tuple[tuple[Path, str], ...] | None = None,
) -> dict[str, object]:
    """无副作用预检 E2E 可用的浏览器运行时。

    只在项目声明 ``browser_e2e`` 命令时启用；不下载驱动、不启动浏览器。
    返回可审计的替代能力，避免把“Playwright 包存在但浏览器未安装”误报为
    产品失败。
    """

    if command is None:
        return {"declared": False, "status": "not_declared", "providers": []}

    providers: list[str] = []
    executables: list[str] = []
    for name, provider in (
        ("google-chrome", "system_chrome"),
        ("chromium", "system_chromium"),
        ("chromium-browser", "system_chromium"),
        ("chrome", "system_chrome"),
    ):
        try:
            resolved = which(name)
        except OSError:
            resolved = None
        if resolved:
            providers.append(provider)
            executables.append(str(resolved))

    for candidate, provider in (
        (project_root / "node_modules/.bin/playwright", "playwright_driver"),
        (project_root / "node_modules/.bin/cypress", "cypress_driver"),
    ):
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            providers.append(provider)
            executables.append(candidate.relative_to(project_root).as_posix())

    # macOS GUI 安装的 Chrome 不一定注册在 PATH 中。
    if gui_candidates is None:
        gui_candidates = (
            (
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                "system_chrome",
            ),
            (
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
                "system_chromium",
            ),
        )
    for candidate, provider in gui_candidates:
        if candidate.is_file():
            providers.append(provider)
            executables.append(str(candidate))

    unique_providers = sorted(set(providers))
    return {
        "declared": True,
        "status": "available" if unique_providers else "missing",
        "providers": unique_providers,
        "executable_count": len(set(executables)),
        "reason_code": None if unique_providers else "BROWSER_RUNTIME_MISSING",
    }


__all__ = ["detect_browser_capability"]
