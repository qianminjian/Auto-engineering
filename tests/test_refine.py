"""test_refine.py — T20a: B6.10/DS-7 plan_refine 输入契约归一 (RefineRequest).

覆盖 build_refine_request() 确定性归一映射 (设计 §B6.10 line 1163-1171):
  - coverage 源 (component_verifier/system_verifier): MISSING/DIVERGED → RefineGap,
    IMPLEMENTED 跳过
  - audit 源 (plate_deep_audit/system_deep_audit): 去重后 P0 全部 + P1, P2 跳过
  - scope_plate/scope_component 按源层级填充
  - RefineRequest 可 asdict → json 序列化 (跨 tick 持久化 refine_request_json #35)

纯函数, 无 orchestrator/LLM/IO 依赖.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from auto_engineering.loop.refine import (
    RefineGap,
    RefineRequest,
    build_refine_request,
)


def _cov(status: str, design_item: str = "B2-1", *, file: str = "", line: int = 0,
         note: str = "") -> dict:
    return {"design_item": design_item, "status": status,
            "file": file, "line": line, "note": note}


def _finding(severity: str, *, file: str = "x.py", line: int = 10,
             description: str = "bug", suggested_fix: str = "",
             design_section: str = "") -> dict:
    return {"severity": severity, "dimension": "code_quality",
            "agent_source": ["a"], "file": file, "line": line,
            "description": description, "suggested_fix": suggested_fix,
            "design_section": design_section}


class TestCoverageSource:
    def test_missing_becomes_missing_gap(self) -> None:
        req = build_refine_request(
            source="component_verifier", trigger_tick=3,
            scope_plate="P1", scope_component="Foo",
            coverage_map=[_cov("MISSING", "B2-1", note="未实现")],
        )
        assert len(req.gaps) == 1
        g = req.gaps[0]
        assert g.kind == "MISSING"
        assert g.design_ref == "B2-1"
        assert g.detail == "未实现"
        assert g.severity is None
        assert g.location is None
        assert "补充实现" in g.suggested_action

    def test_diverged_becomes_diverged_gap_with_location(self) -> None:
        req = build_refine_request(
            source="component_verifier", trigger_tick=1,
            scope_plate="P1", scope_component="Foo",
            coverage_map=[_cov("DIVERGED", "B2-2", file="foo.py", line=42,
                               note="偏离")],
        )
        assert len(req.gaps) == 1
        g = req.gaps[0]
        assert g.kind == "DIVERGED"
        assert g.location == "foo.py:42"
        assert "判定方向" in g.suggested_action

    def test_implemented_is_skipped(self) -> None:
        req = build_refine_request(
            source="component_verifier", trigger_tick=1,
            scope_plate="P1", scope_component="Foo",
            coverage_map=[
                _cov("IMPLEMENTED", "B2-1"),
                _cov("MISSING", "B2-2"),
            ],
        )
        assert [g.kind for g in req.gaps] == ["MISSING"]

    def test_system_verifier_is_also_coverage_source(self) -> None:
        req = build_refine_request(
            source="system_verifier", trigger_tick=1,
            scope_plate=None, scope_component=None,
            coverage_map=[_cov("MISSING", "B3-1")],
        )
        assert len(req.gaps) == 1
        assert req.gaps[0].kind == "MISSING"


class TestAuditSource:
    def test_p0_and_p1_become_audit_gaps(self) -> None:
        req = build_refine_request(
            source="plate_deep_audit", trigger_tick=2,
            scope_plate="P1", scope_component=None,
            audit_findings=[
                _finding("P0", description="崩溃", suggested_fix="加校验",
                         design_section="§B6"),
                _finding("P1", file="y.py", line=5, description="漏洞"),
            ],
        )
        assert len(req.gaps) == 2
        g0 = req.gaps[0]
        assert g0.kind == "AUDIT_FINDING"
        assert g0.severity == "P0"
        assert g0.design_ref == "§B6"
        assert g0.location == "x.py:10"
        assert g0.suggested_action == "加校验"

    def test_p2_is_skipped(self) -> None:
        req = build_refine_request(
            source="plate_deep_audit", trigger_tick=1,
            scope_plate="P1", scope_component=None,
            audit_findings=[
                _finding("P2", description="风格"),
                _finding("P0", description="崩溃"),
            ],
        )
        assert [g.severity for g in req.gaps] == ["P0"]

    def test_missing_suggested_fix_uses_default(self) -> None:
        req = build_refine_request(
            source="system_deep_audit", trigger_tick=1,
            scope_plate=None, scope_component=None,
            audit_findings=[_finding("P1", suggested_fix="")],
        )
        assert req.gaps[0].suggested_action == "修复该 finding"

    def test_duplicate_findings_deduped_keeping_highest_severity(self) -> None:
        # 同 (file, line, description) 被多 Agent 命中 → 合并, 保留最高 severity
        req = build_refine_request(
            source="plate_deep_audit", trigger_tick=1,
            scope_plate="P1", scope_component=None,
            audit_findings=[
                _finding("P1", file="z.py", line=7, description="同一问题"),
                _finding("P0", file="z.py", line=7, description="同一问题"),
            ],
        )
        assert len(req.gaps) == 1
        assert req.gaps[0].severity == "P0"


class TestCriticSource:
    def test_p0_and_p1_findings_become_traceable_repair_gaps(self) -> None:
        req = build_refine_request(
            source="critic", trigger_tick=6,
            scope_plate=None, scope_component=None,
            critic_findings=[
                {
                    "finding_id": "F-001",
                    "severity": "P1",
                    "kind": "contract_gap",
                    "design_ref": "§11.3",
                    "file": "vitest.setup.ts",
                    "line": 1,
                    "issue": "缺少 cleanup",
                    "suggestion": "注册 afterEach(cleanup)",
                },
                {
                    "finding_id": "F-002",
                    "severity": "P2",
                    "issue": "仅风格问题",
                },
            ],
        )

        assert len(req.gaps) == 1
        gap = req.gaps[0]
        assert gap.kind == "CRITIC_FINDING"
        assert gap.source_ref == "F-001"
        assert gap.design_ref == "§11.3"
        assert gap.detail == "缺少 cleanup"
        assert gap.suggested_action == "注册 afterEach(cleanup)"
        assert gap.location == "vitest.setup.ts:1"

    def test_missing_finding_id_gets_deterministic_source_ref(self) -> None:
        finding = {
            "severity": "P1",
            "kind": "plan_gap",
            "file": "src/a.ts",
            "issue": "计划遗漏",
            "suggestion": "补充任务",
        }
        first = build_refine_request(
            source="critic", trigger_tick=1,
            scope_plate=None, scope_component=None,
            critic_findings=[finding],
        )
        second = build_refine_request(
            source="critic", trigger_tick=99,
            scope_plate=None, scope_component=None,
            critic_findings=[finding],
        )

        assert first.gaps[0].source_ref.startswith("critic:")
        assert first.gaps[0].source_ref == second.gaps[0].source_ref

    def test_legacy_critic_field_names_are_preserved(self) -> None:
        req = build_refine_request(
            source="critic", trigger_tick=1,
            scope_plate=None, scope_component=None,
            critic_findings=[{
                "severity": "P1",
                "description": "旧字段问题",
                "suggested_fix": "旧字段修复",
                "design_section": "§5",
            }],
        )

        assert req.gaps[0].detail == "旧字段问题"
        assert req.gaps[0].suggested_action == "旧字段修复"
        assert req.gaps[0].design_ref == "§5"


class TestScopeAndSerialization:
    def test_scope_fields_preserved(self) -> None:
        req = build_refine_request(
            source="component_verifier", trigger_tick=9,
            scope_plate="Plate-A", scope_component="Comp-B",
            coverage_map=[_cov("MISSING")],
        )
        assert req.source == "component_verifier"
        assert req.trigger_tick == 9
        assert req.scope_plate == "Plate-A"
        assert req.scope_component == "Comp-B"

    def test_asdict_json_roundtrip(self) -> None:
        req = build_refine_request(
            source="plate_deep_audit", trigger_tick=1,
            scope_plate="P1", scope_component=None,
            audit_findings=[_finding("P0")],
        )
        payload = json.dumps(asdict(req))
        back = json.loads(payload)
        assert back["source"] == "plate_deep_audit"
        assert back["gaps"][0]["kind"] == "AUDIT_FINDING"
        # 反序列化回 dataclass
        rebuilt = RefineRequest(
            source=back["source"], trigger_tick=back["trigger_tick"],
            scope_plate=back["scope_plate"], scope_component=back["scope_component"],
            gaps=[RefineGap(**g) for g in back["gaps"]],
        )
        assert rebuilt.gaps[0].severity == "P0"

    def test_empty_when_no_qualifying_items(self) -> None:
        req = build_refine_request(
            source="component_verifier", trigger_tick=1,
            scope_plate=None, scope_component=None,
            coverage_map=[_cov("IMPLEMENTED")],
        )
        assert req.gaps == []
