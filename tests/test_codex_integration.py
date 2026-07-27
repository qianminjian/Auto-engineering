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

    venv_bin = install_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)
    (venv_bin / "ae").symlink_to(ROOT / ".venv" / "bin" / "ae")

    environment = os.environ.copy()
    environment.update({
        "CODEX_THREAD_ID": "integration-thread",
        "PLUGIN_ROOT": str(install_root),
        "PYTHONPATH": str(install_root),
        "AE_SKIP_CONFIG_CHECK": "1",
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

    hook_payload = json.dumps({
        "hook_event_name": "SessionStart",
        "cwd": str(install_root),
        "session_id": "integration-session",
    })
    hook = subprocess.run(
        [str(install_root / "hooks" / "codex-hook.sh")],
        cwd=install_root,
        env=environment,
        input=hook_payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert hook.returncode == 0, hook.stderr
    assert hook.stdout == ""

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    tick = subprocess.run(
        [
            str(install_root / "scripts" / "ae-run"),
            "dev-loop",
            "Codex release integration",
            "--init",
            "--max-rounds",
            "1",
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
    }
    assert actions[-1]["thread_id"]
