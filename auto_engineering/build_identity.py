"""内容寻址的 Engine Build Identity。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from auto_engineering import __version__

_BUILD_INFO = "build-info.json"
_IGNORED_PARTS = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
})


def validate_build_info(payload: object) -> dict[str, str]:
    """校验并返回所有入口共用的 Release Build Identity。"""

    version = payload.get("version") if isinstance(payload, Mapping) else None
    build_id = payload.get("build_id") if isinstance(payload, Mapping) else None
    content_sha256 = (
        payload.get("content_sha256") if isinstance(payload, Mapping) else None
    )
    if (
        not isinstance(version, str)
        or not version
        or not isinstance(build_id, str)
        or not build_id.startswith(f"{version}+sha256.")
        or not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(char not in "0123456789abcdef" for char in content_sha256)
        or not build_id.endswith(content_sha256[:16])
    ):
        raise ValueError("build-info.json 身份无效")
    return {
        "version": version,
        "build_id": build_id,
        "content_sha256": content_sha256,
    }


def _content_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and not any(part in _IGNORED_PARTS for part in path.parts)
        and not path.name.endswith((".pyc", ".pyo"))
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_build_identity(package_root: Path, *, version: str) -> str:
    """为未打包源码生成可复现身份；内容变化必然改变身份。"""
    content_digest = _content_digest(package_root)
    return f"{version}+source.sha256.{content_digest[:16]}"


def _read_packaged_build_identity(package_root: Path) -> str | None:
    path = package_root.parent / _BUILD_INFO
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    build_id = payload.get("build_id")
    version = payload.get("version")
    content_digest = payload.get("content_sha256")
    if (
        isinstance(build_id, str)
        and build_id
        and version == __version__
        and isinstance(content_digest, str)
        and len(content_digest) == 64
        and all(char in "0123456789abcdef" for char in content_digest)
    ):
        return build_id
    return None


@lru_cache(maxsize=1)
def current_build_identity() -> str:
    """返回发布包身份；源码环境使用包内容摘要作为后备。"""
    package_root = Path(__file__).resolve().parent
    packaged = _read_packaged_build_identity(package_root)
    if packaged is not None:
        return packaged
    return source_build_identity(package_root, version=__version__)


__all__ = ["current_build_identity", "source_build_identity", "validate_build_info"]
