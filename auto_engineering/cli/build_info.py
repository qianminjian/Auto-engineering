"""只读输出当前 CLI 实际加载的 Release Build Identity。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from auto_engineering import __version__
from auto_engineering.build_identity import current_build_identity, validate_build_info


def _identity_source() -> str:
    """区分已打包安装和源码运行，避免把源码身份误当成 Release 身份。"""

    build_info_path = Path(__file__).resolve().parents[1].parent / "build-info.json"
    try:
        metadata = validate_build_info(
            json.loads(build_info_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return "source"
    return "packaged" if metadata["version"] == __version__ else "source"


def _packaged_content_sha256() -> str | None:
    """返回已加载 Release 的完整内容摘要，供宿主预检落盘。"""

    build_info_path = Path(__file__).resolve().parents[1].parent / "build-info.json"
    try:
        metadata = validate_build_info(
            json.loads(build_info_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return metadata["content_sha256"]


@click.command("build-info")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json"]),
    default="json",
    show_default=True,
    help="输出格式（当前仅支持 json）。",
)
@click.option(
    "--expect-build-id",
    help="要求当前入口的 Build Identity 与给定值完全一致；不一致则非零退出。",
)
def build_info(output_format: str, expect_build_id: str | None) -> None:
    """输出当前宿主加载的内容寻址 Build Identity，不启动 Loop。"""

    payload: dict[str, Any] = {
        "version": __version__,
        "build_id": current_build_identity(),
        "source_kind": _identity_source(),
    }
    content_sha256 = _packaged_content_sha256()
    if content_sha256 is not None:
        payload["content_sha256"] = content_sha256
    if expect_build_id is not None and payload["build_id"] != expect_build_id:
        raise click.ClickException(
            "Build Identity 不匹配："
            f" expected={expect_build_id} observed={payload['build_id']}"
        )
    if output_format == "json":
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def register_build_info_command(group: click.Group) -> None:
    """将只读 Build Identity 预检命令注册到宿主 CLI。"""

    group.add_command(build_info)


__all__ = ["build_info", "register_build_info_command"]
