"""Developer 测试证据完整性守门（T786）。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.shared.guardrail import Guardrail, GuardrailResult

_ASSERTION_PATTERNS = (
    re.compile(r"\bassert\b"),
    re.compile(r"\bexpect\s*\("),
    re.compile(r"\b(?:assert|require)\.[A-Za-z_]+\s*\("),
    re.compile(r"\bassert(?:_eq|_ne|_ok|_not)?!\s*\("),
)


def _is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.py")
    )


def count_test_assertions(source: str) -> int:
    """Count common assertion expressions without retaining test contents."""
    return sum(
        len(pattern.findall(line))
        for line in source.splitlines()
        for pattern in _ASSERTION_PATTERNS
    )


def _resolve_relative_file(raw_path: str, root: Path) -> tuple[str, Path] | None:
    candidate = Path(raw_path)
    resolved_root = root.resolve()
    resolved = (candidate if candidate.is_absolute() else resolved_root / candidate).resolve(
        strict=False,
    )
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError:
        return None
    return relative, resolved


def collect_test_assertion_baseline(
    paths: Sequence[str], root: Path,
) -> dict[str, dict[str, int]]:
    """Create a small Action-bound baseline for existing test files."""
    baseline: dict[str, dict[str, int]] = {}
    for raw_path in paths:
        if not isinstance(raw_path, str) or not _is_test_file(raw_path):
            continue
        resolved_item = _resolve_relative_file(raw_path, root)
        if resolved_item is None:
            continue
        relative, resolved = resolved_item
        try:
            if not resolved.is_file():
                continue
            source = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        baseline[relative] = {"assertion_count": count_test_assertions(source)}
    return baseline


def _baseline_from_state(state: object) -> Mapping[str, Any]:
    runtime_context = getattr(state, "_runtime_ctx", {})
    active_action = (
        runtime_context.get("active_action")
        if isinstance(runtime_context, Mapping)
        else None
    )
    if not isinstance(active_action, Mapping):
        return {}
    extensions = active_action.get("extensions")
    baseline = (
        extensions.get("test_evidence_baseline")
        if isinstance(extensions, Mapping)
        else None
    )
    if not isinstance(baseline, Mapping):
        context = active_action.get("context")
        baseline = (
            context.get("test_evidence_baseline")
            if isinstance(context, Mapping)
            else None
        )
    return baseline if isinstance(baseline, Mapping) else {}


class TestEvidenceIntegrityGuardrail(Guardrail):
    """Reject a Developer result that removes previously witnessed assertions."""

    name = "TestEvidenceIntegrityGuardrail"
    timing = "post"
    applies_to_stages = ("developer",)

    def check(
        self,
        stage: str,
        state: object,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        root = project_root or Path.cwd()
        baseline = _baseline_from_state(state)
        if not baseline:
            return GuardrailResult()

        changed = {
            item for item in getattr(state, "files_changed", []) or []
            if isinstance(item, str)
        }
        weakened: list[str] = []
        for raw_path, expected in baseline.items():
            if raw_path not in changed or not isinstance(expected, Mapping):
                continue
            expected_count = expected.get("assertion_count")
            if not isinstance(expected_count, int) or isinstance(expected_count, bool):
                continue
            resolved_item = _resolve_relative_file(raw_path, root)
            if resolved_item is None:
                continue
            _, resolved = resolved_item
            try:
                current_count = count_test_assertions(
                    resolved.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError):
                continue
            if current_count < expected_count:
                weakened.append(f"{raw_path} ({expected_count}→{current_count})")

        if weakened:
            return GuardrailResult(
                action="retry",
                message=(
                    "测试证据完整性检查失败：检测到测试断言减少："
                    + ", ".join(weakened[:5])
                    + "。请恢复被删除的断言；PII 修复只能替换 fake 夹具或运行时拼接值，"
                    "不得修改断言、伪造测试统计或删除测试来隐藏失败。"
                ),
            )
        return GuardrailResult()


__all__ = [
    "TestEvidenceIntegrityGuardrail",
    "collect_test_assertion_baseline",
    "count_test_assertions",
]
