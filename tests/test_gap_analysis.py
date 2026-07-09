"""T4c — engine/gap_analysis.py (Pre-flight GapItem / GapReport) 测试.

设计参考: v5.6-Design-Loop.md §B10.2 (GapItem/GapReport) + §B10.3 (分级标准) + §B10.5 (处理路径).

Pre-flight Gap Analysis 在 T1 architect 之前扫描设计文档清晰度:
  - grade (architectural/component/module): 模糊 scope, 驱动阻塞约束
  - clarity (missing/vague/partial): 模糊 kind, 驱动 gap_review 建议路径
  - has_blocking: 存在 architectural gap → 不允许全部 defer (B10.5 约束)

grade/clarity 由 gap_scan Agent (LLM) 判定; 本模块只提供数据结构 +
has_blocking 计算 + resolution 管理/校验 + 序列化 (确定性 Python).

测试原则 (per pytest-memory-management.md): 单文件 pytest --timeout=60.
"""

from __future__ import annotations

import pytest

from auto_engineering.engine.gap_analysis import GapItem, GapReport


def _gap(gid: str, grade: str, clarity: str = "vague", resolution: str = "pending") -> GapItem:
    return GapItem(
        id=gid,
        design_section_ref=f"§{gid}",
        node_id=None,
        grade=grade,
        clarity=clarity,
        summary=f"{gid} 缺口",
        depends_on=[],
        resolution=resolution,
    )


# ---------- GapItem ----------


class TestGapItem:
    def test_fields_and_defaults(self) -> None:
        g = GapItem(id="gap-B6.2", design_section_ref="§B6.2", node_id="§B6.2",
                    grade="component", clarity="vague", summary="接口未定义",
                    depends_on=["gap-B6.1"])
        assert g.id == "gap-B6.2"
        assert g.grade == "component"
        assert g.clarity == "vague"
        assert g.depends_on == ["gap-B6.1"]
        assert g.resolution == "pending"
        assert g.user_note is None


# ---------- GapReport ----------


class TestGapReport:
    def test_has_blocking_true_when_architectural_present(self) -> None:
        report = GapReport(
            gaps=[_gap("g1", "architectural"), _gap("g2", "component")],
            scanned_sections=5,
        )
        assert report.has_blocking is True

    def test_has_blocking_false_without_architectural(self) -> None:
        report = GapReport(
            gaps=[_gap("g1", "component"), _gap("g2", "module")],
            scanned_sections=5,
        )
        assert report.has_blocking is False

    def test_has_blocking_false_empty(self) -> None:
        assert GapReport(gaps=[], scanned_sections=3).has_blocking is False

    def test_pending_filters_unresolved(self) -> None:
        report = GapReport(
            gaps=[_gap("g1", "component", resolution="fill"),
                  _gap("g2", "module", resolution="pending")],
            scanned_sections=2,
        )
        pending = report.pending()
        assert [g.id for g in pending] == ["g2"]

    def test_blocking_gaps_returns_architectural(self) -> None:
        report = GapReport(
            gaps=[_gap("g1", "architectural"), _gap("g2", "component"),
                  _gap("g3", "architectural")],
            scanned_sections=3,
        )
        assert {g.id for g in report.blocking_gaps()} == {"g1", "g3"}

    def test_set_resolution_updates_gap(self) -> None:
        report = GapReport(gaps=[_gap("g1", "component")], scanned_sections=1)
        report.set_resolution("g1", "fill", user_note="补充接口定义")
        g = report.gaps[0]
        assert g.resolution == "fill"
        assert g.user_note == "补充接口定义"

    def test_set_resolution_invalid_value_raises(self) -> None:
        report = GapReport(gaps=[_gap("g1", "component")], scanned_sections=1)
        with pytest.raises(ValueError, match="resolution"):
            report.set_resolution("g1", "bogus")

    def test_set_resolution_unknown_id_raises(self) -> None:
        report = GapReport(gaps=[_gap("g1", "component")], scanned_sections=1)
        with pytest.raises(KeyError):
            report.set_resolution("nope", "fill")

    def test_validate_resolutions_architectural_defer_is_violation(self) -> None:
        """architectural gap 选 defer/defer_research → 违规 (B10.5: 不允许全部 defer)."""
        report = GapReport(
            gaps=[_gap("g1", "architectural", resolution="defer"),
                  _gap("g2", "architectural", resolution="defer_research"),
                  _gap("g3", "architectural", resolution="fill")],
            scanned_sections=3,
        )
        violations = report.validate_resolutions()
        assert set(violations) == {"g1", "g2"}

    def test_validate_resolutions_component_defer_ok(self) -> None:
        report = GapReport(
            gaps=[_gap("g1", "component", resolution="defer"),
                  _gap("g2", "module", resolution="defer_research")],
            scanned_sections=2,
        )
        assert report.validate_resolutions() == []

    def test_has_pending(self) -> None:
        r1 = GapReport(gaps=[_gap("g1", "component", resolution="fill")], scanned_sections=1)
        r2 = GapReport(gaps=[_gap("g1", "component", resolution="pending")], scanned_sections=1)
        assert r1.has_pending() is False
        assert r2.has_pending() is True


# ---------- 序列化 ----------


class TestSerialization:
    def _report(self) -> GapReport:
        return GapReport(
            gaps=[_gap("g1", "architectural", clarity="missing"),
                  _gap("g2", "component", resolution="fill")],
            scanned_sections=7,
        )

    def test_to_dict_from_dict_round_trip(self) -> None:
        report = self._report()
        d = report.to_dict()
        restored = GapReport.from_dict(d)
        assert restored.scanned_sections == 7
        assert restored.has_blocking is True
        assert [g.id for g in restored.gaps] == ["g1", "g2"]
        assert restored.gaps[1].resolution == "fill"

    def test_to_json_from_json_round_trip(self) -> None:
        report = self._report()
        s = report.to_json()
        restored = GapReport.from_json(s)
        assert restored.scanned_sections == 7
        assert restored.gaps[0].clarity == "missing"
        assert restored.gaps[0].grade == "architectural"
