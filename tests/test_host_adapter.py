"""Host-neutral 宿主平台与能力契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_host_profile_effective_capabilities_are_safe_intersection() -> None:
    from auto_engineering.host import HostCapabilities, HostPlatform
    from auto_engineering.host.profile import HostProfile

    profile = HostProfile(
        platform=HostPlatform.CODEX,
        declared=HostCapabilities(
            skills=True,
            hooks=frozenset({"pre_tool", "post_tool"}),
            subagents=True,
            parallel_subagents=True,
            git_mutation=True,
        ),
        detected=HostCapabilities(
            skills=True,
            hooks=frozenset({"pre_tool"}),
            subagents=True,
            parallel_subagents=True,
            git_mutation=True,
        ),
        authorized=HostCapabilities(
            skills=True,
            hooks=frozenset({"pre_tool", "stop"}),
            subagents=False,
            parallel_subagents=True,
            git_mutation=False,
        ),
    )

    assert profile.effective.skills is True
    assert profile.effective.hooks == frozenset({"pre_tool"})
    assert profile.effective.subagents is False
    assert profile.effective.parallel_subagents is False
    assert profile.effective.git_mutation is False


def test_adapter_builds_profile_from_declared_detected_and_authorized() -> None:
    from auto_engineering.host import HostCapabilities, HostPlatform
    from auto_engineering.host.adapters import adapter_for

    profile = adapter_for(HostPlatform.CODEX).profile(
        detected=HostCapabilities(skills=True, web_search=True),
        authorized=HostCapabilities(skills=True, web_search=False),
    )

    assert profile.platform is HostPlatform.CODEX
    assert profile.declared is adapter_for(HostPlatform.CODEX).capabilities
    assert profile.effective.skills is True
    assert profile.effective.web_search is False


@pytest.mark.parametrize("platform_name", ["CLAUDE_CODE", "CODEX"])
def test_adapter_2_contract_normalizes_all_core_boundaries(
    platform_name: str,
) -> None:
    from auto_engineering.host import HostCapabilities, HostPlatform
    from auto_engineering.host.adapters import adapter_for

    platform = HostPlatform[platform_name]
    adapter = adapter_for(platform)
    profile = adapter.probe(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action(
        {"action": "developer", "message_id": "msg-1"},
        profile=profile,
    )
    report = adapter.report_execution(
        {
            "message_id": "msg-1",
            "status": "completed",
            "result": {"stage": "developer"},
        }
    )

    assert profile.platform is platform
    assert mapped.platform is platform
    assert mapped.message_id == "msg-1"
    assert mapped.payload["action"] == "developer"
    assert report.platform is platform
    assert report.message_id == "msg-1"
    assert report.status == "completed"
    assert report.result == {"stage": "developer"}
    assert isinstance(profile.effective, HostCapabilities)


def test_execution_report_rejects_unstructured_host_payload() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)

    with pytest.raises(ValueError, match="HOST_EXECUTION_REPORT_INVALID"):
        adapter.report_execution({"status": "completed"})


@pytest.mark.parametrize("platform_name", ["CLAUDE_CODE", "CODEX"])
def test_rollover_maps_to_same_fail_closed_host_protocol(platform_name: str) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform[platform_name])
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    mapped = adapter.map_action({
        "action": "session_rollover",
        "message_id": "rollover-1",
        "claim_token": "claim-1",
        "capsule": {
            "artifact_id": "capsule-1",
            "sha256": "a" * 64,
            "schema_version": "1.0",
        },
    }, profile=profile)

    control = mapped.payload["host_control"]
    assert control["operation"] == "create_fresh_session"
    assert control["load_capsule"]["artifact_id"] == "capsule-1"
    assert control["submit_result"]["stage"] == "session_claimed"
    assert control["submit_result"]["claim_token"] == "claim-1"
    assert control["fail_closed"] is True


def test_rollover_fails_when_host_cannot_handoff_session() -> None:
    from auto_engineering.host import HostCapabilities, HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.profile(
        detected=HostCapabilities(skills=True, session_handoff=False),
        authorized=adapter.capabilities,
    )

    with pytest.raises(ValueError, match="HOST_SESSION_HANDOFF_UNAVAILABLE"):
        adapter.map_action({
            "action": "session_rollover",
            "message_id": "rollover-1",
            "claim_token": "claim-1",
            "capsule": {
                "artifact_id": "capsule-1",
                "sha256": "a" * 64,
                "schema_version": "1.0",
            },
        }, profile=profile)


def test_host_report_boundary_recovers_without_retaining_invalid_payload() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)
    with pytest.raises(ValueError, match="HOST_EXECUTION_REPORT_INVALID"):
        adapter.report_execution({"message_id": "msg-1", "status": "completed"})

    report = adapter.report_execution({
        "message_id": "msg-1",
        "status": "completed",
        "result": {"stage": "developer"},
    })

    assert report.result == {"stage": "developer"}


def test_claude_and_codex_map_same_core_action_semantics() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    action = {"action": "critic", "message_id": "msg-2", "tick": 8}
    mapped = []
    for platform in (HostPlatform.CLAUDE_CODE, HostPlatform.CODEX):
        adapter = adapter_for(platform)
        profile = adapter.probe(
            detected=adapter.capabilities,
            authorized=adapter.capabilities,
        )
        mapped.append(adapter.map_action(action, profile=profile))

    assert mapped[0].payload == mapped[1].payload == action
    assert mapped[0].platform is HostPlatform.CLAUDE_CODE
    assert mapped[1].platform is HostPlatform.CODEX


def test_map_action_fails_closed_when_capability_is_not_effective() -> None:
    from auto_engineering.host import HostCapabilities, HostPlatform
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(HostPlatform.CODEX)
    profile = adapter.probe(
        detected=HostCapabilities(skills=True),
        authorized=HostCapabilities(skills=True),
    )

    with pytest.raises(
        ValueError,
        match=r"HOST_CAPABILITY_UNAVAILABLE.*web_search",
    ):
        adapter.map_action(
            {
                "action": "research",
                "message_id": "msg-3",
                "capability_requirements": {"web_search": True},
            },
            profile=profile,
        )


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


def test_cli_resolution_falls_back_to_global_ae_and_reports_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.host.adapters as adapters
    from auto_engineering.host import HostPlatform

    adapter = adapters.adapter_for(HostPlatform.CODEX)
    monkeypatch.setattr(
        adapters.shutil,
        "which",
        lambda executable: "/usr/local/bin/ae" if executable == "ae" else None,
    )
    assert adapter.resolve_cli(tmp_path) == ("/usr/local/bin/ae",)

    monkeypatch.setattr(adapters.shutil, "which", lambda executable: None)
    with pytest.raises(FileNotFoundError, match="AE_CLI_NOT_FOUND"):
        adapter.resolve_cli(tmp_path)


def test_adapters_return_none_for_invalid_host_events() -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.adapters import adapter_for

    assert adapter_for(HostPlatform.CODEX).normalize_event({}) is None
    assert adapter_for(HostPlatform.CLAUDE_CODE).normalize_event({}) is None


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
