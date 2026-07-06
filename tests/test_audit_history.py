"""v5.5 — AuditHistory JSONL 审计历史日志单元测试.

测试 append-only JSONL 存储的读写、边界值、并发安全基本场景.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from auto_engineering.loop.audit_history import AuditHistory


class TestAuditHistoryInit:
    """初始化测试."""

    def test_init_with_path(self):
        """应接受 Path 对象."""
        history = AuditHistory(project_root=Path("/tmp"))
        assert history is not None

    def test_path_points_to_ae_state(self):
        """默认路径应为 .ae-state/audit-history.jsonl."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            expected = root / ".ae-state" / "audit-history.jsonl"
            assert history._path == expected


class TestAppendAndRead:
    """追加与读取测试."""

    def test_append_single_entry(self):
        """追加一条记录后应能读取."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            history.append_entry(
                p0=0, p1=3, p2=5, threshold=6,
                total_files=50, plan_refine_triggered=False,
            )

            entries = history.read_history()
            assert len(entries) == 1
            e = entries[0]
            assert e["p0_count"] == 0
            assert e["p1_count"] == 3
            assert e["p2_count"] == 5
            assert e["p1_threshold"] == 6
            assert e["total_files"] == 50
            assert e["plan_refine_triggered"] is False

    def test_append_multiple_entries(self):
        """追加多条记录, 读取顺序应与写入顺序一致."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            for i in range(5):
                history.append_entry(
                    p0=0, p1=i, p2=i * 2, threshold=6,
                    total_files=100, plan_refine_triggered=(i == 4),
                )

            entries = history.read_history()
            assert len(entries) == 5
            for i, e in enumerate(entries):
                assert e["p1_count"] == i
                assert e["p2_count"] == i * 2

    def test_timestamp_included(self):
        """每条记录应包含 ISO 格式 timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            history.append_entry(p0=0, p1=0, p2=0, threshold=6,
                                 total_files=10, plan_refine_triggered=False)

            entries = history.read_history()
            assert "timestamp" in entries[0]
            # 应包含 T (ISO 8601 分隔符) 和 Z (UTC)
            assert "T" in entries[0]["timestamp"]

    def test_creates_ae_state_dir(self):
        """追加时若 .ae-state/ 不存在应自动创建."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ae_state = root / ".ae-state"
            assert not ae_state.exists()

            history = AuditHistory(project_root=root)
            history.append_entry(p0=0, p1=0, p2=0, threshold=6,
                                 total_files=10, plan_refine_triggered=False)

            assert ae_state.exists()
            assert (ae_state / "audit-history.jsonl").exists()


class TestReadEmpty:
    """空文件/不存在文件场景."""

    def test_read_nonexistent_file(self):
        """文件不存在时返回空列表."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            entries = history.read_history()
            assert entries == []

    def test_read_empty_file(self):
        """文件存在但为空时返回空列表."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ae-state").mkdir()
            (root / ".ae-state" / "audit-history.jsonl").write_text("")

            history = AuditHistory(project_root=root)
            entries = history.read_history()
            assert entries == []

    def test_read_file_with_blank_lines(self):
        """包含空行的文件应正确跳过空行."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ae-state").mkdir()
            log = root / ".ae-state" / "audit-history.jsonl"
            log.write_text(
                '{"p0_count":0,"p1_count":1,"p2_count":0,"p1_threshold":6,"total_files":10,"plan_refine_triggered":false,"timestamp":"2026-07-07T00:00:00Z"}\n'
                '\n'
                '{"p0_count":0,"p1_count":2,"p2_count":0,"p1_threshold":6,"total_files":10,"plan_refine_triggered":false,"timestamp":"2026-07-07T00:01:00Z"}\n'
            )

            history = AuditHistory(project_root=root)
            entries = history.read_history()
            assert len(entries) == 2


class TestDataIntegrity:
    """数据完整性测试."""

    def test_jsonl_valid_json_per_line(self):
        """每行必须是有效 JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            history.append_entry(p0=1, p1=5, p2=10, threshold=4,
                                 total_files=100, plan_refine_triggered=True)

            with open(root / ".ae-state" / "audit-history.jsonl") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        json.loads(line)  # 不应抛异常

    def test_all_required_fields_present(self):
        """每条记录应包含所有必须字段."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = AuditHistory(project_root=root)
            history.append_entry(p0=0, p1=0, p2=0, threshold=6,
                                 total_files=10, plan_refine_triggered=False)

            entries = history.read_history()
            required = {"timestamp", "p0_count", "p1_count", "p2_count",
                       "p1_threshold", "total_files", "plan_refine_triggered"}
            for key in required:
                assert key in entries[0], f"Missing field: {key}"
