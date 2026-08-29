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


def _write_project_fixture(project: Path) -> None:
    """只写标准工程入口，证明运行时不依赖 Init Engineering manifest。"""
    (project / ".ae-state").mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "acceptance-fixture"\nversion = "0.1.0"\n'
        'requires-python = ">=3.12"\n',
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


def _verify_runtime_semantic_contract(
    install_root: Path,
    environment: dict[str, str],
) -> list[str]:
    """在解压制品内执行身份与设计权威的最小语义契约。"""

    program = (
        "from auto_engineering.host.runtime_identity import ExecutionIdentity;"
        "from auto_engineering.loop.design_authority import DesignAuthorityPolicy;"
        "w=ExecutionIdentity.worker(stage='architect');"
        "p=DesignAuthorityPolicy.default();"
        "assert not w.may_drive_loop and not w.may_spawn_workers;"
        "assert p.authority_for('research').value == 'advisory';"
        "print('semantic-contract-ok')"
    )
    _run(
        ["uv", "run", "--project", str(install_root), "python", "-c", program],
        cwd=install_root,
        env=environment,
    )
    return ["runtime_identity", "design_authority"]


def _hermetic_sync(
    install_root: Path,
    environment: dict[str, str],
    wheel_cache: Path | None,
) -> None:
    """只使用显式受控缓存和锁文件安装，禁止验收时临时联网解析。"""

    if wheel_cache is None or not wheel_cache.is_dir():
        raise RuntimeError("HERMETIC_CACHE_REQUIRED")
    hermetic_env = dict(environment)
    hermetic_env["UV_CACHE_DIR"] = str(wheel_cache.resolve())
    _run(
        [
            "uv", "sync", "--frozen", "--offline",
            "--project", str(install_root),
        ],
        cwd=install_root,
        env=hermetic_env,
    )


def accept_archive(
    archive: Path,
    host: str,
    workspace: Path,
    wheel_cache: Path | None = None,
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

    plugin_root = (install_root / "plugins" / "auto-engineering").resolve()
    if not (plugin_root / "bin" / "ae-run").is_file():
        raise RuntimeError("安装制品缺少嵌套插件入口 plugins/auto-engineering/bin/ae-run")
    _hermetic_sync(plugin_root, environment, wheel_cache)

    project = workspace / "project"
    project.mkdir()
    _run(["git", "init", "-q"], cwd=project, env=environment)
    _write_project_fixture(project)
    if (project / ".ae-state" / "init-manifest.json").exists():
        raise RuntimeError("验收 fixture 不得依赖 init-manifest.json")

    resolver = str(plugin_root / "bin" / "ae-run")
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
    semantic_evidence = _verify_runtime_semantic_contract(
        plugin_root,
        environment,
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
                "manifest_free_project_profile",
                *lifecycle_evidence,
                *semantic_evidence,
            ],
        },
        "product_install": {
            "status": "not_run",
            "evidence_validator": "scripts/product_acceptance.py",
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
    parser.add_argument("--wheel-cache", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix=f"ae-{args.host}-") as temporary:
        report = accept_archive(
            args.archive.resolve(),
            args.host,
            Path(temporary),
            args.wheel_cache,
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
