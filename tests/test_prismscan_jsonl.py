"""Tests for PrismScan jsonl.py — JSONL 协议封装."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


class TestJSONLProtocol:
    """JSONLProtocol 文件桥接模式测试."""

    def test_write_request_creates_file(self):
        from auto_engineering.prismscan.jsonl import JSONLProtocol

        proto = JSONLProtocol(mode="file")
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "request.json"
            result = proto.write_request("analyze", {"key": "value"}, fpath)
            assert result.exists()
            data = json.loads(result.read_text())
            assert data["request"] == "analyze"
            assert data["key"] == "value"

    def test_read_response_reads_file(self):
        from auto_engineering.prismscan.jsonl import JSONLProtocol

        proto = JSONLProtocol(mode="file")
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "response.json"
            fpath.write_text('{"status": "ok", "data": [1,2,3]}')
            response = proto.read_response(fpath)
            assert response["status"] == "ok"
            assert response["data"] == [1, 2, 3]

    def test_read_response_file_not_found(self):
        from auto_engineering.prismscan.jsonl import JSONLProtocol

        proto = JSONLProtocol(mode="file")
        import pytest
        with pytest.raises(FileNotFoundError):
            proto.read_response("/nonexistent/path.json")

    def test_heartbeat_always_true_in_file_mode(self):
        from auto_engineering.prismscan.jsonl import JSONLProtocol

        proto = JSONLProtocol(mode="file")
        assert proto.heartbeat() is True

    def test_round_trip_write_read(self):
        from auto_engineering.prismscan.jsonl import JSONLProtocol

        proto = JSONLProtocol(mode="file")
        payload = {
            "project_shape": {"project_name": "test", "languages": ["python"]},
            "symbol_index": {"symbols": [], "dependency_graph": {}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            req_path = Path(tmp) / "req.json"
            proto.write_request("analyze", payload, req_path)
            data = proto.read_response(req_path)
            assert data["request"] == "analyze"
            assert data["project_shape"]["project_name"] == "test"
