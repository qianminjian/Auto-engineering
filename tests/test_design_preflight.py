"""设计输入 preflight 的确定性边界。"""

from pathlib import Path

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.design_preflight import (
    DESIGN_STRUCTURE_PREFLIGHT_REQUIRED,
    inspect_design_doc,
)


def _parse(tmp_path: Path, content: str) -> DesignDoc:
    path = tmp_path / "design.md"
    path.write_text(content, encoding="utf-8")
    return DesignDoc.parse(path)


def test_unstructured_design_is_rejected_before_gap_scan(tmp_path: Path) -> None:
    result = inspect_design_doc(_parse(tmp_path, "# title\n\nplain text\n"))

    assert result.valid is False
    assert result.reason_code == DESIGN_STRUCTURE_PREFLIGHT_REQUIRED
    assert result.section_count == 0
    assert result.parse_warnings


def test_h2_only_design_remains_compatible(tmp_path: Path) -> None:
    result = inspect_design_doc(_parse(tmp_path, "## B1 Feature\n\ncontract\n"))

    assert result.valid is True
    assert result.reason_code is None
    assert result.section_count == 1
