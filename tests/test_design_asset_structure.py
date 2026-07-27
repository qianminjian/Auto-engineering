"""当前设计入口与历史归档的结构契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_current_design_entrypoints_are_compact_and_traceable() -> None:
    beacon = (ROOT / "design/BEACON.md").read_text(encoding="utf-8")
    tracker = (
        ROOT / "design/IMPLEMENTATION-TRACKER.md"
    ).read_text(encoding="utf-8")
    index = (ROOT / "design/INDEX.md").read_text(encoding="utf-8")

    assert len(beacon.splitlines()) <= 80
    assert len(tracker.splitlines()) <= 160
    assert "design/archive/INDEX.md" in beacon
    assert "design/archive/INDEX.md" in tracker
    assert "archive/INDEX.md" in index


def test_complete_pre_refactor_history_is_archived() -> None:
    expected = (
        ROOT / "design/archive/legacy/BEACON-pre-phase50.md",
        ROOT
        / "design/archive/legacy/IMPLEMENTATION-TRACKER-pre-phase50.md",
        ROOT / "design/archive/legacy/v5.6-Design-Loop-full-history.md",
    )

    for path in expected:
        assert path.is_file(), f"缺少历史归档: {path}"


def test_current_loop_design_keeps_authoritative_contracts() -> None:
    design = (
        ROOT / "design/v5.6-Design-Loop.md"
    ).read_text(encoding="utf-8")

    for contract in (
        "Tick 协议",
        "Host Adapter",
        "五层验证",
        "Init-Loop",
        "Release 验收",
    ):
        assert contract in design
