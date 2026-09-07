"""顺序执行项目验收 Gate 并生成可追溯业务证据；不创建或推进 Loop。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.product_acceptance import (  # noqa: E402
    _read_candidate_build_info,
)

REQUIRED_GATES = ("typecheck", "unit_test", "build")


class BusinessEvidenceGenerationError(ValueError):
    """无法生成结构化业务证据。"""


def _validate_gate_commands(
    gate_commands: dict[str, list[str]],
) -> None:
    if set(gate_commands) != set(REQUIRED_GATES):
        raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMANDS_INCOMPLETE")
    for command in gate_commands.values():
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMAND_INVALID")


def _run_gate(
    *,
    root: Path,
    name: str,
    command: list[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
        output = (completed.stdout or b"") + (completed.stderr or b"")
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        if isinstance(stdout, str):
            stdout = stdout.encode()
        if isinstance(stderr, str):
            stderr = stderr.encode()
        output = stdout + stderr + b"\n[gate timeout]\n"
        exit_code = None
    output_path = root / ".ae-state" / "product-evidence" / f"{name}.log"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    return {
        "status": "pass" if exit_code == 0 else "fail",
        "command": list(command),
        "exit_code": exit_code,
        "evidence_path": output_path.relative_to(root).as_posix(),
        "evidence_sha256": hashlib.sha256(output).hexdigest(),
        "evidence_bytes": len(output),
    }


def generate_business_evidence(
    *,
    project_root: Path,
    archive: Path,
    output: Path,
    gate_commands: dict[str, list[str]],
    scenario_id: str = "voice-clone-v1",
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """执行确定性业务 Gate，生成独立的 L4 业务证据。"""

    if timeout_seconds <= 0:
        raise BusinessEvidenceGenerationError("BUSINESS_GATE_TIMEOUT_INVALID")
    _validate_gate_commands(gate_commands)
    root = project_root.resolve()
    report_path = output.resolve()
    if not report_path.is_relative_to(root):
        raise BusinessEvidenceGenerationError("BUSINESS_EVIDENCE_OUTPUT_INVALID")
    candidate = _read_candidate_build_info(archive)
    gates = {
        name: _run_gate(
            root=root,
            name=name,
            command=gate_commands[name],
            timeout_seconds=timeout_seconds,
        )
        for name in REQUIRED_GATES
    }
    passed = all(item["status"] == "pass" for item in gates.values())
    report = {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "build_id": candidate["build_id"],
        "gates": gates,
        "final_verdict": "pass" if passed else "fail",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _parse_gate_command(value: str) -> tuple[str, list[str]]:
    name, separator, encoded = value.partition("=")
    if not separator or name not in REQUIRED_GATES:
        raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMAND_INVALID")
    try:
        command = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMAND_INVALID") from exc
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMAND_INVALID")
    return name, command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate-command", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    try:
        commands: dict[str, list[str]] = {}
        for value in args.gate_command:
            name, command = _parse_gate_command(value)
            if name in commands:
                raise BusinessEvidenceGenerationError("BUSINESS_GATE_COMMAND_DUPLICATE")
            commands[name] = command
        report = generate_business_evidence(
            project_root=args.project_root,
            archive=args.archive,
            output=args.output,
            gate_commands=commands,
            timeout_seconds=args.timeout_seconds,
        )
    except (BusinessEvidenceGenerationError, ValueError, OSError) as exc:
        parser.exit(2, f"business evidence generation failed: {exc}\n")
    print(args.output)
    return 0 if report["final_verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
