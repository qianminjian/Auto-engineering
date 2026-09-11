"""从 Release 包验证 Codex 最小运行链路。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from scripts.build_release import build_archive

ROOT = Path(__file__).parents[1]


def test_codex_release_minimal_tick_chain(tmp_path: Path) -> None:
    archive = build_archive(ROOT, tmp_path / "release.tar.gz")
    install_root = tmp_path / "plugin"
    install_root.mkdir()
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(install_root, filter="data")

    manifest = json.loads(
        (install_root / ".codex-plugin" / "plugin.json").read_text()
    )
    for key in ("hooks", "skills"):
        assert (install_root / manifest[key]).exists()

    environment = os.environ.copy()
    environment.update({
        "CODEX_THREAD_ID": "integration-thread",
        "PLUGIN_ROOT": str(install_root),
        "PYTHONPATH": str(install_root),
    })

    detection = subprocess.run(
        [
            sys.executable,
            "-c",
            "from auto_engineering.host import detect_host;"
            "print(detect_host().platform)",
        ],
        cwd=install_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert detection.returncode == 0, detection.stderr
    assert detection.stdout.strip() == "codex"

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    for path in install_root.rglob("*"):
        path.chmod(path.stat().st_mode & ~0o222)
    assert all(path.stat().st_mode & 0o222 == 0 for path in install_root.rglob("*"))

    hook_payload = json.dumps({
        "hook_event_name": "SessionStart",
        "cwd": str(project),
        "session_id": "integration-session",
    })
    hook = subprocess.run(
        [str(install_root / "hooks" / "codex-hook.sh")],
        cwd=project,
        env=environment,
        input=hook_payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert hook.returncode == 0, hook.stderr
    assert "安全跳过" in json.loads(hook.stdout)["systemMessage"]

    blocked_hook = subprocess.run(
        [str(install_root / "hooks" / "codex-hook.sh")],
        cwd=project,
        env=environment,
        input=json.dumps({
            "hook_event_name": "PreToolUse",
            "cwd": str(project),
            "session_id": "integration-session",
            "tool_name": "Bash",
            "tool_input": {"command": "printf blocked > .ae-state/events.db"},
        }),
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked_hook.returncode == 0, blocked_hook.stderr
    blocked_payload = json.loads(blocked_hook.stdout)
    assert set(blocked_payload) == {"systemMessage", "hookSpecificOutput"}
    assert blocked_payload["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": blocked_payload["systemMessage"],
    }

    tick = subprocess.run(
        [
            str(install_root / "scripts" / "ae-run"),
            "dev-loop",
            "Codex release integration",
            "--init",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert tick.returncode == 0, tick.stderr
    actions = [
        json.loads(line)
        for line in tick.stdout.splitlines()
        if line.startswith("{") and line.endswith("}")
    ]
    assert actions
    assert actions[-1]["action"] in {
        "gap_scan",
        "architect",
            "developer",
            "gate",
            "project_setup_required",
        }
    assert actions[-1]["thread_id"]
