"""T110d: SessionTranscriptParser 单元测试.

Covers: encode_cwd, collect (empty/incremental/dedup/subagent), reset, create_parser gating.
"""

import json
from pathlib import Path

from auto_engineering.metrics.transcript_parser import (
    SessionTranscriptParser,
    _encode_cwd,
    create_parser,
)


class TestEncodeCwd:
    def test_encode_simple_path(self):
        result = _encode_cwd("/Users/test/project")
        assert result == "Users-test-project"

    def test_encode_no_leading_slash(self):
        result = _encode_cwd("home/user/project")
        assert result == "home-user-project"

    def test_encode_single_dir(self):
        result = _encode_cwd("/tmp")
        assert result == "tmp"


class TestSessionTranscriptParserCollect:
    """Tests for collect() with various JSONL scenarios."""

    def test_collect_empty_when_no_session_dir(self, tmp_path):
        parser = SessionTranscriptParser(tmp_path / "nonexistent")
        result = parser.collect()
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["model"] == "unknown"
        assert result["message_count"] == 0
        assert result["source"] == "transcript"

    def test_collect_empty_when_no_jsonl_files(self, tmp_path, monkeypatch):
        """Session dir exists but has no .jsonl files."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        parser = SessionTranscriptParser(tmp_path)
        result = parser.collect()
        assert result["input_tokens"] == 0
        assert result["message_count"] == 0

    def test_collect_parses_assistant_with_usage(self, tmp_path, monkeypatch):
        """Parse assistant lines with usage blocks."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        jsonl_content = json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 500, "output_tokens": 200},
            },
        }) + "\n"

        jsonl_file = session_dir / "session.jsonl"
        jsonl_file.write_text(jsonl_content)

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        result = parser.collect()
        assert result["input_tokens"] == 500
        assert result["output_tokens"] == 200
        assert "claude-sonnet-4-6" in result["model"]
        assert result["message_count"] == 1

    def test_collect_preserves_cache_read_and_write_usage(self, tmp_path, monkeypatch):
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)
        jsonl_file = session_dir / "cache-session.jsonl"
        jsonl_file.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "id": "cache-1",
                "model": "claude",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 300,
                    "cache_creation_input_tokens": 40,
                },
            },
        }) + "\n")
        monkeypatch.setattr(
            SessionTranscriptParser,
            "_find_latest_session",
            lambda self: jsonl_file,
        )

        result = SessionTranscriptParser(tmp_path).collect()

        assert result["cache_read_tokens"] == 300
        assert result["cache_write_tokens"] == 40

    def test_collect_skips_non_assistant(self, tmp_path, monkeypatch):
        """Only type=='assistant' lines are parsed."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        lines = [
            {"type": "system", "message": {"id": "s1", "usage": {"input_tokens": 10}}},
            {"type": "user", "message": {"id": "u1", "usage": {"input_tokens": 20}}},
            {"type": "assistant", "message": {"id": "a1", "model": "claude", "usage": {"input_tokens": 30, "output_tokens": 10}}},  # noqa: E501
        ]
        jsonl_file = session_dir / "session.jsonl"
        jsonl_file.write_text("\n".join(json.dumps(l) for l in lines) + "\n")  # noqa: E741

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        result = parser.collect()
        assert result["input_tokens"] == 30
        assert result["output_tokens"] == 10
        assert result["message_count"] == 1

    def test_collect_deduplicates_by_message_id(self, tmp_path, monkeypatch):
        """Same message.id across calls is only counted once."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        jsonl_file = session_dir / "session.jsonl"
        jsonl_file.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "model": "claude",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }) + "\n")

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        r1 = parser.collect()
        assert r1["input_tokens"] == 100

        # Second call — same file, same msg id, should be deduped
        r2 = parser.collect()
        assert r2["input_tokens"] == 0
        assert r2["message_count"] == 0

    def test_collect_incremental(self, tmp_path, monkeypatch):
        """Second call with new lines reads only new data."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        jsonl_file = session_dir / "session.jsonl"
        initial = json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "model": "claude",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }) + "\n"
        jsonl_file.write_text(initial)

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        r1 = parser.collect()
        assert r1["input_tokens"] == 100

        # Append new line
        new_line = json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_002",
                "model": "claude",
                "usage": {"input_tokens": 200, "output_tokens": 80},
            },
        }) + "\n"
        with open(jsonl_file, "a") as f:
            f.write(new_line)

        r2 = parser.collect()
        assert r2["input_tokens"] == 200
        assert r2["output_tokens"] == 80
        assert r2["message_count"] == 1

    def test_collect_handles_malformed_jsonl(self, tmp_path, monkeypatch):
        """Malformed JSON lines are silently skipped."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        lines = [
            "not valid json",
            json.dumps({"type": "assistant", "message": {"id": "ok", "model": "x", "usage": {"input_tokens": 5}}}),
            "",
            "{broken",
        ]
        jsonl_file = session_dir / "session.jsonl"
        jsonl_file.write_text("\n".join(lines) + "\n")

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        result = parser.collect()
        assert result["input_tokens"] == 5
        assert result["message_count"] == 1

    def test_collect_subagent_files(self, tmp_path, monkeypatch):
        """Subagent agent-*.jsonl files are also read."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        subagent_dir = session_dir / "subagents"
        subagent_dir.mkdir(parents=True, exist_ok=True)

        main_file = session_dir / "session.jsonl"
        main_file.write_text("")

        agent_file = subagent_dir / "agent-explore.jsonl"
        agent_file.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "id": "sub_001",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 300, "output_tokens": 120},
            },
        }) + "\n")

        class FakeParser(SessionTranscriptParser):
            def _find_latest_session(self):
                return main_file

        parser = FakeParser(tmp_path)
        result = parser.collect()
        assert result["input_tokens"] == 300
        assert result["output_tokens"] == 120
        assert "claude-haiku-4-5" in result["model"]
        assert result["message_count"] == 1


class TestSessionTranscriptParserReset:
    def test_reset_clears_state(self, tmp_path, monkeypatch):
        """reset() clears offset and seen IDs for a fresh start."""
        encoded = _encode_cwd(str(tmp_path))
        session_dir = Path.home() / ".claude" / "projects" / encoded
        session_dir.mkdir(parents=True, exist_ok=True)

        jsonl_file = session_dir / "session.jsonl"
        jsonl_file.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_001",
                "model": "claude",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }) + "\n")

        def fake_find(self):
            return jsonl_file
        monkeypatch.setattr(
            SessionTranscriptParser, "_find_latest_session", fake_find)

        parser = SessionTranscriptParser(tmp_path)
        r1 = parser.collect()
        assert r1["input_tokens"] == 100

        parser.reset()
        r2 = parser.collect()
        # After reset, same message should be read again
        assert r2["input_tokens"] == 100
        assert r2["message_count"] == 1


class TestCreateParser:
    def test_returns_none_when_ae_metrics_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AE_METRICS", "0")
        monkeypatch.setenv("AE_TOKEN_TRACKING", "1")
        assert create_parser(tmp_path) is None

    def test_returns_none_when_token_tracking_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AE_METRICS", "1")
        monkeypatch.setenv("AE_TOKEN_TRACKING", "0")
        assert create_parser(tmp_path) is None

    def test_returns_none_when_both_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AE_METRICS", "0")
        monkeypatch.setenv("AE_TOKEN_TRACKING", "0")
        assert create_parser(tmp_path) is None

    def test_returns_none_when_env_vars_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AE_METRICS", raising=False)
        monkeypatch.delenv("AE_TOKEN_TRACKING", raising=False)
        assert create_parser(tmp_path) is None

    def test_returns_parser_when_both_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AE_METRICS", "1")
        monkeypatch.setenv("AE_TOKEN_TRACKING", "1")
        monkeypatch.setenv("CLAUDE_CODE", "1")
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        monkeypatch.delenv("CODEX_SANDBOX", raising=False)
        parser = create_parser(tmp_path)
        assert parser is not None
        assert isinstance(parser, SessionTranscriptParser)

    def test_returns_none_for_codex_without_usage_source(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AE_METRICS", "1")
        monkeypatch.setenv("AE_TOKEN_TRACKING", "1")
        monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
        monkeypatch.delenv("CLAUDE_CODE", raising=False)

        assert create_parser(tmp_path) is None
