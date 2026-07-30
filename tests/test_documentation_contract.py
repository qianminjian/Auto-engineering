"""跨宿主用户文档的当前入口契约。"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_CURRENT_DOCS = (
    "README.md",
    "docs/USER_GUIDE.md",
    "docs/api-reference.md",
    "docs/PRODUCT-TRAINING-GUIDE.md",
)


@pytest.mark.parametrize("relative", _CURRENT_DOCS)
def test_current_docs_explain_both_host_entries(relative: str) -> None:
    content = (_ROOT / relative).read_text(encoding="utf-8")

    assert "Claude Code" in content
    assert "Codex" in content
    assert "/auto-engineering:dev-loop" in content
    assert "/ae:" not in content
    assert "$auto-engineering" in content


@pytest.mark.parametrize("relative", _CURRENT_DOCS)
def test_current_docs_include_doctor_and_minimal_tick(relative: str) -> None:
    content = (_ROOT / relative).read_text(encoding="utf-8")

    assert "ae-run doctor" in content
    assert 'ae-run dev-loop --init "需求"' in content


def test_current_capability_sections_do_not_advertise_retired_paths() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    user_intro = "\n".join(
        (_ROOT / "docs/USER_GUIDE.md").read_text(encoding="utf-8").splitlines()[:55]
    )
    api_intro = "\n".join(
        (_ROOT / "docs/api-reference.md").read_text(encoding="utf-8").splitlines()[:45]
    )
    training_intro = "\n".join(
        (_ROOT / "docs/PRODUCT-TRAINING-GUIDE.md")
        .read_text(encoding="utf-8")
        .splitlines()[:120]
    )

    assert "standalone_driver.py" not in readme
    assert "ae gate-check" not in readme
    assert "/ae:checkpoint" not in readme
    assert "v7.0 双驱动架构" not in user_intro
    assert "v5.5 Orchestrator" not in api_intro
    assert "Driver B" not in training_intro
    assert "Standalone 模式可直接嵌入流水线" not in training_intro


@pytest.mark.parametrize("relative", _CURRENT_DOCS)
def test_current_docs_contain_no_retired_command_examples(relative: str) -> None:
    content = (_ROOT / relative).read_text(encoding="utf-8")

    for retired in (
        "ae gate-check",
        "ae agent ",
        "ae checkpoint",
        "ae progress",
        "--standalone",
        "//auto-engineering:dev-loop",
    ):
        assert retired not in content
