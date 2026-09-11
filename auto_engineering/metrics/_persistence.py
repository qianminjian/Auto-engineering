"""_MetricsPersistence — 度量派生物持久化。

这里只保存 summary、metadata 和 baseline 等可从 EventStore 重建的结果；
不保存事件、不提供恢复事件流的 API。
"""
import json
import logging
from pathlib import Path

from auto_engineering.utils.file_utils import safe_json_load

_logger = logging.getLogger(__name__)


class _MetricsPersistence:
    """度量派生物持久化 — 摘要/元数据文件读写.

    无状态: 所有方法接收 metrics_dir / thread_id 作为参数.
    """

    def write_summary(self, summary: dict | None, metrics_dir: Path,
                      thread_id: str, category: str = "") -> None:
        """Write M1-M5 summary.json and category metadata.json."""
        req_dir = metrics_dir / "requirements" / thread_id
        req_dir.mkdir(parents=True, exist_ok=True)
        if summary is not None:
            summary_path = req_dir / "summary.json"
            summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        if category:
            meta_path = req_dir / "metadata.json"
            meta_path.write_text(json.dumps(
                {"category": category}, indent=2, ensure_ascii=False))

    def load_history(self, metrics_dir: Path, limit: int = 10) -> list[dict]:
        """Load recent summary.json files from past requirements for trend analysis.

        Scans requirements/*/summary.json in the metrics directory, sorts by
        modification time, and returns the most recent *limit* summaries.
        """
        req_dir = metrics_dir / "requirements"
        if not req_dir.exists():
            return []
        summaries: list[dict] = []
        for summary_path in sorted(
            req_dir.glob("*/summary.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]:
            data = safe_json_load(summary_path)
            if isinstance(data, dict):
                summaries.append(data)
            else:
                _logger.debug("metrics summary read failed: %s", summary_path)
        return summaries
