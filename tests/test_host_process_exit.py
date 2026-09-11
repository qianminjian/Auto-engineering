"""宿主进程退出边界的回归测试。"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path

from auto_engineering.host.runtime_driver import (
    HostRunLease,
    HostRunLeaseStore,
    fencing_token_for,
)


def _save_lease(root: Path, *, session_id: str = "session-1") -> None:
    HostRunLeaseStore(root).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id=session_id,
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
        fencing_token=fencing_token_for("action-1", session_id, 1),
    ))


def _write_result(path: Path, *, session_id: str = "session-1") -> None:
    path.write_text(json.dumps({
        "type": "result",
        "session_id": session_id,
        "is_error": True,
        "terminal_reason": "budget_exhausted",
        "stop_reason": "tool_use",
    }) + "\n", encoding="utf-8")


def test_process_exit_records_report_and_clears_continue_lease(tmp_path: Path) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    _write_result(host_output)

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "1",
    ]) == 0

    assert HostRunLeaseStore(tmp_path).load() is None
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"
    assert report["termination_category"] == "host_action_failed_with_continue"
    assert report["last_host_observation"]["reason"] == "budget_exhausted"


def test_process_exit_classifies_provider_stream_idle_timeout(tmp_path: Path) -> None:
    """上游流空闲错误必须保留为稳定的宿主故障事实。"""

    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    host_output.write_text(
        json.dumps({
            "type": "message",
            "is_api_error_message": True,
            "content": [{
                "type": "text",
                "text": "API Error: Stream idle timeout - no chunks received",
            }],
        }) + "\n" + json.dumps({
            "type": "result",
            "session_id": "session-1",
            "is_error": True,
            "terminal_reason": "api_error",
            "result": "API Error: Stream idle timeout - no chunks received",
        }) + "\n",
        encoding="utf-8",
    )

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "1",
    ]) == 0

    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROVIDER_STREAM_IDLE_TIMEOUT"
    assert report["last_host_observation"]["reason"] == (
        "HOST_PROVIDER_STREAM_IDLE_TIMEOUT"
    )


def test_process_exit_uses_bounded_fallback_when_host_output_is_not_json(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    host_output.write_text("host terminated before emitting a result\n", encoding="utf-8")

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "137",
    ]) == 0

    assert HostRunLeaseStore(tmp_path).load() is None
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["last_host_observation"]["reason"] == "process_exit"


def test_process_exit_extracts_nested_time_limit_reason_and_resume_operation(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    host_output.write_text(
        "\n".join([
            json.dumps({
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps({
                        "status": "failed",
                        "error_code": "TIME_LIMIT_EXCEEDED",
                    }),
                },
            }),
            json.dumps({"type": "turn.completed", "usage": {"output_tokens": 1}}),
        ]) + "\n",
        encoding="utf-8",
    )

    output = StringIO()
    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "1",
    ], stdout=output) == 0

    response = json.loads(output.getvalue())
    assert response["next_operation"] == {
        "operation": "resume_active_action",
        "thread_id": "thread-1",
        "argv": ["dev-loop", "--resume", "thread-1"],
    }
    report_path = tmp_path / response["stop_report_path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["last_host_observation"]["reason"] == "TIME_LIMIT_EXCEEDED"


def test_process_exit_rejects_result_session_mismatch_without_clearing_lease(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path, session_id="session-owner")
    host_output = tmp_path / "host-stream.jsonl"
    _write_result(host_output, session_id="session-other")

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "1",
    ]) == 2

    assert HostRunLeaseStore(tmp_path).load() is not None
    assert not (tmp_path / ".ae-state/host-runtime/stop-reports").exists()


def test_host_run_wrapper_preserves_exit_code_and_records_boundary(tmp_path: Path) -> None:
    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    payload = json.dumps({
        "type": "result",
        "session_id": "session-1",
        "is_error": True,
        "terminal_reason": "budget_exhausted",
    })

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--", sys.executable, "-c", f"print({payload!r})",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(host_output.read_text(encoding="utf-8"))["terminal_reason"] == (
        "budget_exhausted"
    )
    assert HostRunLeaseStore(tmp_path).load() is None
    assert list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))


def test_host_run_wrapper_resolves_relative_output_before_changing_project_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", "project",
            "--output", "host-stream.jsonl",
            "--", sys.executable, "-c", "print('ready')",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert (tmp_path / "host-stream.jsonl").read_text(encoding="utf-8") == "ready\n"


def test_host_run_wrapper_exports_fixed_invocation_root(tmp_path: Path) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "import json, os; print(json.dumps({\"root\": "
        "os.environ.get(\"AE_INVOCATION_PROJECT_ROOT\")}, ensure_ascii=False))"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(host_output.read_text(encoding="utf-8"))["root"] == str(tmp_path)


def test_host_run_wrapper_binds_claude_command_over_inherited_codex_signal(
    tmp_path: Path,
) -> None:
    """外层 Codex 环境不能覆盖边界内真实 Claude 命令的身份。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    observed_platform = tmp_path / "observed-platform.txt"
    claude_command = tmp_path / "claude"
    claude_command.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$AE_HOST_PLATFORM\" > {shlex.quote(str(observed_platform))}\n"
        "printf '%s\\n' '{\"type\":\"result\",\"session_id\":\"session-1\","
        "\"is_error\":true,\"terminal_reason\":\"budget_exhausted\"}'\n",
        encoding="utf-8",
    )
    claude_command.chmod(0o755)

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--", str(claude_command), "-p",
        ],
        cwd=tmp_path,
        env={**os.environ, "CODEX_THREAD_ID": "outer-codex"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert observed_platform.read_text(encoding="utf-8").strip() == "claude-code"
    assert HostRunLeaseStore(tmp_path).load() is None


def test_host_run_wrapper_provisions_claude_session_for_standalone_cli(
    tmp_path: Path,
) -> None:
    """独立 claude CLI 没有内部 session 环境变量时，边界适配器必须补齐。"""

    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    observed_session = tmp_path / "observed-session.txt"
    claude_command = tmp_path / "claude"
    claude_command.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$CLAUDE_CODE_SESSION_ID\" > {shlex.quote(str(observed_session))}\n"
        "printf '%s\\n' '{\"type\":\"result\",\"session_id\":\"placeholder\","
        "\"is_error\":true,\"terminal_reason\":\"budget_exhausted\"}'\n",
        encoding="utf-8",
    )
    claude_command.chmod(0o755)

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--", str(claude_command), "-p",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "AE_HOST_PLATFORM": "",
            "CODEX_THREAD_ID": "outer-codex",
            "CLAUDE_CODE_SESSION_ID": "",
            "CLAUDE_SESSION_ID": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    session_id = observed_session.read_text(encoding="utf-8").strip()
    assert session_id.startswith("ae-host-") or len(session_id) >= 16


def test_host_run_wrapper_rejects_explicit_platform_command_conflict(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    claude_command = tmp_path / "claude"
    claude_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude_command.chmod(0o755)

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(tmp_path / "host-stream.jsonl"),
            "--", str(claude_command),
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_PLATFORM": "codex"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "HOST_COMMAND_PLATFORM_MISMATCH" in result.stderr


def test_host_run_wrapper_marks_auto_resume_for_session_end_hook(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "import json, os; print(json.dumps({\"auto_resume\": "
        "os.environ.get(\"AE_HOST_ADAPTER_AUTO_RESUME\")}, ensure_ascii=False))"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--auto-resume", "--max-resumes", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 75
    assert json.loads(host_output.read_text(encoding="utf-8"))["auto_resume"] == "1"


def test_host_run_wrapper_rejects_disabled_slash_commands_with_loop_entry(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(tmp_path / "host-stream.jsonl"),
            "--", "claude", "-p", "--disable-slash-commands",
            "/auto-engineering:dev-loop \"不可执行\"",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "HOST_COMMAND_CONTRACT_INVALID" in result.stderr
    assert not (tmp_path / "host-stream.jsonl.adapter-active").exists()


def test_host_run_wrapper_rejects_nested_adapter_boundary(tmp_path: Path) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(tmp_path / "host-stream.jsonl"),
            "--", sys.executable, "-c", "print('unreachable')",
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_ADAPTER_ACTIVE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 75
    assert "禁止嵌套调用" in result.stderr


def test_host_run_wrapper_rejects_nested_adapter_with_filtered_environment(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    output = tmp_path / "host-stream.jsonl"
    nested_command = (
        "import os, subprocess; "
        f"subprocess.run(['env', '-u', 'AE_HOST_ADAPTER_ACTIVE', {str(wrapper)!r}, "
        f"'--project-root', {str(tmp_path)!r}, '--output', {str(output)!r}, "
        f"'--', {sys.executable!r}, '-c', \"print('unreachable')\"], check=False)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(output),
            "--", sys.executable, "-c", nested_command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0
    assert "同一输出路径已有宿主边界适配器运行" in result.stderr
    assert not output.with_name(output.name + ".adapter-active").exists()
    assert HostRunLeaseStore(tmp_path).load() is None


def test_host_run_wrapper_rejects_nested_adapter_with_different_output_path(
    tmp_path: Path,
) -> None:
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    outer_output = tmp_path / "outer.jsonl"
    inner_output = tmp_path / "inner.jsonl"
    nested_command = (
        "import os, subprocess; os.environ.pop('AE_HOST_ADAPTER_ACTIVE', None); "
        f"subprocess.run([{str(wrapper)!r}, '--project-root', {str(tmp_path)!r}, "
        f"'--output', {str(inner_output)!r}, '--', {sys.executable!r}, '-c', "
        "\"print('unreachable')\"], check=False)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(outer_output),
            "--", sys.executable, "-c", nested_command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0
    assert "同一项目已有宿主边界适配器运行" in result.stderr
    assert not inner_output.exists()


def test_host_run_wrapper_bounds_host_runtime_and_records_timeout(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-runtime-seconds", "1",
            "--", sys.executable, "-c", "import time; time.sleep(5)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=4,
    )

    assert result.returncode != 0
    assert HostRunLeaseStore(tmp_path).load() is None
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_TIMEOUT"


def test_host_run_wrapper_bounds_host_idle_time_and_records_idle_timeout(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", "import time; time.sleep(5)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=4,
    )

    assert result.returncode != 0
    assert HostRunLeaseStore(tmp_path).load() is None
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_treat_thinking_tokens_as_progress(
    tmp_path: Path,
) -> None:
    """传输层 thinking 心跳不能让没有语义进展的宿主绕过 idle 上限。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "import json, time; "
        "[print(json.dumps({'type':'system','subtype':'thinking_tokens'}), flush=True) "
        "or time.sleep(0.2) for _ in range(12)]; time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--max-runtime-seconds", "4",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_treat_repeated_tool_calls_as_progress(
    tmp_path: Path,
) -> None:
    """重复工具调用不能在 Core 状态不变时绕过 idle 上限。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "import json, time; "
        "event={'type':'assistant','message':{'content':[{'type':'tool_use',"
        "'name':'Bash'}]}}; "
        "[print(json.dumps(event), flush=True) or time.sleep(0.2) for _ in range(12)]; "
        "time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--max-runtime-seconds", "4",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_treat_repeated_terminal_stream_as_progress(
    tmp_path: Path,
) -> None:
    """重复 result/turn.completed 不能在没有新事实时绕过 idle 上限。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "import json, time; "
        "event={'type':'result','session_id':'session-1',"
        "'is_error':True,'terminal_reason':'budget_exhausted'}; "
        "[print(json.dumps(event), flush=True) or time.sleep(0.2) for _ in range(12)]; "
        "time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--max-runtime-seconds", "4",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_treat_unknown_stream_noise_as_progress(
    tmp_path: Path,
) -> None:
    """未知事件和非结构化噪声不能伪装成宿主语义进展。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "import json, time; "
        "[print(json.dumps({'type':'unknown_heartbeat'}), flush=True) or "
        "time.sleep(.2) for _ in range(12)]; time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_records_user_interrupt_before_exiting(
    tmp_path: Path,
) -> None:
    """用户中断不能留下没有 Stop Report 的 active Action。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    process = subprocess.Popen(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--", sys.executable, "-c", "import time; time.sleep(30)",
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.3)
    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=8)

    assert process.returncode == 130, (stdout, stderr)
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_INTERRUPTED"
    assert report["lease_cleared"] is True


def test_host_run_wrapper_treats_action_state_activity_as_liveness(
    tmp_path: Path,
) -> None:
    """原生 Worker 静默时，Action-scoped 状态变化不能被误判为 idle。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    activity = tmp_path / ".ae-state/host-runtime/worker-outcomes/activity.json"
    activity.parent.mkdir(parents=True, exist_ok=True)
    command = (
        "from pathlib import Path; import time; "
        f"p=Path({str(activity)!r}); time.sleep(0.5); "
        "p.write_text('worker-progress'); time.sleep(0.8)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"


def test_host_run_wrapper_allows_idle_during_current_claude_native_call(
    tmp_path: Path,
) -> None:
    """同步 Claude Agent 等待期间，running observation 不是宿主失活。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    claude_command = tmp_path / "claude"
    fencing_token = fencing_token_for("action-1", "session-1", 1)
    claude_command.write_text(
        "#!/bin/sh\n"
        "sleep 0.2\n"
        "mkdir -p .ae-state/host-runtime/worker-observations\n"
        f"printf '%s' '{{\"action_message_id\":\"action-1\","
        f"\"execution_generation\":1,\"fencing_token\":\"{fencing_token}\","
        "\"native_status\":\"running\","
        "\"observed_at\":\"' > "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "date -u +%Y-%m-%dT%H:%M:%S.%N%z | tr -d '\\n' >> "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "printf '%s\\n' '\"}' >> "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "sleep 2\n"
        "printf '%s\\n' '{\"type\":\"result\",\"session_id\":\"session-1\","
        "\"is_error\":true,\"terminal_reason\":\"budget_exhausted\"}'\n",
        encoding="utf-8",
    )
    claude_command.chmod(0o755)

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", str(claude_command), "-p",
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_PLATFORM": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode == 0, result.stderr
    assert not host_output.with_name(host_output.name + ".idle-timeout").exists()


def test_host_run_wrapper_allows_delayed_first_claude_native_observation(
    tmp_path: Path,
) -> None:
    """首次 native running observation 延迟到达时，启动竞态不能误触发 idle。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    claude_command = tmp_path / "claude"
    fencing_token = fencing_token_for("action-1", "session-1", 1)
    claude_command.write_text(
        "#!/bin/sh\n"
        "sleep 1.5\n"
        "mkdir -p .ae-state/host-runtime/worker-observations\n"
        f"printf '%s' '{{\"action_message_id\":\"action-1\","
        f"\"execution_generation\":1,\"fencing_token\":\"{fencing_token}\","
        "\"native_status\":\"running\","
        "\"observed_at\":\"' > "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "date -u +%Y-%m-%dT%H:%M:%S.%N%z | tr -d '\\n' >> "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "printf '%s\n' '\"}' >> "
        ".ae-state/host-runtime/worker-observations/current.json\n"
        "sleep 0.5\n"
        "printf '%s\n' '{\"type\":\"result\",\"session_id\":\"session-1\","
        "\"is_error\":true,\"terminal_reason\":\"budget_exhausted\"}'\n",
        encoding="utf-8",
    )
    claude_command.chmod(0o755)

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", str(claude_command), "-p",
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_PLATFORM": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode == 0, result.stderr
    assert not host_output.with_name(host_output.name + ".idle-timeout").exists()


def test_host_run_wrapper_does_not_allow_mismatched_fencing_observation(
    tmp_path: Path,
) -> None:
    """旧会话或伪造的 fencing observation 不能绕过 idle。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from datetime import datetime, timezone; from pathlib import Path; "
        "import time; "
        "p=Path('.ae-state/host-runtime/worker-observations/current.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text('{\"action_message_id\":\"action-1\","
        "\"execution_generation\":1,"
        "\"fencing_token\":\"'+'0'*64+'\","
        "\"native_status\":\"running\",\"observed_at\":\"' + "
        "datetime.now(timezone.utc).isoformat() + '\"}'); "
        "time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_allow_repeated_mismatched_observations(
    tmp_path: Path,
) -> None:
    """连续改写错误 fencing observation 不能把伪造流量变成 liveness。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from datetime import datetime, timezone; from pathlib import Path; "
        "import time, json; "
        "p=Path('.ae-state/host-runtime/worker-observations/current.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(p.write_text(json.dumps({'action_message_id':'action-1',"
        "'execution_generation':1,'fencing_token':'0'*64,"
        "'native_status':'running','observed_at':datetime.now(timezone.utc).isoformat()})),"
        "time.sleep(0.3)) for _ in range(20)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_allow_repeated_native_result_rewrites(
    tmp_path: Path,
) -> None:
    """反复改写原始 native result 不能替代提交后的 Worker 事实。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from pathlib import Path; import time; "
        "p=Path('.ae-state/host-runtime/native-results/current.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(p.write_text('{\"candidate\":'+str(i)+'}'), time.sleep(0.3)) "
        "for i in range(20)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_does_not_allow_stale_native_observation_forever(
    tmp_path: Path,
) -> None:
    """丢失 PostToolUse 时，过期 running observation 不能永久绕过 idle。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from pathlib import Path; import time; "
        "p=Path('.ae-state/host-runtime/worker-observations/current.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "p.write_text('{\"action_message_id\":\"action-1\","
        "\"execution_generation\":1,\"native_status\":\"running\","
        "\"observed_at\":\"2000-01-01T00:00:00+00:00\"}'); "
        "time.sleep(5)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_repeated_identical_work_file_writes(
    tmp_path: Path,
) -> None:
    """重复覆盖同一 Result 不能伪装成 Action 进展。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from pathlib import Path; import time; "
        "p=Path('.ae-state/host-runtime/work/current/result.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(p.write_text('{\"same\":true}'), time.sleep(0.6)) for _ in range(6)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_changing_unsubmitted_work_file_writes(
    tmp_path: Path,
) -> None:
    """不断改写未提交候选 Result 不能伪装成宿主语义进展。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "from pathlib import Path; import time; "
        "p=Path('.ae-state/host-runtime/work/current/result.json'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(p.write_text('{\"candidate\":'+str(i)+'}'), time.sleep(0.3)) "
        "for i in range(20)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_active_lease_rewrites_for_liveness(
    tmp_path: Path,
) -> None:
    """租约身份重写不能把没有业务进展的宿主伪装成活跃。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    lease_path = tmp_path / ".ae-state/host-runtime/active-lease.json"
    command = (
        "from pathlib import Path; import json, time; "
        f"p=Path({str(lease_path)!r}); "
        "base={'schema_version':'1.0','thread_id':'thread-1',"
        "'action_message_id':'action-1','platform':'claude-code',"
        "'host_session_id':'session-1','build_id':'build-1',"
        "'disposition':'CONTINUE','continuation_required':True,"
        "'yield_allowed':False,'execution_generation':1,"
        "'fencing_token':__import__('hashlib').sha256("
        "b'action-1:session-1:1').hexdigest()}; "
        "[(base.__setitem__('build_id','build-'+str(i % 2)),"
        "p.write_text(json.dumps(base)), time.sleep(0.3)) for i in range(20)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_PLATFORM": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_unrelated_state_activity_for_liveness(
    tmp_path: Path,
) -> None:
    """非 Action 状态变化不能把真正失活的宿主伪装成活跃。"""

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    unrelated = tmp_path / ".ae-state" / "offload" / "activity.json"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    command = (
        "from pathlib import Path; import time; "
        f"p=Path({str(unrelated)!r}); time.sleep(0.5); "
        "p.write_text('unrelated-progress'); time.sleep(1.1)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_legacy_checkpoint_writes_for_liveness(
    tmp_path: Path,
) -> None:
    """新 EventStore 运行中，遗留 checkpoint 改写不能延长宿主等待。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from pathlib import Path; import time; "
        "p=Path('.ae-state/checkpoints.db'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(p.write_bytes(str(i).encode()), time.sleep(0.3)) for i in range(12)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_ignores_event_store_touch_for_liveness(
    tmp_path: Path,
) -> None:
    """只 touch EventStore 文件而不提交事件，不能延长宿主等待。"""

    _save_lease(tmp_path)
    from auto_engineering.loop.event_store import SQLiteEventStore

    with SQLiteEventStore(tmp_path / ".ae-state" / "events.db"):
        pass
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "from pathlib import Path; import os, time; "
        "p=Path('.ae-state/events.db'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "[(os.utime(p, None), time.sleep(0.3)) for _ in range(12)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode != 0
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_treats_committed_event_store_fact_as_liveness(
    tmp_path: Path,
) -> None:
    """已提交 EventStore 事实可以延长观察，数据库 touch 本身不行。"""

    _save_lease(tmp_path)
    from auto_engineering.loop.event_store import SQLiteEventStore

    event_store_path = tmp_path / ".ae-state" / "events.db"
    with SQLiteEventStore(event_store_path):
        pass
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    repository_root = Path(__file__).parents[1]
    command = (
        "import sys, time; "
        f"sys.path.insert(0, {str(repository_root)!r}); "
        "from auto_engineering.loop.event_store import SQLiteEventStore; "
        "from auto_engineering.loop.events import LoopEvent, LoopEventType; "
        f"store=SQLiteEventStore({str(event_store_path)!r}); time.sleep(0.5); "
        "store.append([LoopEvent.create(thread_id='thread-1', "
        "sequence=store.next_sequence('thread-1'), "
        "event_type=LoopEventType.TELEMETRY_RECORDED, "
        "payload={'kind':'host-progress'}, correlation_id='correlation-1')]); "
        "store.close(); time.sleep(0.8)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_RUNTIME_PROTOCOL_ERROR"


def test_host_run_wrapper_forces_exit_when_host_ignores_term(
    tmp_path: Path,
) -> None:
    """watchdog 触发后，拒绝 TERM 的宿主也不能让适配器永久挂起。"""
    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    command = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(30)"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-idle-seconds", "1",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=9,
    )

    assert result.returncode != 0
    assert HostRunLeaseStore(tmp_path).load() is None
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROCESS_IDLE_TIMEOUT"


def test_host_run_wrapper_bounds_repeated_protocol_refusals_without_resuming(
    tmp_path: Path,
) -> None:
    """同一宿主反复被 Hook 拒绝时必须熔断，而不是进入反馈死循环。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "import time; "
        "[print('NATIVE_WORKER_STOP_FORBIDDEN', flush=True) or time.sleep(0.2) "
        "for _ in range(20)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--auto-resume", "--max-protocol-refusals", "2",
            "--max-idle-seconds", "10",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 75
    assert HostRunLeaseStore(tmp_path).load() is not None
    reports = list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_PROTOCOL_RETRY_EXHAUSTED"
    assert "有界次数" in result.stderr


def test_host_run_wrapper_does_not_treat_nested_blocked_hook_as_protocol_refusal(
    tmp_path: Path,
) -> None:
    """Worker transcript 中的普通 Stop hook 文本不能越层触发外层熔断。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    payload = json.dumps({
        "type": "result",
        "session_id": "session-1",
        "is_error": True,
        "terminal_reason": "process_exit",
    })
    command = (
        "import json, time; "
        "[print('Stop hook feedback: Blocked by hook', flush=True) or time.sleep(0.2) "
        "for _ in range(4)]; "
        f"print({payload!r})"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--max-protocol-refusals", "2",
            "--max-idle-seconds", "10",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0
    assert "HOST_PROTOCOL_RETRY_EXHAUSTED" not in result.stderr
    records = [
        json.loads(line)
        for line in host_output.read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]
    assert records[-1]["terminal_reason"] == "process_exit"


def test_host_run_wrapper_bounds_repeated_coordinator_resume_polls(
    tmp_path: Path,
) -> None:
    """同一 Action 反复 resume 但没有消费 Worker 事实时必须停止放大。"""

    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    host_output = tmp_path / "host-stream.jsonl"
    command = (
        "import time; "
        "[print('dev-loop --resume 12345678-1234-1234-1234-123456789abc', flush=True) "
        "or time.sleep(0.2) for _ in range(10)]"
    )

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--auto-resume", "--max-coordinator-polls", "2",
            "--max-idle-seconds", "10",
            "--", sys.executable, "-c", command,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 75
    assert HostRunLeaseStore(tmp_path).load() is not None
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_COORDINATOR_POLL_LIMIT"
    assert "Coordinator resume" in result.stderr


def test_host_run_wrapper_auto_resumes_only_for_continue_status(
    tmp_path: Path,
) -> None:
    _save_lease(tmp_path)
    wrapper = Path(__file__).parents[1] / "scripts" / "ae-host-run"
    real_runner = Path(__file__).parents[1] / "scripts" / "ae-run"
    runner_state = tmp_path / "runner-state"
    host_count = tmp_path / "host-count"
    fake_runner = tmp_path / "fake-runner"
    fake_runner.write_text(
        "#!/bin/sh\n"
        "set -u\n"
        f"REAL_RUNNER={shlex.quote(str(real_runner))}\n"
        f"STATE={shlex.quote(str(runner_state))}\n"
        "if [ \"${1:-}\" = \"dev-loop\" ] && [ \"${2:-}\" = \"--status\" ]; then\n"
        "  count=$(cat \"$STATE\" 2>/dev/null || printf '0')\n"
        "  count=$((count + 1))\n"
        "  printf '%s' \"$count\" > \"$STATE\"\n"
        "  if [ \"$count\" -eq 1 ]; then\n"
        "    printf '%s\\n' "
        "'{\"thread_id\":\"thread-1\",\"active_action\":{\"message_id\":\"action-1\"},"
        "\"next_operation\":{\"operation\":\"resume_active_action\","
        "\"thread_id\":\"thread-1\"}}'\n"
        "  else\n"
        "    printf '%s\\n' '{\"next_operation\":{\"operation\":\"terminal\"}}'\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"--run-module\" ] && [ \"${2:-}\" = \"auto_engineering.host.continuation_driver\" ]; then\n"
        "  case \" $* \" in *' --project-root '*) exit 91;; esac\n"
        "  count=$(cat \"$STATE\" 2>/dev/null || printf '0')\n"
        "  if [ \"$count\" -eq 1 ]; then printf '%s\\n' resume; else printf '%s\\n' stop; fi\n"
        "  exit 0\n"
        "fi\n"
        "exec \"$REAL_RUNNER\" \"$@\"\n",
        encoding="utf-8",
    )
    fake_runner.chmod(0o755)
    host_command = (
        "from pathlib import Path; import json; "
        f"p=Path({str(host_count)!r}); n=int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n+1)); "
        "print(json.dumps({'type':'result','session_id':'session-1','terminal_reason':'process_exit'}))"
    )
    host_output = tmp_path / "host-stream.jsonl"

    result = subprocess.run(
        [
            str(wrapper),
            "--project-root", str(tmp_path),
            "--output", str(host_output),
            "--auto-resume", "--max-resumes", "2",
            "--", sys.executable, "-c", host_command,
        ],
        cwd=tmp_path,
        env={**os.environ, "AE_HOST_RUNNER": str(fake_runner)},
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert host_count.read_text(encoding="utf-8") == "2"
    assert len(host_output.read_text(encoding="utf-8").splitlines()) == 2


def test_process_exit_can_record_missing_worker_handle_without_fake_result(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    missing_output = tmp_path / "missing-host-stream.jsonl"

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(missing_output),
        "--exit-code", "75",
        "--reason-code", "HOST_WORKER_ATTESTATION_MISSING",
    ]) == 0

    assert HostRunLeaseStore(tmp_path).load() is None
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["reason_code"] == "HOST_WORKER_ATTESTATION_MISSING"
    assert report["last_host_observation"]["reason"] == "process_exit"


def test_process_exit_can_preserve_continue_lease_for_auto_resume(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.process_exit import main

    _save_lease(tmp_path)
    host_output = tmp_path / "host-stream.jsonl"
    _write_result(host_output)

    assert main([
        "--project-root", str(tmp_path),
        "--host-output", str(host_output),
        "--exit-code", "1",
        "--preserve-lease",
    ]) == 0

    assert HostRunLeaseStore(tmp_path).load() is not None
    report = json.loads(next(
        (tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")
    ).read_text(encoding="utf-8"))
    assert report["lease_cleared"] is False


def test_continuation_driver_rejects_stale_lease_for_different_action() -> None:
    from auto_engineering.host.continuation_driver import should_resume_host

    status = {
        "thread_id": "thread-current",
        "active_action": {"message_id": "action-current"},
        "next_operation": {
            "operation": "resume_active_action",
            "thread_id": "thread-current",
        },
    }
    stale_lease = {
        "thread_id": "thread-old",
        "action_message_id": "action-old",
        "disposition": "CONTINUE",
        "continuation_required": True,
        "yield_allowed": False,
    }

    assert should_resume_host(status, stale_lease) is False


def test_continuation_driver_requires_complete_action_identity() -> None:
    from auto_engineering.host.continuation_driver import should_resume_host

    status = {
        "thread_id": "thread-current",
        "active_action": {"message_id": "action-current"},
        "next_operation": {"operation": "resume_active_action"},
    }
    lease = {
        "thread_id": "thread-current",
        "action_message_id": "action-current",
        "disposition": "CONTINUE",
        "continuation_required": True,
        "yield_allowed": False,
    }

    assert should_resume_host(status, lease) is False
