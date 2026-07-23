"""file_utils — 安全 JSON 文件读写 (T135a).

统一 24 处 ``json.loads(path.read_text())`` 重复模式，提供一致的错误处理：
- ``safe_json_load(path)`` → 解析成功返回 dict|list，失败返回 None + WARN 日志
- ``safe_json_save(path, data)`` → 原子写入（tmp + os.replace），成功返回 True
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_logger = logging.getLogger("ae.utils.file_utils")


def safe_json_load(path: Path) -> dict | list | None:
    """安全读取 JSON 文件，失败返回 None + WARN。

    替代模式: ``json.loads(path.read_text())`` → ``safe_json_load(path)``
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("Failed to read JSON from %s: %s", path, e)
        return None


def safe_json_save(path: Path, data: dict | list) -> bool:
    """安全写入 JSON 文件（原子：tmp → os.replace）。

    替代模式: ``path.write_text(json.dumps(data))`` → ``safe_json_save(path, data)``
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)
        return True
    except OSError as e:
        _logger.warning("Failed to write JSON to %s: %s", path, e)
        return False
