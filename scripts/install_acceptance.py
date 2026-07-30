"""从 Release 压缩包执行单宿主安装后验收。"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

try:
    from scripts.check_host_package import check_host_package
except ModuleNotFoundError:  # 直接执行解压目录内的脚本
    from check_host_package import check_host_package


_HOST_ENV = {
    "claude-code": ("CLAUDE_CODE", "1"),
    "codex": ("CODEX_THREAD_ID", "release-acceptance"),
}


def _safe_extract_archive(package: tarfile.TarFile, destination: Path) -> None:
    """兼容旧 Python 的安全 tar 解压，拒绝路径穿越和链接成员。"""
    resolved_destination = destination.resolve()
    for member in package.getmembers():
        target = (resolved_destination / member.name).resolve()
        if (
            not target.is_relative_to(resolved_destination)
            or member.issym()
            or member.islnk()
        ):
            raise ValueError(f"不安全的归档路径: {member.name}")
        if "filter" in inspect.signature(package.extract).parameters:
            package.extract(member, resolved_destination, filter="data")
        else:
            package.extract(member, resolved_destination)


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"命令失败 ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def _write_init_manifest(project: Path) -> None:
    state_dir = project / ".ae-state"
    state_dir.mkdir()
    manifest = {
        "schema_version": "1.0",
        "project_type": "app-service",
        "language": "python",
        "structure": {
            "source_root": "src/",
            "test_root": "tests/",
            "config_files": ["pyproject.toml"],
            "entry_point": "src/main.py",
        },
        "conventions": {
            "package_manager": "uv",
            "linter": "ruff",
            "type_checker": "mypy",
            "test_runner": "pytest",
        },
    }
    (state_dir / "init-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _last_json_object(output: str) -> dict[str, object]:
    """提取 CLI 输出中的最后一个 JSON 对象。"""
    objects = [
        json.loads(line)
        for line in output.splitlines()
        if line.startswith("{") and line.endswith("}")
    ]
    if not objects or not isinstance(objects[-1], dict):
        raise RuntimeError("CLI 未返回有效 JSON 对象")
    return objects[-1]


def _verify_checkpoint_lifecycle(
    resolver: str,
    project: Path,
    environment: dict[str, str],
    init_output: str,
) -> list[str]:
    """验证隔离项目的 status 与 thread_id resume 生命周期。"""
    action = _last_json_object(init_output)
    thread_id = action.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise RuntimeError("最小 Tick 未生成有效 thread_id")

    status = _run(
        [
            resolver,
            "dev-loop",
            "--status",
            "--format",
            "json",
            "--project-root",
            str(project),
        ],
        cwd=project,
        env=environment,
    )
    status_payload = _last_json_object(status.stdout)
    if status_payload.get("thread_id") != thread_id:
        raise RuntimeError("status 返回的 thread_id 与初始化结果不一致")

    resumed = _run(
        [
            resolver,
            "dev-loop",
            "--resume",
            thread_id,
            "--project-root",
            str(project),
        ],
        cwd=project,
        env=environment,
    )
    resumed_action = _last_json_object(resumed.stdout)
    if resumed_action.get("thread_id") != thread_id:
        raise RuntimeError("resume 返回的 thread_id 与初始化结果不一致")
    return ["status", "resume"]


def accept_archive(
    archive: Path,
    host: str,
    workspace: Path,
) -> dict[str, object]:
    """执行可自动化的归档 smoke；不冒充真实宿主产品安装。"""
    if host not in _HOST_ENV:
        raise ValueError(f"未知宿主: {host}")

    install_root = workspace / "plugin"
    install_root.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as package:
        _safe_extract_archive(package, install_root)

    errors = check_host_package(install_root, host)
    if errors:
        raise RuntimeError("; ".join(errors))

    environment = os.environ.copy()
    for key in ("CLAUDE_CODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_SANDBOX"):
        environment.pop(key, None)
    host_key, host_value = _HOST_ENV[host]
    environment[host_key] = host_value
    environment["AE_SKIP_CONFIG_CHECK"] = "1"

    _run(["uv", "sync", "--project", str(install_root)], cwd=install_root, env=environment)

    project = workspace / "project"
    project.mkdir()
    _run(["git", "init", "-q"], cwd=project, env=environment)
    _write_init_manifest(project)

    resolver = str(install_root / "bin" / "ae-run")
    doctor = _run(
        [resolver, "doctor", "--project-root", str(project)],
        cwd=project,
        env=environment,
    )
    if "宿主模式已启用" not in doctor.stdout:
        raise RuntimeError("doctor 未识别目标宿主")

    tick = _run(
        [
            resolver,
            "dev-loop",
            f"{host} release acceptance",
            "--init",
            "--max-rounds",
            "1",
        ],
        cwd=project,
        env=environment,
    )
    lifecycle_evidence = _verify_checkpoint_lifecycle(
        resolver,
        project,
        environment,
        tick.stdout,
    )
    generated_config = project / "ae.toml"
    if not generated_config.is_file() or "metrics = \"1\"" not in generated_config.read_text(
        encoding="utf-8"
    ):
        raise RuntimeError("首次启动未生成有效 standard profile")

    return {
        "host": host,
        "archive_smoke": {
            "status": "pass",
            "evidence": [
                "package_contract",
                "isolated_uv_sync",
                "doctor",
                "minimal_tick",
                *lifecycle_evidence,
            ],
        },
        "product_install": {
            "status": "not_run",
            "reason": (
                "自动验收仅模拟宿主信号；"
                "需要在真实 Claude Code 或 Codex 产品内完成安装验收"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--host", choices=sorted(_HOST_ENV), required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix=f"ae-{args.host}-") as temporary:
        report = accept_archive(
            args.archive.resolve(),
            args.host,
            Path(temporary),
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
