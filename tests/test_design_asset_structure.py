"""当前设计入口、双基线与历史摘要的结构契约。"""

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
    for entrypoint in (
        "design/v5.8-Session-Decoupling-Design.md",
        "design/v5.8-Session-Decoupling-PLAN.md",
        "design/incidents/2026-07-29-claude-146-tick-long-run.md",
        "design/IMPLEMENTATION-TRACKER.md",
        "design/HISTORY.md",
    ):
        assert entrypoint in beacon
    assert "v5.6-Design-Loop.md" in index
    assert "v5.7-Protocol-Kernel-Design.md" in index
    assert "HISTORY.md" in tracker


def test_current_design_assets_exist() -> None:
    expected = (
        ROOT / "design/BEACON.md",
        ROOT / "design/v5.6-Design-Loop.md",
        ROOT / "design/v5.7-Protocol-Kernel-Design.md",
        ROOT / "design/v5.7-Protocol-Kernel-PLAN.md",
        ROOT / "design/IMPLEMENTATION-TRACKER.md",
        ROOT / "design/HISTORY.md",
    )

    for path in expected:
        assert path.is_file(), f"缺少当前设计资产: {path}"


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
