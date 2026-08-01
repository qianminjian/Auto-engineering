"""确定性静态审计门禁；已知行数债务只允许下降，不允许增长。"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "auto_engineering"
MAX_LINES = 400
LINE_DEBT = {
    "auto_engineering/loop/tick_orchestrator.py": 2593,
    "auto_engineering/loop/action_builder.py": 1012,
    "auto_engineering/loop/checkpoint/store.py": 829,
    "auto_engineering/cli/doctor.py": 677,
    "auto_engineering/loop/guardrail.py": 601,
    "auto_engineering/cli/dev_loop.py": 573,
    "auto_engineering/loop/event_store.py": 545,
    "auto_engineering/gates/audit.py": 513,
    "auto_engineering/loop/checkpoint/_serialization.py": 491,
    "auto_engineering/engine/models.py": 490,
    "auto_engineering/engine/progress_tree.py": 474,
    "auto_engineering/loop/guardrails/stateful.py": 459,
    "auto_engineering/engine/design_doc.py": 445,
    "auto_engineering/loop/convergence.py": 436,
    "auto_engineering/metrics/collector.py": 408,
    "auto_engineering/engine/batch_state.py": 406,
    "auto_engineering/engine/state.py": 404,
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
