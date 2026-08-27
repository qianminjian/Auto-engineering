"""统一设计工程模型的稳定身份与追溯关系。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.engineering_model import (
    EngineeringModel,
    EngineeringModelError,
)


def _parse(tmp_path: Path, name: str, content: str) -> DesignDoc:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return DesignDoc.parse(path)


def test_section_identity_survives_display_title_changes(tmp_path: Path) -> None:
    first = EngineeringModel.from_design_doc(
        _parse(
            tmp_path,
            "first.md",
            "## B1 页面\n### C1 上传\n明确上传契约。\n",
        ),
        design_digest="sha256:" + "1" * 64,
    )
    renamed = EngineeringModel.from_design_doc(
        _parse(
            tmp_path,
            "renamed.md",
            "## B1 页面新版\n### C1 上传组件\n明确上传契约。\n",
        ),
        design_digest="sha256:" + "2" * 64,
    )

    assert first.sections[0].section_id == renamed.sections[0].section_id
    assert first.sections[0].design_section == "§C1"
    assert first.sections[0].title == "上传"


def test_trace_links_section_gap_task_and_evidence(tmp_path: Path) -> None:
    model = EngineeringModel.from_design_doc(
        _parse(
            tmp_path,
            "design.md",
            "## B1 页面\n### C1 上传\n明确上传契约。\n",
        ),
        design_digest="sha256:" + "a" * 64,
    )
    section_id = model.sections[0].section_id

    model = model.bind_gap(section_id=section_id, gap_id="GAP-1")
    model = model.bind_task(source_id="GAP-1", task_id="B1-T1")
    model = model.bind_evidence(task_id="B1-T1", evidence_id="sha256:evidence")

    assert model.trace("sha256:evidence") == (
        section_id,
        "GAP-1",
        "B1-T1",
        "sha256:evidence",
    )


def test_trace_rejects_unknown_source(tmp_path: Path) -> None:
    model = EngineeringModel.from_design_doc(
        _parse(tmp_path, "design.md", "## B1 页面\n### C1 上传\n内容\n"),
        design_digest="sha256:" + "b" * 64,
    )

    with pytest.raises(EngineeringModelError, match="ENGINEERING_SOURCE_UNKNOWN"):
        model.bind_task(source_id="GAP-MISSING", task_id="B1-T1")


def test_select_sections_accepts_stable_id_and_legacy_display_ref(
    tmp_path: Path,
) -> None:
    model = EngineeringModel.from_design_doc(
        _parse(tmp_path, "design.md", "## B1 页面\n### C1 上传\n内容\n"),
        design_digest="sha256:" + "c" * 64,
    )
    section = model.sections[0]

    assert model.select_sections([section.section_id]) == (section,)
    assert model.select_sections(["§C1", "上传"]) == (section,)
    assert model.select_sections(["§C1 上传"]) == (section,)


def test_select_sections_rejects_unknown_ref(tmp_path: Path) -> None:
    model = EngineeringModel.from_design_doc(
        _parse(tmp_path, "design.md", "## B1 页面\n### C1 上传\n内容\n"),
        design_digest="sha256:" + "d" * 64,
    )

    with pytest.raises(EngineeringModelError, match="ENGINEERING_SECTION_UNKNOWN"):
        model.select_sections(["不存在的章节"])


def test_host_sections_expose_readable_unique_refs_without_core_ids(
    tmp_path: Path,
) -> None:
    """Agent 只应看到可读引用，Core 哈希身份不得成为输出负担。"""

    model = EngineeringModel.from_design_doc(
        _parse(
            tmp_path,
            "design.md",
            "## B1 页面\n### C1 上传\n内容\n### C2 克隆\n内容\n",
        ),
        design_digest="sha256:" + "e" * 64,
    )

    sections = model.host_sections()

    assert [item["section_ref"] for item in sections] == ["§C1", "§C2"]
    assert all("section_id" not in item for item in sections)
    assert len({item["section_ref"] for item in sections}) == len(sections)
