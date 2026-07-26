"""_MetricsPersistence — 度量持久化 (T117 拆分自 collector.py).

职责: events.jsonl / summary.json / metadata.json 文件读写.
不含聚合计算、事件记录、生命周期管理.
"""
import json
import logging
import os
from pathlib import Path

from auto_engineering.utils.file_utils import safe_json_load

_logger = logging.getLogger(__name__)


class _MetricsPersistence:
    """度量持久化 — 事件/摘要/元数据文件读写.

    无状态: 所有方法接收 metrics_dir / thread_id 作为参数.
    """

    def flush_events(self, events: list[dict], metrics_dir: Path,
                     thread_id: str) -> None:
        """Write events buffer to events.jsonl (atomic overwrite via temp file, P2-41)."""
        req_dir = metrics_dir / "requirements" / thread_id
        req_dir.mkdir(parents=True, exist_ok=True)
        events_path = req_dir / "events.jsonl"
        tmp_path = events_path.with_suffix(".jsonl.tmp")
        with open(tmp_path, "w") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        os.replace(tmp_path, events_path)  # atomic on POSIX

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

    def flush(self, events: list[dict], summary: dict | None,
              metrics_dir: Path, thread_id: str, category: str = "") -> None:
        """Flush events and write summary (convenience, calls flush_events + write_summary)."""
        self.flush_events(events, metrics_dir, thread_id)
        self.write_summary(summary, metrics_dir, thread_id, category)

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

    def read_events_from_disk(self, metrics_dir: Path,
                              thread_id: str) -> list[dict]:
        """Read events.jsonl for cross-process tick continuation.

        Returns the loaded events list (empty if no prior events or read error).
        """
        events_path = metrics_dir / "requirements" / thread_id / "events.jsonl"
        if not events_path.exists():
            return []
        events: list[dict] = []
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            _logger.debug("metrics events read failed: %s", events_path, exc_info=True)
            return []
        return events

    def read_category_from_disk(self, metrics_dir: Path,
                                thread_id: str) -> str:
        """Read category from metadata.json for cross-process continuity (T85).

        Returns category string or empty string if not found.
        """
        meta_path = metrics_dir / "requirements" / thread_id / "metadata.json"
        if not meta_path.exists():
            return ""
        data = safe_json_load(meta_path)
        if isinstance(data, dict):
            return str(data.get("category", ""))
        _logger.debug("metrics metadata read failed: %s", meta_path)
        return ""
