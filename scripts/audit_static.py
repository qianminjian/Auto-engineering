"""确定性静态审计门禁；已知行数债务只允许下降，不允许增长。"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "auto_engineering"
MAX_LINES = 400
LINE_DEBT = {
    # 2026-08-29 ratchet baseline: existing modules are tracked at their
    # measured size; any subsequent growth fails the gate. Refactoring remains
    # a separate T570 task and is not hidden by increasing MAX_LINES globally.
    "auto_engineering/cli/dev_loop.py": 1830,
    "auto_engineering/engine/batch_state.py": 573,
    "auto_engineering/engine/state.py": 435,
    "auto_engineering/engine/progress_tree.py": 485,
    "auto_engineering/host/adapters.py": 407,
    "auto_engineering/host/execution_assembler.py": 1341,
    "auto_engineering/host/supervisor.py": 682,
    "auto_engineering/loop/tick_orchestrator.py": 3431,
    "auto_engineering/loop/action_builder.py": 1729,
    "auto_engineering/loop/actions.py": 611,
    "auto_engineering/loop/checkpoint/store.py": 835,
    "auto_engineering/loop/event_store.py": 663,
    "auto_engineering/loop/guardrail.py": 620,
    "auto_engineering/loop/reducers.py": 484,
    "auto_engineering/loop/stages/design.py": 466,
    "auto_engineering/metrics/transcript_parser.py": 465,
    "auto_engineering/project_profile/providers.py": 419,
    "auto_engineering/cli/doctor.py": 677,
    "auto_engineering/gates/audit.py": 513,
    "auto_engineering/loop/checkpoint/_serialization.py": 491,
    "auto_engineering/engine/models.py": 490,
    "auto_engineering/loop/guardrails/stateful.py": 459,
    "auto_engineering/engine/design_doc.py": 445,
    "auto_engineering/loop/convergence.py": 436,
    "auto_engineering/metrics/collector.py": 408,
}


def _python_files() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def audit_line_count() -> list[str]:
    errors: list[str] = []
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        count = len(path.read_text(encoding="utf-8").splitlines())
        limit = LINE_DEBT.get(relative, MAX_LINES)
        if count > limit:
            errors.append(f"{relative}:{count} lines > limit {limit}")
    return errors


def _handler_has_observable_outcome(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute) and target.attr in {
                "debug", "info", "warning", "error", "exception", "critical",
            }:
                return True
    return False


def audit_silent_except() -> list[str]:
    errors: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            catches_exception = (
                node.type is None
                or (
                    isinstance(node.type, ast.Name)
                    and node.type.id in {"Exception", "BaseException"}
                )
            )
            if catches_exception and not _handler_has_observable_outcome(node):
                errors.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno} 静默吞异常"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("check", choices=("silent-except", "line-count"))
    args = parser.parse_args()
    errors = audit_silent_except() if args.check == "silent-except" else audit_line_count()
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
