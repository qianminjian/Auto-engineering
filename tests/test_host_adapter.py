"""Host-neutral 宿主平台与能力契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_detects_codex_before_claude_compatibility_signals() -> None:
    from auto_engineering.host import HostPlatform, detect_host

    detection = detect_host({
        "CODEX_THREAD_ID": "thread-1",
        "CLAUDE_PLUGIN_ROOT": "/compat/path",
        "ANTHROPIC_AUTH_TOKEN": "compat-token",
    })

    assert detection.platform is HostPlatform.CODEX
    assert detection.signal == "CODEX_THREAD_ID"


def test_detects_codebuddy_before_claude_signals() -> None:
    from auto_engineering.host import HostPlatform, detect_host

    detection = detect_host({
        "CODEBUDDY_PLUGIN_ROOT": "/plugin",
        "CLAUDE_CODE": "1",
    })

    assert detection.platform is HostPlatform.CODEBUDDY
    assert detection.signal == "CODEBUDDY_PLUGIN_ROOT"


def test_detects_claude_code_from_native_signal() -> None:
    from auto_engineering.host import HostPlatform, detect_host

    detection = detect_host({"CLAUDE_CODE_ENTRYPOINT": "cli"})

    assert detection.platform is HostPlatform.CLAUDE_CODE
    assert detection.signal == "CLAUDE_CODE_ENTRYPOINT"


def test_credentials_do_not_identify_host_platform() -> None:
    from auto_engineering.host import HostPlatform, detect_host

    detection = detect_host({"ANTHROPIC_AUTH_TOKEN": "token"})

    assert detection.platform is HostPlatform.UNKNOWN
    assert detection.signal == "no host signal"


def test_codex_capabilities_are_explicit() -> None:
    from auto_engineering.host import HostPlatform, capabilities_for

    capabilities = capabilities_for(HostPlatform.CODEX)

    assert capabilities.skills is True
    assert capabilities.commands is False
    assert capabilities.subagents is True
    assert capabilities.parallel_subagents is True
    assert capabilities.transcript_usage is False
    assert capabilities.web_search is True
    assert capabilities.hooks == frozenset({
        "session_start",
        "pre_tool",
        "post_tool",
        "stop",
    })


def test_usage_source_is_explicit_per_host() -> None:
    from auto_engineering.host import HostPlatform, usage_source_for

    claude = usage_source_for(HostPlatform.CLAUDE_CODE)

    assert claude is not None
    assert claude.name == "claude-transcript"
    assert claude.provider == "anthropic"
    assert usage_source_for(HostPlatform.CODEX) is None
    assert usage_source_for(HostPlatform.UNKNOWN) is None


def test_codex_adapter_exposes_complete_host_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.host.adapters as adapters
    from auto_engineering.host import HostPlatform

    monkeypatch.setattr(
        adapters.shutil,
        "which",
        lambda executable: "/usr/bin/uv" if executable == "uv" else None,
    )

    adapter = adapters.adapter_for(HostPlatform.CODEX)
    event = adapter.normalize_event({
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Read",
        "tool_input": {"file_path": "src/example.py"},
    })

    assert adapter.platform is HostPlatform.CODEX
    assert adapter.capabilities.commands is False
    assert event is not None
    assert event.platform is HostPlatform.CODEX
    assert event.event == "pre_tool"
    assert event.file_path == "src/example.py"
    assert adapter.resolve_cli(tmp_path) == (
        "/usr/bin/uv",
        "run",
        "--project",
        str(tmp_path.resolve()),
        "ae",
    )
    assert adapter.usage_source(tmp_path) is None


def test_claude_adapter_prefers_local_cli_and_exposes_usage(
    tmp_path: Path,
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    executable = tmp_path / ".venv" / "bin" / "ae"
    executable.parent.mkdir(parents=True)
    executable.touch(mode=0o755)

    adapter = adapter_for(HostPlatform.CLAUDE_CODE)
    event = adapter.normalize_event({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"path": "README.md"},
    })
    usage = adapter.usage_source(tmp_path)

    assert adapter.platform is HostPlatform.CLAUDE_CODE
    assert event is not None
    assert event.platform is HostPlatform.CLAUDE_CODE
    assert event.event == "post_tool"
    assert adapter.resolve_cli(tmp_path) == (str(executable.resolve()),)
    assert usage is not None
    assert usage.name == "claude-transcript"
    assert usage.provider == "anthropic"


def test_adapter_rejects_hosts_without_an_implementation() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    with pytest.raises(ValueError, match="HOST_ADAPTER_UNAVAILABLE"):
        adapter_for(HostPlatform.UNKNOWN)


def test_unknown_host_has_no_assumed_capabilities() -> None:
    from auto_engineering.host import HostPlatform, capabilities_for

    capabilities = capabilities_for(HostPlatform.UNKNOWN)

    assert capabilities.skills is False
    assert capabilities.commands is False
    assert capabilities.hooks == frozenset()
    assert capabilities.subagents is False
    assert capabilities.web_search is False
    assert capabilities.git_mutation is False


def test_runtime_config_recognizes_codex_plugin_mode_without_credentials() -> None:
    from auto_engineering.config.runtime_config import RuntimeConfig
    from auto_engineering.host import HostPlatform

    config = RuntimeConfig(environ={"CODEX_THREAD_ID": "thread-1"})

    assert config.host_platform is HostPlatform.CODEX
    assert config.is_plugin_mode is True
    assert config.is_claude_code is False


def test_legacy_plugin_mode_api_reports_codex_signal() -> None:
    from auto_engineering.utils.plugin_mode import (
        detect_plugin_mode,
        detect_plugin_mode_detail,
    )

    environ = {"CODEX_THREAD_ID": "thread-1"}

    assert detect_plugin_mode(environ) is True
    assert detect_plugin_mode_detail(environ) == (True, "CODEX_THREAD_ID")


def test_doctor_describes_codex_without_anthropic_credentials(
    monkeypatch,
) -> None:
    from auto_engineering.cli.doctor import (
        _check_api_key,
        _check_openai_api_key,
        _check_plugin_mode,
    )

    for key in (
        "CLAUDE_CODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "ANTHROPIC_CLI",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")

    plugin_ok, plugin_message = _check_plugin_mode()
    credential_ok, credential_message = _check_api_key()
    openai_ok, openai_message = _check_openai_api_key()

    assert plugin_ok is True
    assert credential_ok is True
    assert openai_ok is True
    assert "Codex" in plugin_message
    assert "ANTHROPIC" not in plugin_message
    assert "宿主 Agent" in credential_message
    assert "ANTHROPIC" not in credential_message
    assert "Codex" in openai_message
