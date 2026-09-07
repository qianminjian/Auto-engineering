"""宿主进程退出边界的回归测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore


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
